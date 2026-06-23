"""DEVI-04 — اندازه‌گیریِ سه تعریفِ درآمدِ حسابداری روی دادهٔ زنده (READ-ONLY).

اولین کارِ مطلقِ نقشهٔ مهاجرت (migration_plan.md §۳): پیش از طراحیِ oracle/canonical،
باید بدانیم سه تعریفِ درآمد روی دادهٔ واقعی چقدر اختلاف دارند.

تعریف‌ها (تأییدشده در src/adapters/accounting_bridge.py):
  billed (الف)   = Σ(visits.price + injections.total_price + procedures.price)، فقط فاکتورِ closed
  total  (ب)     = Σ invoices.total_amount (سهمِ بیمارِ ذخیره‌شده)، closed
  collected (ج)  = همان آیتم‌های billed که invoice_item_payments.is_paid=1 (پرداختیِ واقعی)
  + تشخیصی: سهمِ consumables_ledger در total_amount (گاتچا #۱۰: در total هست، در billed نیست)

ایمنی (نگرانیِ #۱): اتصال فقط mode=ro؛ SHA-256 فایل قبل/بعد باید یکسان بماند (zero-write).
خروجی: per_invoice.csv + per_day_insurance.csv + خلاصهٔ کنسول.
"""
import sqlite3, hashlib, os, csv

REPO = r"C:/Users/Emad Karimi/Desktop/projects/hesabdari_darmangah"
DB = os.environ.get("ACCOUNTING_DB_PATH", REPO + "/webapp/clinic_new.db")
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devi04_out")
os.makedirs(OUTDIR, exist_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


def f(x):
    return float(x or 0)


before = sha256(DB)
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

invs = conn.execute(
    "SELECT id, patient_id, work_date, insurance_type, supplementary_insurance, total_amount "
    "FROM invoices WHERE status='closed' ORDER BY work_date, id"
).fetchall()

# consumables_ledger introspection (diagnostic for gotcha #10)
cl_cols = [r["name"] for r in conn.execute("PRAGMA table_info(consumables_ledger)").fetchall()]
cl_has_invoice = "invoice_id" in cl_cols
# pick the most likely patient-share column present
cl_amount_col = next((c for c in ("patient_share", "patient_amount", "total_cost", "total_price", "amount", "price")
                      if c in cl_cols), None)


def billed_for(inv_id):
    v = conn.execute("SELECT COALESCE(SUM(price),0) s FROM visits WHERE invoice_id=?", (inv_id,)).fetchone()["s"]
    j = conn.execute("SELECT COALESCE(SUM(total_price),0) s FROM injections WHERE invoice_id=?", (inv_id,)).fetchone()["s"]
    p = conn.execute("SELECT COALESCE(SUM(price),0) s FROM procedures WHERE invoice_id=?", (inv_id,)).fetchone()["s"]
    return f(v) + f(j) + f(p)


def collected_for(inv_id):
    out = 0.0
    for tbl, col, it in (("visits", "price", "visit"), ("injections", "total_price", "injection"),
                         ("procedures", "price", "procedure")):
        s = conn.execute(
            f"""SELECT COALESCE(SUM(t.{col}),0) s FROM {tbl} t
                JOIN invoice_item_payments iip
                  ON iip.invoice_id=t.invoice_id AND iip.item_type=? AND iip.item_id=t.id AND iip.is_paid=1
                WHERE t.invoice_id=?""", (it, inv_id)).fetchone()["s"]
        out += f(s)
    return out


def consumable_for(inv_id):
    if not (cl_has_invoice and cl_amount_col):
        return 0.0
    s = conn.execute(
        f"SELECT COALESCE(SUM({cl_amount_col}),0) s FROM consumables_ledger WHERE invoice_id=?",
        (inv_id,)).fetchone()["s"]
    return f(s)


rows = []
for inv in invs:
    iid = inv["id"]
    billed = billed_for(iid)
    collected = collected_for(iid)
    total = f(inv["total_amount"])
    consum = consumable_for(iid)
    rows.append({
        "invoice_id": iid,
        "work_date": inv["work_date"] or "",
        "insurance_type": inv["insurance_type"] or "(none)",
        "supplementary": inv["supplementary_insurance"] or "",
        "billed_raw": round(billed),
        "total_amount": round(total),
        "collected": round(collected),
        "consumable_in_total": round(consum),
        "diff_total_minus_billed": round(total - billed),
        "uncollected_billed": round(billed - collected),
    })

# ---- per-invoice CSV ----
inv_csv = os.path.join(OUTDIR, "per_invoice.csv")
with open(inv_csv, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                       ["invoice_id", "work_date", "insurance_type", "supplementary", "billed_raw",
                        "total_amount", "collected", "consumable_in_total",
                        "diff_total_minus_billed", "uncollected_billed"])
    w.writeheader()
    for r in rows:
        w.writerow(r)

# ---- per (work_date, insurance) aggregate ----
agg = {}
for r in rows:
    k = (r["work_date"], r["insurance_type"])
    a = agg.setdefault(k, {"work_date": r["work_date"], "insurance_type": r["insurance_type"],
                           "n_invoices": 0, "billed_raw": 0, "total_amount": 0, "collected": 0,
                           "consumable_in_total": 0})
    a["n_invoices"] += 1
    a["billed_raw"] += r["billed_raw"]
    a["total_amount"] += r["total_amount"]
    a["collected"] += r["collected"]
    a["consumable_in_total"] += r["consumable_in_total"]

day_csv = os.path.join(OUTDIR, "per_day_insurance.csv")
with open(day_csv, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=["work_date", "insurance_type", "n_invoices", "billed_raw",
                                       "total_amount", "collected", "consumable_in_total"])
    w.writeheader()
    for a in sorted(agg.values(), key=lambda x: (x["work_date"], x["insurance_type"])):
        w.writerow(a)

# ---- grand totals ----
tot_billed = sum(r["billed_raw"] for r in rows)
tot_total = sum(r["total_amount"] for r in rows)
tot_coll = sum(r["collected"] for r in rows)
tot_consum = sum(r["consumable_in_total"] for r in rows)

conn.close()
after = sha256(DB)

print("=" * 64)
print("DEVI-04 — اندازه‌گیریِ سه تعریفِ درآمد (READ-ONLY)")
print("=" * 64)
print(f"DB: {DB}")
print(f"SHA-256 before: {before}")
print(f"SHA-256 after : {after}")
print(f"ZERO-WRITE: {'OK ✅ (فایل دست‌نخورده)' if before == after else 'FAIL ❌ فایل تغییر کرد!'}")
print(f"consumables_ledger: invoice_id={cl_has_invoice} amount_col={cl_amount_col!r}")
print("-" * 64)
print(f"فاکتورهای closed: {len(rows)}")
print(f"  billed (raw items, الف)        = {tot_billed:,}")
print(f"  total_amount (سهم بیمار, ب)     = {tot_total:,}")
print(f"  collected (پرداختی واقعی, ج)    = {tot_coll:,}")
print(f"  consumable_in_total (تشخیصی)   = {tot_consum:,}")
print("-" * 64)
if tot_billed:
    print(f"نسبت total_amount/billed = {tot_total/tot_billed:.3f}  (سهم بیمار از قیمت کامل)")
if tot_total:
    print(f"نسبت collected/total_amount = {tot_coll/tot_total:.3f}  (نرخ وصول نسبت به سهم بیمار)")
if tot_billed:
    print(f"نسبت collected/billed = {tot_coll/tot_billed:.3f}")
print("-" * 64)
print("per-invoice:")
hdr = ("inv", "work_date", "insurance", "billed", "total_amt", "collected", "Δtot-bill")
print("  " + " | ".join(f"{h:>10}" for h in hdr))
for r in rows:
    print("  " + " | ".join(f"{str(x):>10}" for x in (
        r["invoice_id"], r["work_date"], r["insurance_type"][:10], r["billed_raw"],
        r["total_amount"], r["collected"], r["diff_total_minus_billed"])))
print("-" * 64)
print(f"CSV per-invoice: {inv_csv}")
print(f"CSV per-day    : {day_csv}")

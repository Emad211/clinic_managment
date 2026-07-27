from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECIALIST = ROOT / "specialist_clinic"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.rstrip() + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == normalized:
        return
    path.write_text(normalized, encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A13 anchor missing in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_block(path: Path, start: str, end: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    start_at = text.find(start)
    if start_at < 0:
        raise RuntimeError(f"A13 start anchor missing in {path}: {start!r}")
    end_at = text.find(end, start_at)
    if end_at < 0:
        raise RuntimeError(f"A13 end anchor missing in {path}: {end!r}")
    path.write_text(text[:start_at] + replacement + text[end_at:], encoding="utf-8")


schema = SPECIALIST / "src/adapters/sqlite/schema.sql"
schema_block = r'''

-- A13: immutable, content-bound dual review of every rule before SILENT freeze.
CREATE TABLE IF NOT EXISTS clinical_rule_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset_id INTEGER NOT NULL,
    rule_version_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('CLINICAL', 'TECHNICAL')),
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REQUEST_CHANGES')),
    ruleset_content_hash TEXT NOT NULL,
    rule_content_hash TEXT NOT NULL,
    package_hash TEXT NOT NULL,
    case_bundle_hash TEXT NOT NULL,
    reviewer_username TEXT NOT NULL,
    reviewer_display_name TEXT NOT NULL,
    note TEXT NOT NULL,
    supersedes_event_id INTEGER,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(ruleset_id) REFERENCES clinical_rulesets(id),
    FOREIGN KEY(rule_version_id) REFERENCES clinical_rule_versions(id),
    FOREIGN KEY(supersedes_event_id) REFERENCES clinical_rule_review_events(id)
);
CREATE INDEX IF NOT EXISTS idx_rule_review_latest
ON clinical_rule_review_events(ruleset_id, rule_version_id, role, id DESC);
CREATE INDEX IF NOT EXISTS idx_rule_review_actor
ON clinical_rule_review_events(ruleset_id, reviewer_username, role, id DESC);

CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_no_update
BEFORE UPDATE ON clinical_rule_review_events BEGIN
    SELECT RAISE(ABORT, 'clinical rule review events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_no_delete
BEFORE DELETE ON clinical_rule_review_events BEGIN
    SELECT RAISE(ABORT, 'clinical rule review events cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_draft_only
BEFORE INSERT ON clinical_rule_review_events
WHEN (SELECT status FROM clinical_rulesets WHERE id=NEW.ruleset_id) <> 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'rule review events require a DRAFT ruleset');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_identity_match
BEFORE INSERT ON clinical_rule_review_events
WHEN NOT EXISTS (
    SELECT 1
    FROM clinical_ruleset_members m
    JOIN clinical_rulesets s ON s.id=m.ruleset_id
    JOIN clinical_rule_versions r ON r.id=m.rule_version_id
    WHERE m.ruleset_id=NEW.ruleset_id
      AND m.rule_version_id=NEW.rule_version_id
      AND s.content_hash=NEW.ruleset_content_hash
      AND r.content_hash=NEW.rule_content_hash
)
BEGIN
    SELECT RAISE(ABORT, 'rule review identity or content hash mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_supersedes_match
BEFORE INSERT ON clinical_rule_review_events
WHEN NEW.supersedes_event_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM clinical_rule_review_events prior
    WHERE prior.id=NEW.supersedes_event_id
      AND prior.ruleset_id=NEW.ruleset_id
      AND prior.rule_version_id=NEW.rule_version_id
      AND prior.role=NEW.role
 )
BEGIN
    SELECT RAISE(ABORT, 'review supersession must stay in the same rule and role');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_role_separation
BEFORE INSERT ON clinical_rule_review_events
WHEN EXISTS (
    SELECT 1 FROM clinical_rule_review_events prior
    WHERE prior.ruleset_id=NEW.ruleset_id
      AND prior.role<>NEW.role
      AND prior.reviewer_username=NEW.reviewer_username
)
BEGIN
    SELECT RAISE(ABORT, 'one account cannot review both clinical and technical roles');
END;
'''
if "CREATE TABLE IF NOT EXISTS clinical_rule_review_events" not in schema.read_text(encoding="utf-8"):
    schema.write_text(schema.read_text(encoding="utf-8").rstrip() + schema_block + "\n", encoding="utf-8")

core = SPECIALIST / "src/adapters/sqlite/core.py"
replace_once(
    core,
    '    "clinical_flag_events",\n})',
    '    "clinical_flag_events",\n    "clinical_rule_review_events",\n})',
)
replace_once(
    core,
    '    "trg_ruleset_members_no_delete",\n})',
    '    "trg_ruleset_members_no_delete",\n'
    '    "trg_rule_review_events_no_update",\n'
    '    "trg_rule_review_events_no_delete",\n'
    '    "trg_rule_review_events_draft_only",\n'
    '    "trg_rule_review_events_identity_match",\n'
    '    "trg_rule_review_events_supersedes_match",\n'
    '    "trg_rule_review_events_role_separation",\n})',
)

write(
    SPECIALIST / "src/adapters/sqlite/clinical_engine_rule_review_repo.py",
    r'''"""Append-only, content-bound dual review for Clinical Engine rule packages."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.adapters.sqlite.core import get_db

from .clinical_engine_rules_common import content_hash, now_text


_ROLES = frozenset({"CLINICAL", "TECHNICAL"})
_DECISIONS = frozenset({"APPROVE", "REQUEST_CHANGES"})


class RuleReviewRepositoryMixin:
    """Persist latest-by-event review projections without mutable review rows."""

    def append_package_reviews(
        self,
        ruleset_id: int,
        *,
        role: str,
        decisions: Mapping[str, str],
        package_hash: str,
        case_bundle_hash: str,
        reviewer_username: str,
        reviewer_display_name: str,
        note: str,
    ) -> dict[str, Any]:
        normalized_role = str(role or "").strip().upper()
        username = str(reviewer_username or "").strip()
        display_name = str(reviewer_display_name or "").strip()
        review_note = str(note or "").strip()
        package_digest = str(package_hash or "").strip()
        case_digest = str(case_bundle_hash or "").strip()
        if normalized_role not in _ROLES:
            raise ValueError("review role must be CLINICAL or TECHNICAL")
        if not username or not display_name or not review_note:
            raise ValueError("authenticated reviewer identity and note are required")
        if not package_digest or not case_digest:
            raise ValueError("package and validation-case hashes are required")

        ruleset = self.get_ruleset(int(ruleset_id))
        if not ruleset:
            raise LookupError("ruleset not found")
        if ruleset["status"] != "DRAFT":
            raise ValueError("reviews can only be appended to a DRAFT ruleset")
        expected_codes = {str(item["rule_code"]) for item in ruleset["members"]}
        normalized_decisions = {
            str(code): str(decision or "").strip().upper()
            for code, decision in dict(decisions or {}).items()
        }
        if set(normalized_decisions) != expected_codes:
            raise ValueError("every ruleset member requires an explicit review decision")
        invalid = sorted(
            code for code, decision in normalized_decisions.items()
            if decision not in _DECISIONS
        )
        if invalid:
            raise ValueError("invalid review decision for: " + ", ".join(invalid))

        db = get_db()
        opposite = db.execute(
            """SELECT 1 FROM clinical_rule_review_events
               WHERE ruleset_id=? AND role<>? AND reviewer_username=? LIMIT 1""",
            (int(ruleset_id), normalized_role, username),
        ).fetchone()
        if opposite:
            raise ValueError(
                "یک حساب کاربری نمی‌تواند هر دو نقش بازبینی بالینی و فنی را ثبت کند"
            )

        created_at = now_text()
        with db:
            for member in ruleset["members"]:
                rule_code = str(member["rule_code"])
                rule_version_id = int(member["rule_version_id"])
                prior = db.execute(
                    """SELECT id FROM clinical_rule_review_events
                       WHERE ruleset_id=? AND rule_version_id=? AND role=?
                       ORDER BY id DESC LIMIT 1""",
                    (int(ruleset_id), rule_version_id, normalized_role),
                ).fetchone()
                identity = {
                    "ruleset_id": int(ruleset_id),
                    "rule_version_id": rule_version_id,
                    "role": normalized_role,
                    "decision": normalized_decisions[rule_code],
                    "ruleset_content_hash": str(ruleset["content_hash"]),
                    "rule_content_hash": str(member["content_hash"]),
                    "package_hash": package_digest,
                    "case_bundle_hash": case_digest,
                    "reviewer_username": username,
                    "reviewer_display_name": display_name,
                    "note": review_note,
                    "supersedes_event_id": int(prior["id"]) if prior else None,
                }
                idempotency_key = content_hash(identity)
                if db.execute(
                    "SELECT id FROM clinical_rule_review_events WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone():
                    continue
                db.execute(
                    """INSERT INTO clinical_rule_review_events
                       (ruleset_id, rule_version_id, role, decision,
                        ruleset_content_hash, rule_content_hash, package_hash,
                        case_bundle_hash, reviewer_username, reviewer_display_name,
                        note, supersedes_event_id, idempotency_key, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(ruleset_id), rule_version_id, normalized_role,
                        normalized_decisions[rule_code], str(ruleset["content_hash"]),
                        str(member["content_hash"]), package_digest, case_digest,
                        username, display_name, review_note,
                        int(prior["id"]) if prior else None,
                        idempotency_key, created_at,
                    ),
                )
        return self.rule_review_summary(int(ruleset_id))

    def latest_rule_reviews(self, ruleset_id: int) -> list[dict[str, Any]]:
        rows = get_db().execute(
            """SELECT event.*, version.rule_code
               FROM clinical_rule_review_events event
               JOIN clinical_rule_versions version
                 ON version.id=event.rule_version_id
               WHERE event.ruleset_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_rule_review_events child
                     WHERE child.ruleset_id=event.ruleset_id
                       AND child.rule_version_id=event.rule_version_id
                       AND child.role=event.role
                       AND child.id>event.id
                 )
               ORDER BY version.rule_code, event.role""",
            (int(ruleset_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def rule_review_summary(self, ruleset_id: int) -> dict[str, Any]:
        ruleset = self.get_ruleset(int(ruleset_id))
        if not ruleset:
            raise LookupError("ruleset not found")
        events = self.latest_rule_reviews(int(ruleset_id))
        by_rule: dict[str, dict[str, dict[str, Any] | None]] = {
            str(member["rule_code"]): {"clinical": None, "technical": None}
            for member in ruleset["members"]
        }
        for event in events:
            by_rule[str(event["rule_code"])][str(event["role"]).lower()] = event

        role_projection: dict[str, dict[str, Any]] = {}
        for role in ("clinical", "technical"):
            records = [by_rule[code][role] for code in sorted(by_rule)]
            reviewers = {
                str(record["reviewer_username"])
                for record in records if record is not None
            }
            complete = bool(records) and all(
                record is not None and record["decision"] == "APPROVE"
                for record in records
            ) and len(reviewers) == 1
            role_projection[role] = {
                "complete": complete,
                "reviewer_username": next(iter(reviewers)) if len(reviewers) == 1 else None,
                "reviewer_display_name": (
                    next(
                        str(record["reviewer_display_name"])
                        for record in records if record is not None
                    ) if len(reviewers) == 1 else None
                ),
                "approved_count": sum(
                    1 for record in records
                    if record is not None and record["decision"] == "APPROVE"
                ),
                "changes_requested_count": sum(
                    1 for record in records
                    if record is not None and record["decision"] == "REQUEST_CHANGES"
                ),
                "total": len(records),
            }

        distinct = bool(
            role_projection["clinical"]["reviewer_username"]
            and role_projection["technical"]["reviewer_username"]
            and role_projection["clinical"]["reviewer_username"]
            != role_projection["technical"]["reviewer_username"]
        )
        ready = bool(
            ruleset["status"] == "DRAFT"
            and role_projection["clinical"]["complete"]
            and role_projection["technical"]["complete"]
            and distinct
        )
        blockers: list[str] = []
        for role, label in (("clinical", "بازبینی بالینی"), ("technical", "بازبینی فنی")):
            if not role_projection[role]["complete"]:
                blockers.append(label + " همهٔ قواعد کامل و تأییدشده نیست")
        if (
            role_projection["clinical"]["complete"]
            and role_projection["technical"]["complete"]
            and not distinct
        ):
            blockers.append("بازبین بالینی و فنی باید دو حساب کاربری مستقل باشند")
        return {
            "rules": by_rule,
            "roles": role_projection,
            "distinct_reviewers": distinct,
            "ready_to_freeze": ready,
            "blockers": blockers,
            "event_count": len(events),
        }
''',
)

facade = SPECIALIST / "src/adapters/sqlite/clinical_engine_rules_repo.py"
replace_once(
    facade,
    "from .clinical_engine_rule_projection_repo import RuleProjectionRepositoryMixin\n",
    "from .clinical_engine_rule_projection_repo import RuleProjectionRepositoryMixin\n"
    "from .clinical_engine_rule_review_repo import RuleReviewRepositoryMixin\n",
)
replace_once(
    facade,
    "    RuleVersionRepositoryMixin,\n    RulesetRepositoryMixin,\n",
    "    RuleVersionRepositoryMixin,\n    RulesetRepositoryMixin,\n    RuleReviewRepositoryMixin,\n",
)

service = SPECIALIST / "src/services/clinical_engine/package_service.py"
replace_once(
    service,
    '    "observation.egfr": "آخرین eGFR",\n',
    '    "observation.egfr": "آخرین eGFR",\n'
    '    "observation.hba1c": "آخرین HbA1c",\n'
    '    "observation.uacr": "آخرین نسبت آلبومین به کراتینین ادرار",\n'
    '    "observation.keys": "فهرست آزمایش‌های ثبت‌شده",\n',
)
replace_once(
    service,
    '    "has": "شامل",\n',
    '    "has": "شامل",\n    "not_has": "شامل نیست",\n',
)
replace_block(
    service,
    "    def approve_and_freeze(",
    "    def reset(",
    r'''    def _current_package_and_ruleset(self, ruleset_id: int):
        package = load_rule_package(
            _package_dir(),
            expected_version=PACKAGE_VERSION,
            expected_ruleset_code=RULESET_CODE,
            compiler=self.compiler,
        )
        ruleset = self.rules.get_ruleset(int(ruleset_id))
        if not ruleset or ruleset["ruleset_code"] != RULESET_CODE:
            raise LookupError("بستهٔ قواعد پیدا نشد")
        if base_ruleset_version(ruleset.get("version")) != PACKAGE_VERSION:
            raise ValueError("این بسته قدیمی است؛ ابتدا بستهٔ اصلاح‌شدهٔ فعلی را آماده کنید")
        if ruleset["status"] != "DRAFT":
            raise ValueError("فقط بستهٔ DRAFT قابل بازبینی یا فریز است")
        expected_hashes = {
            compiled.definition.rule_code: compiled.content_hash
            for compiled in package.compiled_rules
        }
        stored_hashes = {
            str(member["rule_code"]): str(member["content_hash"])
            for member in ruleset["members"]
        }
        if stored_hashes != expected_hashes:
            raise ValueError("اعضای بستهٔ ذخیره‌شده با بستهٔ immutable برنامه یکسان نیستند")
        return package, ruleset

    def review_rules(
        self,
        ruleset_id: int,
        *,
        role: str,
        decisions: dict[str, str],
        actor_username: str,
        reviewer_display_name: str,
        note: str,
    ) -> dict:
        package, ruleset = self._current_package_and_ruleset(int(ruleset_id))
        summary = self.rules.append_package_reviews(
            int(ruleset["id"]),
            role=role,
            decisions=decisions,
            package_hash=package.package_hash,
            case_bundle_hash=package.case_bundle_hash,
            reviewer_username=actor_username,
            reviewer_display_name=reviewer_display_name,
            note=note,
        )
        log_activity(
            "clinical_v2_rule_review",
            f"Recorded {str(role).upper()} review for ruleset {ruleset_id}; "
            f"package={package.package_hash}; cases={package.case_bundle_hash}",
            user_id=0,
            username=str(actor_username or "").strip(),
        )
        return summary

    def freeze_reviewed_package(
        self,
        ruleset_id: int,
        *,
        activated_by: str,
        note: str,
    ) -> dict:
        actor = str(activated_by or "").strip()
        freeze_note = str(note or "").strip()
        if not actor or not freeze_note:
            raise ValueError("نام فعال‌ساز و یادداشت فریز الزامی است")
        package, ruleset = self._current_package_and_ruleset(int(ruleset_id))
        summary = self.rules.rule_review_summary(int(ruleset["id"]))
        if not summary["ready_to_freeze"]:
            raise ValueError(
                "بسته هنوز دو بازبینی مستقل و کامل ندارد: "
                + "؛ ".join(summary["blockers"])
            )
        clinical = summary["roles"]["clinical"]["reviewer_username"]
        technical = summary["roles"]["technical"]["reviewer_username"]
        approved_by = f"clinical={clinical};technical={technical}"
        for member in ruleset["members"]:
            if member["lifecycle_status"] == "VALIDATED":
                self.rules.approve_rule_version(
                    int(member["rule_version_id"]), approved_by=approved_by,
                )
            elif member["lifecycle_status"] not in {"APPROVED", "SILENT", "ACTIVE"}:
                raise ValueError(f"قاعدهٔ {member['rule_code']} آمادهٔ فریز نیست")
        self.rules.activate_ruleset(
            int(ruleset["id"]), activated_by=actor, silent=True,
        )
        for key in (
            "last_report", "approval_clinical", "approval_technical",
            "selected_rollout_verification", "seal",
        ):
            self.activation.delete(key)
        self.activation.set_raw_mode("off")
        log_activity(
            "clinical_v2_package_freeze",
            f"Dual-reviewed and froze ruleset {ruleset_id}: {freeze_note}; "
            f"clinical={clinical}; technical={technical}; "
            f"package={package.package_hash}; cases={package.case_bundle_hash}",
            user_id=0,
            username=actor,
        )
        return self.rules.get_ruleset(int(ruleset_id))

    def approve_and_freeze(self, *args, **kwargs):
        raise ValueError(
            "مسیر تأیید تک‌نفره حذف شده است؛ بازبینی بالینی و فنی مستقل و سپس فریز لازم است"
        )

''',
)
# Enrich projection with the immutable manifest and latest review events.
replace_once(
    service,
    '''    def projection(self) -> dict:
        ruleset = self.rules.latest_ruleset(RULESET_CODE)
''',
    '''    def projection(self) -> dict:
        bundled = load_rule_package(
            _package_dir(),
            expected_version=PACKAGE_VERSION,
            expected_ruleset_code=RULESET_CODE,
            compiler=self.compiler,
        )
        expected_rules = [
            {
                "code": compiled.definition.rule_code,
                "title": compiled.definition.title,
                "phase": compiled.definition.phase.value,
            }
            for compiled in bundled.compiled_rules
        ]
        ruleset = self.rules.latest_ruleset(RULESET_CODE)
''',
)
replace_once(
    service,
    '''                "expected_version": PACKAGE_VERSION,
            }
        rules = []
''',
    '''                "expected_version": PACKAGE_VERSION,
                "expected_rules": expected_rules,
                "expected_rule_count": len(expected_rules),
                "review": None,
            }
        review = self.rules.rule_review_summary(int(ruleset["id"]))
        rules = []
''',
)
replace_once(
    service,
    '''                "lifecycle_status": member["lifecycle_status"],
            })
''',
    '''                "lifecycle_status": member["lifecycle_status"],
                "reviews": review["rules"].get(
                    raw["rule_code"], {"clinical": None, "technical": None}
                ),
            })
''',
)
replace_once(
    service,
    '''            "rules": rules,
            "upgrade_from": None,
            "expected_version": PACKAGE_VERSION,
        }
''',
    '''            "rules": rules,
            "upgrade_from": None,
            "expected_version": PACKAGE_VERSION,
            "expected_rules": expected_rules,
            "expected_rule_count": len(expected_rules),
            "review": review,
        }
''',
)

manager = SPECIALIST / "src/api/manager.py"
replace_once(
    manager,
    '''    projection["package"] = ClinicalRulePackageService().projection()
    projection["cohort"] = DemoCohortService().summary()
''',
    '''    projection["package"] = ClinicalRulePackageService().projection()
    projection["rule_review_permissions"] = {
        "clinical": has_permission(Permission.RULE_REVIEW_CLINICAL),
        "technical": has_permission(Permission.RULE_REVIEW_TECHNICAL),
        "activate": has_permission(Permission.RULE_ACTIVATE),
    }
    projection["cohort"] = DemoCohortService().summary()
''',
)
replace_once(
    manager,
    '''        "activate-global", "rollback", "reset-workflow",
    }:
''',
    '''        "activate-global", "rollback", "reset-workflow", "freeze-rules",
    }:
''',
)
replace_once(
    manager,
    '''    elif action == "approve" and request.form.get("role") == "technical":
        required = Permission.RULE_REVIEW_TECHNICAL
''',
    '''    elif action in {"approve", "review-rules"} and request.form.get("role") == "technical":
        required = Permission.RULE_REVIEW_TECHNICAL
    elif action == "review-rules":
        required = Permission.RULE_REVIEW_CLINICAL
''',
)
replace_block(
    manager,
    '''        elif action == "approve-rules":
''',
    '''        elif action == "compare":
''',
    '''        elif action == "review-rules":
            from src.services.clinical_engine.package_service import ClinicalRulePackageService
            package_service = ClinicalRulePackageService()
            package_projection = package_service.projection()
            if package_projection["state"] != "review":
                raise ActivationGateError("بستهٔ جاری در وضعیت بازبینی نیست")
            decisions = {
                rule["code"]: request.form.get(
                    f"decision__{rule['code']}", ""
                )
                for rule in package_projection["rules"]
            }
            role = request.form.get("role", "").strip().lower()
            summary = package_service.review_rules(
                request.form.get("ruleset_id", type=int),
                role=role,
                decisions=decisions,
                actor_username=actor,
                reviewer_display_name=(g.user["full_name"] or actor),
                note=note,
            )
            role_title = "بالینی" if role == "clinical" else "فنی"
            role_summary = summary["roles"][role]
            if role_summary["complete"]:
                flash(f"بازبینی {role_title} همهٔ قواعد ثبت شد.", "success")
            else:
                flash(
                    f"بازبینی {role_title} ثبت شد؛ "
                    f"{role_summary['changes_requested_count']} قاعده نیازمند اصلاح است.",
                    "warning",
                )
        elif action == "freeze-rules":
            from src.services.clinical_engine.package_service import ClinicalRulePackageService
            frozen = ClinicalRulePackageService().freeze_reviewed_package(
                request.form.get("ruleset_id", type=int),
                activated_by=actor,
                note=note,
            )
            flash(
                f"هر {len(frozen['members'])} قاعده با دو بازبینی مستقل فریز شد.",
                "success",
            )
        elif action == "compare":
''',
)

template = SPECIALIST / "src/templates/manager/clinical_engine.html"
replace_once(
    template,
    "{% for number, title in [(1,'آماده‌سازی قواعد'),(2,'بازبینی پزشک'),",
    "{% for number, title in [(1,'آماده‌سازی قواعد'),(2,'بازبینی دوگانه قواعد'),",
)
replace_once(
    template,
    '''        <h2 id="task-title">بستهٔ اولیهٔ قواعد را آماده کنید</h2>
        <p>برنامه دو قاعدهٔ ایمنی آزمایشی را از فایل‌های همراه خودش وارد و از نظر ساختار فنی بررسی می‌کند. در این مرحله هیچ پیشنهادی به بیمار نمایش داده نمی‌شود.</p>
''',
    '''        <h2 id="task-title">بستهٔ اولیهٔ قواعد را آماده کنید</h2>
        <p>برنامه {{ package.expected_rule_count|fa_num }} قاعدهٔ پیش‌نویس نسخهٔ جاری را از artifactهای immutable وارد و از نظر ساختار فنی بررسی می‌کند. در این مرحله هیچ پیشنهادی به بیمار نمایش داده نمی‌شود.</p>
''',
)
replace_block(
    template,
    '''        <ul class="engine-plain-list">
''',
    '''        <div class="alert-banner alert-warn">''',
    '''        <ul class="engine-plain-list">
            {% for expected in package.expected_rules %}
            <li><svg class="icon icon-sm"><use href="#i-check"></use></svg> {{ expected.title }} <code>{{ expected.code }}</code></li>
            {% endfor %}
        </ul>
''',
)
review_block = r'''{% elif package.state == 'review' %}
    {% set review = package.review %}
    <section class="card engine-review-card" aria-labelledby="task-title">
        <div class="engine-task-number">مرحلهٔ ۲ از ۷</div>
        <div class="engine-section-head"><div><span class="engine-section-icon"><svg class="icon"><use href="#i-stethoscope"></use></svg></span><div><h2 id="task-title">بازبینی مستقل بالینی و فنی</h2><p>هر قاعده باید توسط دو حساب کاربری مستقل، با تصمیم صریح و ثبت append-only بررسی شود. هیچ فرم تک‌نفره‌ای بسته را فریز نمی‌کند.</p></div></div></div>
        <div class="engine-result-summary">
            <span><b>{{ review.roles.technical.approved_count|fa_num }}/{{ review.roles.technical.total|fa_num }}</b> تأیید فنی</span>
            <span><b>{{ review.roles.clinical.approved_count|fa_num }}/{{ review.roles.clinical.total|fa_num }}</b> تأیید بالینی</span>
            <span><b>{{ 'آماده' if review.ready_to_freeze else 'مسدود' }}</b> فریز SILENT</span>
        </div>
        <div class="engine-rule-list">
        {% for rule in package.rules %}
            <article class="engine-rule-review">
                <div class="engine-rule-head"><div><span class="badge {{ 'badge-danger' if rule.phase in ['PREFLIGHT','SAFETY'] else 'badge-warn' }}">{{ rule.phase }}</span><code>{{ rule.code }}</code></div><h3>{{ rule.title }}</h3></div>
                <div class="engine-rule-grid">
                    <div><span>جمعیت توصیفی</span><p>{{ rule.population }}</p></div>
                    <div><span>چه داده‌ای لازم است؟</span><ul>{% for item in rule.required_inputs %}<li>{{ item }}</li>{% endfor %}</ul></div>
                </div>
                {{ condition_box('۱. بیمار چه زمانی وارد دامنهٔ قاعده می‌شود؟', rule.eligibility_mode, rule.eligibility_conditions) }}
                {{ condition_box('۲. قاعده دقیقاً چه زمانی فعال می‌شود؟', rule.trigger_mode, rule.trigger_conditions) }}
                <div class="engine-recommendation"><span>۳. پیشنهاد سیستم</span><p>{{ rule.recommendation }}</p></div>
                <div class="engine-automation-limit"><svg class="icon icon-sm"><use href="#i-shield"></use></svg><span>{{ rule.automation_limit }}</span></div>
                <details class="engine-evidence"><summary>محدوده، منبع و وضعیت شواهد</summary>{% if rule.out_of_scope %}<p><b>خارج از محدوده:</b> {{ rule.out_of_scope|join('، ') }}</p>{% endif %}<p><b>{{ rule.source_title }}</b></p><p>{{ rule.source_locator }}</p>{% if rule.source_url %}<p><a href="{{ rule.source_url }}" target="_blank" rel="noopener noreferrer">بازکردن منبع اصلی</a></p>{% endif %}<span class="badge badge-warn">بازبینی محلی: {{ rule.validation_status }}</span></details>
                <div class="engine-history-list">
                    {% for role, label in [('technical','فنی'),('clinical','بالینی')] %}
                    {% set event = rule.reviews[role] %}
                    <span>{{ label }}: {% if event %}<b>{{ 'تأیید' if event.decision == 'APPROVE' else 'نیازمند اصلاح' }}</b> · {{ event.reviewer_display_name }}{% else %}<b>ثبت نشده</b>{% endif %}</span>
                    {% endfor %}
                </div>
            </article>
        {% endfor %}
        </div>

        {% for role, role_title in [('technical','فنی'),('clinical','بالینی')] %}
        {% set role_state = review.roles[role] %}
        <section class="card engine-task-card engine-task-wide">
            <h3>فرم بازبینی {{ role_title }}</h3>
            {% if role_state.complete %}<div class="alert-banner alert-ok"><span>همهٔ قواعد توسط {{ role_state.reviewer_display_name }} تأیید شده‌اند. ارسال دوباره فقط یک رویداد اصلاحی append-only می‌سازد.</span></div>{% endif %}
            {% if engine.rule_review_permissions[role] %}
            <form method="post" action="{{ url_for('manager.clinical_engine_action', action='review-rules') }}" class="engine-review-form">
                <input type="hidden" name="ruleset_id" value="{{ package.ruleset.id }}">
                <input type="hidden" name="role" value="{{ role }}">
                <div class="engine-rule-list">
                {% for rule in package.rules %}
                    {% set event = rule.reviews[role] %}
                    <label class="engine-rule-attest"><span><b>{{ rule.code }}</b> · {{ rule.title }}</span><select name="decision__{{ rule.code }}" required><option value="">انتخاب تصمیم</option><option value="APPROVE"{% if event and event.decision == 'APPROVE' %} selected{% endif %}>تأیید برای ادامهٔ validation</option><option value="REQUEST_CHANGES"{% if event and event.decision == 'REQUEST_CHANGES' %} selected{% endif %}>نیازمند اصلاح artifact</option></select></label>
                {% endfor %}
                </div>
                <div class="engine-review-signoff">
                    <label><span>هویت احرازشدهٔ بازبین</span><input value="{{ g.user.full_name or g.user.username }} ({{ g.user.username }})" readonly></label>
                    <label><span>یادداشت بازبینی {{ role_title }}</span><textarea name="note" rows="3" required placeholder="موارد بررسی‌شده و علت تصمیم‌ها را ثبت کنید."></textarea></label>
                    <button class="btn btn-lg engine-primary-action" type="submit">ثبت append-only بازبینی {{ role_title }}</button>
                </div>
            </form>
            {% else %}<div class="alert-banner alert-warn"><span>حساب فعلی مجوز ثبت بازبینی {{ role_title }} را ندارد.</span></div>{% endif %}
        </section>
        {% endfor %}

        {% if review.ready_to_freeze %}
        <section class="card engine-task-card">
            <div class="engine-task-icon is-ok"><svg class="icon icon-lg"><use href="#i-check"></use></svg></div>
            <h3>دو بازبینی مستقل کامل است</h3>
            <p>فریز فقط content hashهای همین package و case bundle را به SILENT می‌برد؛ موتور برای بیمار واقعی روشن نمی‌شود.</p>
            {% if engine.rule_review_permissions.activate %}
            <form method="post" action="{{ url_for('manager.clinical_engine_action', action='freeze-rules') }}" class="engine-signoff-form">
                <input type="hidden" name="ruleset_id" value="{{ package.ruleset.id }}">
                <label><span>یادداشت فریز</span><textarea name="note" rows="3" required></textarea></label>
                <button class="btn btn-lg engine-primary-action" type="submit">فریز بستهٔ دوگانه‌بازبینی‌شده</button>
            </form>
            {% else %}<div class="alert-banner alert-warn"><span>برای فریز، مجوز مستقل فعال‌سازی لازم است.</span></div>{% endif %}
        </section>
        {% else %}
        <div class="engine-inline-problems" role="alert"><b>فریز مسدود است:</b><ul>{% for blocker in review.blockers %}<li>{{ blocker }}</li>{% endfor %}</ul></div>
        {% endif %}
        <small class="engine-safe-note"><svg class="icon icon-sm"><use href="#i-shield"></use></svg>یک حساب نمی‌تواند هر دو نقش را ثبت کند؛ نام نمایشی فرم قابل ویرایش نیست و هویت username در رویداد ذخیره می‌شود.</small>
    </section>

'''
replace_block(
    template,
    "{% elif package.state == 'review' %}",
    "{% elif not engine.report_ok %}",
    review_block,
)

# Replace the main manager UI journey with the governed dual-review path.
ui_test = SPECIALIST / "tests/test_clinical_engine_v2_manager_ui.py"
new_ui_test = r'''def test_guided_package_prepare_then_dual_review_and_freeze(manager_ui_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
    from src.services.auth_service import AuthService

    client = _manager_client(manager_ui_app)
    prepared = client.post(
        "/manager/clinical-engine/prepare-rules", follow_redirects=True,
    )
    html = prepared.get_data(as_text=True)
    assert prepared.status_code == 200
    assert "بازبینی مستقل بالینی و فنی" in html
    assert "سررسید ارزیابی HbA1c" in html
    assert "بازبینی فایده و خطر متفورمین" in html
    assert "یک حساب نمی‌تواند هر دو نقش" in html
    with manager_ui_app.app_context():
        assert ClinicalEngineFactRepository().get_mode() == "off"
        package = ClinicalEngineRulesRepository().latest_ruleset("general-outpatient")
        assert package["status"] == "DRAFT"
        ruleset_id = package["id"]
        rule_codes = [item["rule_code"] for item in package["members"]]
        assert len(rule_codes) == 6

    technical_data = {
        "ruleset_id": ruleset_id,
        "role": "technical",
        "note": "Schema, facts, units and task contracts reviewed.",
        **{f"decision__{code}": "APPROVE" for code in rule_codes},
    }
    technical = client.post(
        "/manager/clinical-engine/review-rules",
        data=technical_data,
        follow_redirects=True,
    )
    assert "بازبینی فنی همهٔ قواعد ثبت شد" in technical.get_data(as_text=True)

    same_actor = client.post(
        "/manager/clinical-engine/review-rules",
        data={
            **technical_data,
            "role": "clinical",
            "note": "unsafe same-account review",
        },
        follow_redirects=True,
    )
    assert "نمی‌تواند هر دو نقش" in same_actor.get_data(as_text=True)

    with manager_ui_app.app_context():
        assert AuthService().register_user(
            "clinical-reviewer", "safe-password", "manager", "پزشک بازبین"
        )
    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"username": "clinical-reviewer", "password": "safe-password"},
    )
    clinical_changes = {
        "ruleset_id": ruleset_id,
        "role": "clinical",
        "note": "One rule needs explicit clarification.",
        **{f"decision__{code}": "APPROVE" for code in rule_codes},
    }
    clinical_changes[f"decision__{rule_codes[-1]}"] = "REQUEST_CHANGES"
    changes = client.post(
        "/manager/clinical-engine/review-rules",
        data=clinical_changes,
        follow_redirects=True,
    )
    assert "1 قاعده نیازمند اصلاح" in changes.get_data(as_text=True)
    blocked = client.post(
        "/manager/clinical-engine/freeze-rules",
        data={"ruleset_id": ruleset_id, "note": "must fail"},
        follow_redirects=True,
    )
    assert "دو بازبینی مستقل و کامل ندارد" in blocked.get_data(as_text=True)

    clinical_approved = dict(clinical_changes)
    clinical_approved["note"] = "Eligibility, exclusions and source locators reviewed."
    clinical_approved[f"decision__{rule_codes[-1]}"] = "APPROVE"
    approved = client.post(
        "/manager/clinical-engine/review-rules",
        data=clinical_approved,
        follow_redirects=True,
    )
    assert "دو بازبینی مستقل کامل است" in approved.get_data(as_text=True)

    client.get("/auth/logout")
    client.post("/auth/login", data={"username": "admin", "password": "admin"})
    frozen_response = client.post(
        "/manager/clinical-engine/freeze-rules",
        data={"ruleset_id": ruleset_id, "note": "dual review complete"},
        follow_redirects=True,
    )
    html = frozen_response.get_data(as_text=True)
    assert "هر 6 قاعده با دو بازبینی مستقل فریز شد" in html
    assert "۱۰ پروندهٔ نمونهٔ کامل" in html
    with manager_ui_app.app_context():
        repo = ClinicalEngineRulesRepository()
        package = repo.latest_ruleset("general-outpatient")
        assert package["status"] == "SILENT"
        summary = repo.rule_review_summary(ruleset_id)
        assert summary["ready_to_freeze"] is False  # no longer DRAFT after freeze
        assert summary["roles"]["clinical"]["reviewer_username"] == "clinical-reviewer"
        assert summary["roles"]["technical"]["reviewer_username"] == "admin"
        assert ClinicalEngineFactRepository().get_mode() == "off"

    validation_run = client.post(
        "/manager/clinical-engine/validation/run", follow_redirects=True,
    )
    assert "اعتبارسنجی با وضعیت PASS" in validation_run.get_data(as_text=True)
    with manager_ui_app.app_context():
        from src.services.clinical_engine.validation_service import ClinicalValidationService
        validation_report = ClinicalValidationService().dashboard()["report"]
    client.post(
        "/manager/clinical-engine/validation/attest",
        data={"role": "clinical", "reviewer": "doctor-a",
              "note": "Clinical validation reviewed.",
              "report_hash": validation_report["report_hash"],
              "attestation": "yes"},
    )
    client.post(
        "/manager/clinical-engine/validation/attest",
        data={"role": "technical", "reviewer": "engineer-b",
              "note": "Technical validation reviewed.",
              "report_hash": validation_report["report_hash"],
              "attestation": "yes"},
    )

    cohort = client.post(
        "/manager/clinical-engine/prepare-demo-cohort", follow_redirects=True,
    )
    assert "۱۰ پروندهٔ طولی آماده شد" in cohort.get_data(as_text=True)
    compared = client.post(
        "/manager/clinical-engine/compare", follow_redirects=True,
    )
    html = compared.get_data(as_text=True)
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html
    with manager_ui_app.app_context():
        state = ClinicalEngineActivationRepository()
        report = state.get_json("last_report")
        rows = {row["national_id"]: row for row in report["patients"]}
        assert "T2-REDFLAG-BP" in rows["TEST0008"]["v2_rule_codes"]
        assert "T2-SAFE-MET-STOP" in rows["TEST0010"]["v2_rule_codes"]
'''
replace_block(
    ui_test,
    "def test_guided_package_prepare_then_clinical_review_and_freeze",
    "def test_workflow_reset_requires_confirmation_preserves_audit_and_can_restart",
    new_ui_test + "\n\n",
)

# Update end-to-end package freeze to use two authenticated review identities.
e2e = SPECIALIST / "tests/test_end_to_end_loops.py"
replace_block(
    e2e,
    "    frozen = packages.approve_and_freeze(\n",
    "    assert install_sealed_rollout() == int(frozen[\"id\"])\n",
    '''    decisions = {
        member["rule_code"]: "APPROVE" for member in package["members"]
    }
    packages.review_rules(
        int(package["id"]), role="technical", decisions=decisions,
        actor_username="pytest-engineer", reviewer_display_name="Pytest Engineer",
        note="technical end-to-end review",
    )
    packages.review_rules(
        int(package["id"]), role="clinical", decisions=decisions,
        actor_username="pytest-physician", reviewer_display_name="Pytest Physician",
        note="clinical end-to-end review",
    )
    frozen = packages.freeze_reviewed_package(
        int(package["id"]), activated_by="pytest-release-manager",
        note="end-to-end safety contract",
    )
''',
)

contract_test = SPECIALIST / "tests/test_clinical_rule_package_contract.py"
replace_block(
    contract_test,
    "    service = ClinicalRulePackageService(rules=FakeRules())\n",
    "        )\n",
    '''    service = ClinicalRulePackageService(rules=FakeRules())
    with pytest.raises(ValueError, match="immutable"):
        service.review_rules(
            1,
            role="clinical",
            decisions={code: "APPROVE" for code in package.rule_codes},
            actor_username="physician-a",
            reviewer_display_name="Physician A",
            note="reviewed",
        )
''',
)

write(
    SPECIALIST / "tests/test_clinical_rule_review_governance_a13.py",
    r'''"""A13 dual-control and append-only rule review contract."""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def review_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "review-a13.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "review-a13",
    })
    context = app.app_context()
    context.push()
    core.get_db()
    yield app
    context.pop()
    core._initialized = False


def _prepared():
    from src.services.clinical_engine.package_service import ClinicalRulePackageService

    service = ClinicalRulePackageService()
    ruleset = service.prepare(actor="package-preparer")
    decisions = {member["rule_code"]: "APPROVE" for member in ruleset["members"]}
    return service, ruleset, decisions


def test_dual_review_is_append_only_idempotent_and_separated(review_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository

    service, ruleset, decisions = _prepared()
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="facts, units, DSL and tasks reviewed",
    )
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="facts, units, DSL and tasks reviewed",
    )
    db = get_db()
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_rule_review_events"
    ).fetchone()["count"] == len(decisions)

    with pytest.raises(ValueError, match="هر دو نقش"):
        service.review_rules(
            ruleset["id"], role="clinical", decisions=decisions,
            actor_username="engineer-a", reviewer_display_name="Engineer A",
            note="same actor must fail",
        )

    changes = dict(decisions)
    changes[next(iter(changes))] = "REQUEST_CHANGES"
    service.review_rules(
        ruleset["id"], role="clinical", decisions=changes,
        actor_username="physician-b", reviewer_display_name="Physician B",
        note="one rule needs clarification",
    )
    summary = ClinicalEngineRulesRepository().rule_review_summary(ruleset["id"])
    assert summary["ready_to_freeze"] is False
    assert summary["roles"]["clinical"]["changes_requested_count"] == 1
    with pytest.raises(ValueError, match="دو بازبینی مستقل"):
        service.freeze_reviewed_package(
            ruleset["id"], activated_by="release-manager", note="blocked",
        )

    service.review_rules(
        ruleset["id"], role="clinical", decisions=decisions,
        actor_username="physician-b", reviewer_display_name="Physician B",
        note="clarification resolved and all rules reviewed",
    )
    summary = ClinicalEngineRulesRepository().rule_review_summary(ruleset["id"])
    assert summary["ready_to_freeze"] is True
    assert summary["distinct_reviewers"] is True
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_rule_review_events"
    ).fetchone()["count"] == len(decisions) * 3

    frozen = service.freeze_reviewed_package(
        ruleset["id"], activated_by="release-manager", note="dual control complete",
    )
    assert frozen["status"] == "SILENT"
    with pytest.raises(ValueError, match="DRAFT"):
        service.review_rules(
            ruleset["id"], role="clinical", decisions=decisions,
            actor_username="physician-b", reviewer_display_name="Physician B",
            note="late mutation must fail",
        )


def test_review_storage_rejects_mutation_deletion_and_hash_mismatch(review_app):
    from src.adapters.sqlite.core import get_db

    service, ruleset, decisions = _prepared()
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="technical review",
    )
    db = get_db()
    event = db.execute(
        "SELECT * FROM clinical_rule_review_events ORDER BY id LIMIT 1"
    ).fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE clinical_rule_review_events SET note='changed' WHERE id=?",
            (event["id"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM clinical_rule_review_events WHERE id=?", (event["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="hash mismatch"):
        db.execute(
            """INSERT INTO clinical_rule_review_events
               (ruleset_id, rule_version_id, role, decision,
                ruleset_content_hash, rule_content_hash, package_hash,
                case_bundle_hash, reviewer_username, reviewer_display_name,
                note, idempotency_key, created_at)
               VALUES (?, ?, 'CLINICAL', 'APPROVE', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ruleset["id"], event["rule_version_id"], "bad-ruleset-hash",
                event["rule_content_hash"], event["package_hash"],
                event["case_bundle_hash"], "physician-b", "Physician B",
                "bad identity", "bad-idempotency", "2026-07-27 12:00:00",
            ),
        )


def test_legacy_single_reviewer_freeze_is_retired(review_app):
    service, ruleset, decisions = _prepared()
    with pytest.raises(ValueError, match="تک‌نفره حذف شده"):
        service.approve_and_freeze(
            ruleset["id"], reviewer="one-person",
            attested_codes=list(decisions), note="unsafe",
        )
''',
)

write(
    SPECIALIST / "docs/clinical_rule_review_governance_a13.md",
    r'''# A13 — حاکمیت بازبینی دوگانهٔ قواعد بالینی

## مشکل بسته‌شده

مسیر قبلی اجازه می‌داد یک فرم بالینی همهٔ Ruleها را تیک بزند و همان لحظه ruleset را به `SILENT` ببرد. A13 این مسیر تک‌نفره را حذف می‌کند.

## قرارداد جدید

```text
immutable package + case bundle
→ technical decisions for every rule
→ clinical decisions for every rule
→ distinct authenticated usernames
→ exact latest APPROVE for both roles
→ separate RULE_ACTIVATE freeze
→ SILENT only
```

هر تصمیم در `clinical_rule_review_events` ثبت می‌شود و به این شناسه‌ها متصل است:

- ruleset و `ruleset_content_hash`
- rule version و `rule_content_hash`
- `package_hash`
- `case_bundle_hash`
- نقش بازبین، تصمیم، username احرازشده، نام نمایشی، یادداشت و زمان
- رویداد قبلی همان Rule/Role در صورت اصلاح تصمیم

## گاردها

- UPDATE و DELETE رویدادهای بازبینی در SQLite ممنوع است.
- review فقط روی ruleset با وضعیت `DRAFT` ثبت می‌شود.
- Rule باید عضو همان ruleset باشد و hashها باید دقیقاً منطبق باشند.
- یک username نمی‌تواند در یک ruleset هر دو نقش بالینی و فنی را ثبت کند.
- هر Rule باید در هر نقش تصمیم صریح `APPROVE` یا `REQUEST_CHANGES` داشته باشد.
- `REQUEST_CHANGES` فریز را مسدود می‌کند؛ رفع آن یک رویداد جدید append-only می‌سازد.
- فریز به مجوز مستقل `RULE_ACTIVATE` نیاز دارد و موتور همچنان خاموش می‌ماند.
- approval تک‌نفرهٔ قدیمی عمداً fail-closed شده است.

## مرز انتشار

A13 هیچ Rule را از `NOT_REVIEWED` به تأیید بالینی واقعی تبدیل نمی‌کند. این مرحله فقط زیرساخت قابل‌ممیزی برای ثبت آن تصمیم‌ها را می‌سازد.
''',
)

print("A13 dual rule-review governance finalized")

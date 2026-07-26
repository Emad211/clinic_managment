# A6 — اقتصاد کمپین با lineage صریح

## اصل اندازه‌گیری

هیچ فاکتور یا وصولی فقط به دلیل رخ‌دادن در بازهٔ زمانی پس از پیامک به کمپین منتسب نمی‌شود. زنجیرهٔ معتبر به شکل زیر است:

```text
Campaign
→ frozen audience
→ governed message
→ provider acceptance / actual delivery
→ explicit patient response
→ explicit CareJourney attribution
→ completed Encounter
→ attributed accounting invoice
→ A4 financial observation
→ direct cost / net contribution / ROI
```

## Audience

Audience هر کمپین فقط یک بار با seed قطعی ثابت می‌شود. اعضای treated، control و excluded همراه با consent event، شماره canonical و وضعیت accounting scope ذخیره می‌شوند. snapshotهای legacy فقط برای تاریخچه قابل مشاهده‌اند و قابل اجرا یا استفاده برای ROI نیستند.

## پاسخ بیمار

پاسخ مثبت نیازمند شاهد مستقیم است. عضوی از گروه control یا excluded نمی‌تواند پاسخ مثبت قابل attribution بسازد. اصلاح پاسخ، attribution قدیمی را برای ROI stale می‌کند تا اپراتور آن را لغو یا اصلاح کند.

## Journey attribution

اتصال پاسخ مثبت به Journey فقط با انتخاب صریح هنگام شروع ویزیت یا اقدام اصلاحی مجاز انجام می‌شود. یک پاسخ نمی‌تواند هم‌زمان به چند Journey فعال منتسب شود. تاریخچهٔ revoke و re-attribution append-only است.

## هزینه و کیف پول

- هزینه پیامک با evidence type مشخص ثبت می‌شود.
- نرخ تنظیم‌شدهٔ هر بخش فقط `ESTIMATED_CONFIGURED_RATE` است و هزینه واقعی provider محسوب نمی‌شود.
- اعتبار کیف پول فقط پس از پذیرش قطعی پیام ایجاد می‌شود.
- timeout مبهم، obligation با وضعیت `GRANT_REVIEW_REQUIRED` می‌سازد و اعتبار خودکار نمی‌دهد.
- شکست قطعی پس از grant در صورت نبود مصرف بعدی به‌صورت خودکار جبران می‌شود؛ وجود debit بعدی review انسانی می‌خواهد.

## انتشار ROI

ROI فقط در وضعیت `READY` نمایش داده می‌شود. موارد زیر آن را مسدود می‌کنند:

- Audience ثابت نشده یا legacy/untrusted؛
- delivery در جریان؛
- هزینه مستقیم ناقص؛
- Journey attribution فاقد financial observation؛
- attribution متصل به پاسخ superseded؛
- wallet compensation review باز؛
- نبود attribution صریح.

عدد A6 ادعای اثر علّی ندارد. گروه control به‌تنهایی برای استنتاج causal کافی نیست و تحلیل incrementality قرارداد جداگانه می‌خواهد.

## مرز حسابداری

A6 هیچ schema یا داده‌ای در `webapp` تغییر نمی‌دهد. وضعیت فاکتور و وصول فقط از snapshotهای read-only و append-only مرحله A4 مصرف می‌شود.

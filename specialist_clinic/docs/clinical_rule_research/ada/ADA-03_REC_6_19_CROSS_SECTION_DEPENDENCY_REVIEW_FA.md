# ADA-03 — مرور وابستگی‌های بین‌بخشی Recommendation 6.19

**نسخه:** 0.5  
**تاریخ:** 2026-07-30  
**Rule Candidate:** `0`  
**Accepted Rule:** `0`  
**Licensing:** `HOLD`

## نتیجهٔ اصلی

Recommendation 6.19 فقط یک trigger برای بازنگری طرح درمان ایجاد می‌کند. نوع اقدام نمی‌تواند از Section 6 به‌تنهایی تعیین شود.

بخش‌های 9، 10، 11 و 13 هم‌زمان الزام می‌کنند که:

- داروهای دارای ریسک مستقیم هیپوگلیسمی از سایر داروها تفکیک شوند؛
- indication مستقل قلبی، کلیوی و وزنی هر دارو ثبت شود؛
- CKD stage و kidney clearance لحاظ شود؛
- در سالمندان، cognition، function، nutrition، caregiver support و treatment burden بررسی شوند؛
- deintensification، cessation، switch و simplification یک intervention واحد محسوب نشوند؛
- منافع SGLT2 inhibitors و GLP-1 RAs در بیماران واجد شرایط صرفاً به دلیل A1C یا یک رویداد هیپوگلیسمی حذف نشوند.

## تعارض مرکزی

ADA در همان مجموعهٔ 2026 دو جهت هم‌زمان دارد:

1. کاهش یا جایگزینی داروهای ایجادکنندهٔ هیپوگلیسمی در فرد پرخطر؛
2. حفظ یا افزودن درمان‌های دارای منفعت قلبی–کلیوی، مستقل از نیاز به کاهش A1C.

این دو توصیه متعارض نیستند، اما فقط وقتی قابل جمع‌اند که موتور بداند:

- کدام دارو محتمل‌ترین عامل رویداد است؛
- دارو برای چه indicationهایی مصرف می‌شود؛
- آیا دارو منفعت مستقل قلبی/کلیوی دارد؛
- آیا جایگزین کم‌خطر مناسب وجود دارد؛
- وضعیت CKD، HF، ASCVD، وزن، تغذیه، cognition و function چیست.

## وابستگی‌های ثبت‌شده

چهارده وابستگی از Recommendations و بخش‌های زیر در Workbook ثبت شده‌اند:

- 6.3c، 6.6، 6.7 و 6.19؛
- Section 7 technology context؛
- 9.10، 9.11، 9.16 و 9.17؛
- 10.40a–c؛
- 11.11a–b؛
- 13.13 و 13.14a–d.

## تعارض event و pattern

یک رخداد تأییدشدهٔ Level 2/3 با یک الگوی طولی CGM یکسان نیست:

- event به زمان، منبع، glucose در صورت وجود و external assistance نیاز دارد؛
- CGM pattern به بازهٔ کافی، data sufficiency، TBR و اعتبار دستگاه نیاز دارد.

هیچ‌کدام نباید از دیگری استنباط شود.

## نتیجه برای formalization

منطق‌های زیر ممنوع‌اند:

- `hypoglycemia_event → reduce_all_diabetes_medications`
- `old_age → deintensify`
- `low_eGFR → stop_all_agents`
- `A1C_at_goal → remove_cardiorenal_agent`
- `CGM_low → assume_level_3_event`
- `one_event → infer_persistent_TBR`

تنها مفهوم باقی‌مانده:

> رخداد تأییدشده می‌تواند یک کار مرور پزشک ایجاد کند؛ نوع اقدام دارویی باید پس از ارزیابی class، indication، comorbidity، goals و preferences تصمیم‌گیری شود.

این مفهوم هنوز Rule Candidate نیست.

## منابع رسمی

- ADA Section 6: https://diabetesjournals.org/care/article/49/Supplement_1/S132/163927/6-Glycemic-Goals-Hypoglycemia-and-Hyperglycemic
- ADA Section 7: https://diabetesjournals.org/care/article/49/Supplement_1/S150/163922/7-Diabetes-Technology-Standards-of-Care-in
- ADA Section 9: https://diabetesjournals.org/care/article/49/Supplement_1/S183/163934/9-Pharmacologic-Approaches-to-Glycemic-Treatment
- ADA Section 10: https://diabetesjournals.org/care/article/49/Supplement_1/S216/163933/10-Cardiovascular-Disease-and-Risk-Management
- ADA Section 11: https://diabetesjournals.org/care/article/49/Supplement_1/S246/163914/11-Chronic-Kidney-Disease-and-Risk-Management
- ADA Section 13: https://diabetesjournals.org/care/article/49/Supplement_1/S277/163921/13-Older-Adults-Standards-of-Care-in-Diabetes-2026

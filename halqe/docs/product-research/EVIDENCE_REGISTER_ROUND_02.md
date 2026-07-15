# الحاقیهٔ رجیستر شواهد — دور دوم

**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**موضوع:** Care Loop، داشبورد بیمار، caregiver، عملیات پاسخ و حاکمیت موتور پیشنهاد  
**قاعده:** قابلیت vendor با اثربخشی مستقل برابر نیست. یافتهٔ مقاله با requirement قطعی محصول نیز برابر نیست؛ تبدیل شواهد به قابلیت نیازمند review، prototype و pilot است.

---

## ۱. شواهد مستقیم از کد فعلی Halqe

| موضوع | شاهد در مخزن | برداشت محصولی |
|---|---|---|
| Follow-up فعلی | `halqe/clinical/models.py`، مدل `FollowupTask` | موعد، متن، status، assigned_to متنی و call log دارد؛ owner identity، team queue، SLA، attempt history، escalation، evidence و closure outcome ندارد. |
| وضعیت follow-up | `open | done | dismissed` | برای worklist اولیه کافی است، برای Care Loop کامل نیست. |
| suggestion state | `SuggestionLog` و `SuggestionEvent` | pending/accepted/dismissed و eventهای accepted/dismissed/fired موجودند؛ conversion به plan/task و outcome downstream مدل نشده است. |
| rule metadata | `ClinicalRule` | trigger، recommendation، monitoring، contraindication، evidence_level و source_ref دارد؛ version/release/expiry/approval/shadow metrics هنوز contract کامل نیست. |
| دادهٔ canonical | مدل `Observation` | vital و lab در مسیر read کانونیک جمع شده و verified gate دارد؛ foundation مناسب برای engine است. |
| patient public card | `clinical/api/patient_card.py` | token عمومی، read-only، minimum necessary و LAN-only؛ نباید به پرتال کامل گسترش داده شود. |
| self-report | `clinical/api/self_report.py` | token یک‌بارمصرف، فقط FBS و BP، با `verified=FALSE`؛ حساب و dashboard طولی بیمار نیست. |
| بیمار/همراه | مدل رسمی patient account یا caregiver proxy در سطح پرتال وجود ندارد | authenticated patient portal، RelatedPerson-like relation، consent و scope باید bounded context مستقل باشند. |

---

## ۲. عملیات مراقبت پیوسته و human support

| منبع | نوع | یافتهٔ مرتبط | نتیجهٔ طراحی |
|---|---|---|---|
| [Kilfoy et al., 2024](https://doi.org/10.1111/jocn.17226) | review of nurse-led remote digital support | پاسخ به دادهٔ ورودی، virtual contact، education و نقش پرستار از اجزای تکرارشونده بودند. | جمع‌آوری داده بدون queue، owner و پاسخ انسانی کافی نیست. |
| [Granath et al., 2025](https://doi.org/10.1111/scs.70166) | qualitative remote-monitoring study | RPM رابطه‌ای انسانی و اخلاقی است، نه صرفاً انتقال عدد. | care team identity و response expectation باید در UX دیده شوند. |
| [Mikkonen et al., 2022](https://doi.org/10.1111/jocn.16448) | systematic review | مداخلات موفق‌تر فناوری را با تعامل، coaching و education ترکیب کردند. | service model و software باید هم‌زمان طراحی شوند. |
| [Buck et al., 2020](https://doi.org/10.1002/nur.22073) | theory-based analysis | self-care شامل maintenance، monitoring و management است؛ ابزارها همه را یکجا پوشش نمی‌دهند. | Halqe باید از logging به decision/action support برسد. |
| [Fraser-Hurt et al., 2021](https://doi.org/10.1111/1753-6405.13113) | care-cascade evidence | tracking، lists/exception reports، outreach، task shifting و adherence support مهم‌اند. | population workbench و exception queue بخش هسته‌ای محصول‌اند. |
| [Rodriguez et al., 2019](https://doi.org/10.1111/1468-0009.12400) | implementation study | adoption فناوری بدون training، workflow redesign و مشارکت بیمار outcome را تضمین نکرد. | rollout باید implementation package و capacity model داشته باشد. |

---

## ۳. داشبورد بیمار، سواد سلامت و caregiver

| منبع | نوع | یافته | قاعدهٔ UX |
|---|---|---|---|
| [Norouzi Aval et al., 2025](https://doi.org/10.1002/hsr2.70520) | systematic review of portal features | دارو، نتیجه، نوبت، پیام، care plan/goal، آموزش، caregiver و privacy از featureهای پرتکرارند. | پرتال باید چندسطحی باشد، ولی صفحهٔ اول feature dump نباشد. |
| [Son et al., 2021](https://doi.org/10.1111/jnu.12633) | patient-portal adoption model | self-efficacy، privacy، usefulness، ease، literacy و سن روی استفاده اثر دارند. | onboarding، recovery، navigation و اعتماد قبل از هوشمندی پیچیده‌اند. |
| [Alcántara-Porcuna et al., 2026](https://doi.org/10.1111/nhs.70348) | qualitative synthesis | empowerment و communication در کنار burden، هزینه، مشکلات فنی و overreliance دیده شدند. | contextual insight بهتر از tracking دائمی و پرسر‌وصدا است. |
| [Chen et al., 2025](https://doi.org/10.1002/nop2.70356) | older adult/caregiver HF study | monitoring، communication و education در چند کانال و با محدودیت منابع انسانی همراه‌اند. | caregiver و fallback تلفنی/غیردیجیتال باید از ابتدا طراحی شوند. |
| [Suwanno et al., 2023](https://doi.org/10.1111/ijn.13208) | hypertension self-care evidence | سالمند و آموزش پایین به زبان ساده، تصویر، مثال و reminder متناسب نیاز دارند. | ساده‌سازی محتوا requirement است، نه polish. |
| [Yan et al., 2024](https://doi.org/10.1111/nhs.70006) | mental-workload review | terminology، navigation، feedback خطا، visibility و help بار شناختی را تغییر می‌دهند. | usability باید با task completion و workload تست شود. |
| [Utong et al., 2026](https://doi.org/10.1002/appl.70095) | digital-health usability | multilingual، low-data، font/button/symbol و instruction واضح مهم‌اند. | فارسی/RTL، low-data و accessibility مزیت بومی واقعی‌اند. |

---

## ۴. CDS، alert burden و حاکمیت علمی

| منبع | نوع | یافته | قاعدهٔ موتور |
|---|---|---|---|
| [Gholamzadeh et al., 2023](https://doi.org/10.1155/2023/8550905) | systematic review؛ knowledge-based CDSS | patient-specific recommendation، EHR integration و alerts رایج‌اند؛ framework استاندارد لازم است. | rule artifact versioned و machine-testable لازم است. |
| [Ronan et al., 2022](https://doi.org/10.1002/jhm.12825) | systematic review/meta-analysis | اثر کلی بر رفتار پزشک کوچک/نامنظم بود و context اهمیت داشت. | fire rate معیار موفقیت نیست؛ action و outcome مهم‌اند. |
| [Jia et al., 2018](https://doi.org/10.1111/jep.12968) | overview of reviews | اثر process-of-care منظم‌تر از patient outcome بود. | claim outcome قبل از pilot ممنوع؛ process telemetry لازم است. |
| [Aminzade et al., 2026](https://doi.org/10.1111/jgs.70379) | population-level Iran study | alertهای نرم و غیرinterruptive با کاهش prescribing نامناسب همراه بودند. | non-interruptive inbox باید default باشد؛ popup منبع کمیاب است. |
| [Mehraeen et al., 2025](https://doi.org/10.1049/htl2.70017) | systematic review of AI challenges | reliability، adoption، privacy، workflow interruption، bias و transparency مانع‌اند. | governance، validation و workflow fit از model accuracy جدا سنجیده شوند. |
| [Kang et al., 2026](https://doi.org/10.1002/dad2.70236) | hybrid AI framework | retrieval با citation، rules/context و feedback همراه با clinician oversight پیشنهاد شد. | موتور hybrid و human-in-the-loop؛ LLM منبع تصمیم نیست. |
| [Evans et al., 2023](https://doi.org/10.1111/bjh.19158) | data-driven/CDSS review | اثرها متغیر و مشکلات alert fatigue و fit شناخته‌شده‌اند. | alert tier، suppression، dedup و monitoring لازم‌اند. |

---

## ۵. استانداردها و حاکمیت رسمی

| مرجع | نکته | استفادهٔ پیشنهادی |
|---|---|---|
| [HL7 FHIR CarePlan](https://hl7.org/fhir/careplan.html) | plan بیمار، participant/custodian، conditions، goals و activities | alignment مفهومی CarePlan داخلی |
| [HL7 FHIR Goal](https://hl7.org/fhir/goal.html) | lifecycle، priority و target مبتنی بر Observation | مدل Goal و outcome evidence |
| [HL7 FHIR Task](https://hl7.org/fhir/task.html) | owner، queue، requested/execution period، input/output و status history | CareTask و staff inbox |
| [HL7 FHIR CommunicationRequest](https://hl7.org/fhir/communicationrequest.html) | درخواست پیام از رخداد واقعی communication جدا است | delivery/read/reply model |
| [HL7 FHIR Consent](https://hl7.org/fhir/consent.html) | اجازه/منع برای purpose و period | patient/caregiver consent lifecycle |
| [HL7 FHIR RelatedPerson](https://hl7.org/fhir/relatedperson.html) | caregiver/family/guardian مرتبط با بیمار | proxy access مستقل |
| [HL7 CQL](https://cql.hl7.org/) | زبان و representation کانونیک برای دانش محاسبه‌پذیر | الهام برای DSL قابل‌تبدیل و versioned |
| [WHO SMART Guidelines](https://www.who.int/teams/digital-health-and-innovation/smart-guidelines) | machine-readable، testable، standards-based و localization | guideline pack و digital adaptation kit |
| [NICE Evidence Standards Framework](https://www.nice.org.uk/corporate/ecd7) | evidence متناسب با risk و فناوری adaptive/AI | evidence plan و release gate |
| [FDA CDS Guidance, January 2026](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software) | مرزبندی CDS و patient/caregiver software | threat/regulatory assessment محافظه‌کارانه؛ نه ادعای انطباق |

---

## ۶. قابلیت‌های رسمی رقبا؛ فقط capability mapping

| vendor | capability قابل مشاهده | درس |
|---|---|---|
| [MyChart](https://www.mychart.org/) | appointment، medications، results، bills، messages، family access | account/proxy/access یک baseline بالغ است. |
| [Omada](https://www.omadahealth.com/) | multi-condition program، coach، device، plan و education | software بدون human program تمایز کافی ندارد. |
| [Dario](https://www.dariohealth.com/) | one experience، coaching، connected devices و چندبیماری | تجربهٔ تلفیقی cardiometabolic expectation بازار است. |
| [Welldoc](https://www.welldoc.com/) | personalized cardiometabolic insights | insight باید context-aware و قابل‌اقدام باشد. |
| [Cadence](https://www.cadence.care/) | monitoring، care team، triage و workflow physician | operating model و response capacity هستهٔ RPM است. |
| [Huma](https://www.huma.com/) | configurable RPM apps، dashboards و enterprise infrastructure | multi-tenant configuration باید محصول مستقل باشد. |

**محدودیت:** outcome claimهای vendor در این جدول ثبت نشده‌اند و نیازمند منبع مستقل‌اند.

---

## ۷. فرضیه‌های قابل‌آزمایش حاصل از شواهد

| فرضیه | آزمایش |
|---|---|
| نمایش یک اقدام اصلی، task completion را نسبت به dashboard نمودارمحور افزایش می‌دهد. | prototype usability + controlled pilot |
| نمایش زمان مورد انتظار پاسخ، تماس تکراری و اضطراب را کم می‌کند. | A/B محدود + support-call rate |
| inbox non-interruptive با tiering، نسبت action/alert را بهتر می‌کند. | shadow + stepped rollout |
| caregiver رسمی completion را در سالمندان بهتر می‌کند. | cohort pilot با consent |
| closure evidence نرخ «done کاذب» را کاهش می‌دهد. | dual-run با worklist فعلی |
| rule explanation و source/version، اعتماد و review quality را بهتر می‌کند. | clinician usability study |
| human coaching فقط برای cohort منتخب، unit economics بهتری از coaching همگانی دارد. | service-design pilot |

هیچ‌کدام هنوز نتیجهٔ اثبات‌شدهٔ Halqe نیستند.

---

## ۸. شکاف‌های پژوهشی بعدی

- appraisal خط‌به‌خط guidelineهای دیابت، HTN، ASCVD و HF؛
- مدل ظرفیت و هزینهٔ nurse/care navigator؛
- patient authentication در بافت ایران؛
- caregiver و consent در وضعیت‌های اختلاف یا ناتوانی؛
- multilingual Persian/plain-language content testing؛
- pilot design و sample-size planning؛
- reimbursement و قرارداد remote care؛
- تحلیل demoمحور رقبا با taskهای ثابت؛
- interview با بیمار، caregiver، پزشک، پرستار و مدیر سه نوع مرکز.

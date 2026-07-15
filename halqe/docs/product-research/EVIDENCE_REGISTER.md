# رجیستر شواهد پژوهش محصول حلقه

**آخرین به‌روزرسانی:** ۲۰۲۶-۰۷-۱۵  
**کاربرد:** ردیابی شواهد، نه جایگزینی appraisal کامل مقاله یا sign-off بالینی  
**قاعده:** قابلیت vendor با اثربخشی مستقل برابر نیست؛ guideline با implementation rule برابر نیست.

---

## ۱. شواهد وضعیت واقعی کد

| موضوع | شاهد در مخزن | نتیجه |
|---|---|---|
| کارت عمومی بیمار | `halqe/web/src/app/card/[token]/page.tsx:3-18` | عمومی، بدون JWT و read-only؛ پرتال کامل نیست. |
| محتوای کارت | همان فایل `:206-284` | ویتال منتخب، یادآور و نوبت بعدی. |
| self-report | `halqe/clinical/api/self_report.py:3-29` | token یک‌بارمصرف؛ داده `verified=FALSE` و خارج از موتور تا review پزشک. |
| self-report whitelist | همان فایل `:78-89` | فقط FBS، فشار سیستولیک و دیاستولیک. |
| cockpit کارکنان | `halqe/web/src/app/patients/[uuid]/page.tsx:23-46` و `:198-203` | overview، trends، meds، record و اجزای ایمنی/پیشنهاد/ویزیت. |
| MVP فعلی | `halqe/docs/ROADMAP_MVP.md:11-25` | پایلوت ایمن care-loop؛ suggestion-only و verified-gate. |
| محدودیت portal در MVP قدیمی | `ROADMAP_MVP.md:27-36` | public PWA و برخی قابلیت‌ها عمداً defer شده‌اند. |
| حسابداری runtime | `halqe/docs/UNIFIED_MIGRATION_AUDIT_REPORTING_UPDATE.md:8-63` | عملیات، مدیریت، گزارش، payroll، audit، ETL، backup، dual-run و release gate. |
| gateهای واقعی حسابداری | همان فایل `:84-112` | rehearsal، restore، dual-run و sign-off واقعی هنوز external gate هستند. |
| مرز معماری | `halqe/README.md:37-43` | clinical فقط از accounting read port می‌خواند؛ schema-first و Tehran time. |

---

## ۲. دیابت و مراقبت دیجیتال

| منبع | نوع/حجم | یافتهٔ مرتبط با محصول | محدودیت/احتیاط |
|---|---|---|---|
| [Versluis et al., 2025](https://doi.org/10.1111/dme.70002) | systematic review + meta-analysis؛ 43 trial، 9328 participant | DSME/DSMS موبایلی اثر متوسطی بر HbA1c گزارش کرد؛ support و education مهم‌اند. | اثر بزرگ یا یکنواخت نیست؛ patient-reported outcomes محدود بودند. |
| [Kuo et al., 2018](https://doi.org/10.1111/jan.13574) | systematic review + meta-analysis؛ 21 RCT | self-management مبتنی بر empowerment می‌تواند HbA1c، فعالیت، وزن و کیفیت زندگی را بهبود دهد. | مداخلات و بیماری‌ها heterogeneous هستند. |
| [Jia et al., 2018](https://doi.org/10.1111/jep.12968) | overview of systematic reviews؛ 17 review، صدها مطالعه | CDSS در process-of-care منظم‌تر از patient outcomes اثر نشان داده است. | کیفیت گزارش و روش‌ها متفاوت؛ برای claim outcome کافی نیست. |
| [Abd Elqader & Srulovici, 2024](https://doi.org/10.1111/jan.16423) | systematic review؛ 35 مقاله/65 outcome | personalization، آموزش patient-centered و تماس مستقیم در جمعیت عرب مؤثرتر از remote monitoring غیرشخصی گزارش شد. | جمعیت ایران معادل جمعیت‌های بررسی‌شده نیست؛ فقط سیگنال بومی‌سازی است. |
| [Lo Monaco et al., 2025](https://doi.org/10.1002/nop2.70265) | umbrella review؛ 31 systematic review | telenursing، تماس، پیام و coaching برای self-management و HbA1c امیدبخش‌اند. | long-term sustainability و cost-effectiveness نامطمئن است. |
| [Alcántara-Porcuna et al., 2026](https://doi.org/10.1111/nhs.70348) | qualitative evidence synthesis؛ 27 مطالعه/522 نفر | empowerment، communication و visualization ارزش دارند؛ burden، هزینه، مشکلات فنی و نبود حمایت engagement را کم می‌کنند. | بیشتر دربارهٔ T1D/device experience؛ تعمیم مستقیم به T2D نیازمند احتیاط است. |

### پیام طراحی

```text
self-monitoring
+ feedback انسانی
+ education
+ action plan
+ response workflow
```

از data logging تنها قابل‌دفاع‌تر است.

---

## ۳. فشارخون و home monitoring

| منبع | نوع/حجم | یافته | محدودیت |
|---|---|---|---|
| [Zhou et al., 2023](https://doi.org/10.1111/jch.14690) | meta-analysis؛ 13 RCT | mHealth در uncontrolled hypertension با control rate بهتر و کاهش BP همراه بود. | interventionها از SMS تا telemonitoring متفاوت‌اند. |
| [Wang et al., 2021](https://doi.org/10.1111/jch.14194) | clinical review | telemonitoring معمولاً به co-intervention مانند feedback، education، counseling یا treatment adjustment نیاز دارد. | review روایی است؛ protocol واحد ارائه نمی‌کند. |
| [Carey et al., 2024](https://doi.org/10.1111/jch.14795) | systematic review؛ 18 مطالعه CKD | HBPM در بیشتر مطالعات بخشی از مداخلهٔ چندجزئی و review بالینی بوده است. | heterogeneity بالا و کیفیت بخشی از مطالعات پایین/متوسط. |
| [Miao et al., 2022](https://doi.org/10.1111/jch.14487) | systematic review + meta-analysis؛ 35 مطالعه/49,432 نفر | clinic و home BP قابل‌جایگزینی ساده نیستند؛ زمان و context measurement مهم است. | اختلاف‌های منطقه‌ای و جمعیتی وجود دارد. |

### پیام طراحی

- dashboard نباید یک reading منفرد را مانند تشخیص قطعی رنگ‌آمیزی کند.
- protocol، context، میانگین/روند و verification باید در مدل داده وجود داشته باشند.
- abnormal data بدون owner و response SLA جمع‌آوری نشود.

---

## ۴. بیماری قلبی و نارسایی قلبی

| منبع | نوع/حجم | یافته | محدودیت |
|---|---|---|---|
| [De Lathauwer et al., 2025](https://doi.org/10.1002/ejhf.3568) | meta-analysis؛ 41 مطالعه/16,312 بیمار | RPM با کاهش mortality و نخستین HF hospitalization همراه بود؛ self-management، education و video communication مؤلفه‌های مهم بودند. | intervention heterogeneity؛ همهٔ زیرگروه‌ها به یک اندازه نمایندگی نشده‌اند. |
| [Ni et al., 2024](https://doi.org/10.1155/2024/6859795) | systematic review + meta-analysis؛ 24 مطالعه/2886 نفر | app-based intervention با HF hospitalization کمتر و QoL بهتر همراه بود؛ mortality نتیجهٔ قطعی نداشت. | certainty و طراحی مطالعات متفاوت است. |
| [Ramtin et al., 2023](https://doi.org/10.1002/nop2.1698) | systematic review + meta-analysis؛ 11 مطالعه | distance education در follow-up کوتاه‌تر با readmission کمتر همراه بود؛ اثر بلندمدت نامطمئن‌تر بود. | heterogeneity در follow-up طولانی. |
| [Varma et al., 2021](https://doi.org/10.1002/joa3.12461) | international collaborative statement | implementation، adherence و actionability تعیین می‌کنند monitoring مفید یا پرسر‌وصدا باشد. | تمرکز اصلی arrhythmia/mHealth؛ برخی مثال‌ها broader HF هستند. |

### پیام طراحی

«بیماری قلبی» باید به programهای محدود تبدیل شود؛ مثلاً:

```text
HTN / ASCVD risk
Heart-failure transition and monitoring
Post-MI secondary prevention
Arrhythmia/device pathway
```

یک ماژول مبهم قلبی از نظر داده، rule، workflow و مسئولیت قابل دفاع نیست.

---

## ۵. سالمند، caregiver و تجربهٔ بیمار

| منبع | نوع/حجم | یافته | پیام UX |
|---|---|---|---|
| [Kim & Ha, 2026](https://doi.org/10.1111/opn.70062) | systematic review؛ 10 مطالعه/1293 سالمند | engagement strategyها هنوز کم‌توسعه‌اند؛ onboarding، ongoing feedback و family support مهم‌اند. | آموزش تدریجی، پشتیبانی مداوم و family involvement. |
| [Wang et al., 2025](https://doi.org/10.1111/wvn.70030) | systematic review + qualitative meta-synthesis | فناوری باید comprehensive، usable و کم‌بار باشد و technical support داشته باشد. | «کمترین کار لازم» و support channel در خود محصول. |
| [Vick & Wolff, 2021](https://doi.org/10.1111/1475-6773.13857) | scoping review of reviews | family engagement و downsides engagement کمتر بررسی شده‌اند. | proxy رسمی، consent، scope و revoke؛ نه credential sharing. |
| [Samal et al., 2021](https://doi.org/10.1111/1475-6773.13860) | evidence review؛ 44 مطالعه MCC | workflow integration و provider burden تعیین‌کننده‌اند؛ شواهد outcome یکدست نیست. | هر patient feature باید queue/owner/response flow کارکنان داشته باشد. |
| [Yan et al., 2024](https://doi.org/10.1111/nhs.70006) | scoping review؛ 38 مطالعه | task difficulty، language، navigation، error feedback، text visibility و interface design بر mental workload اثر دارند. | زبان ساده، navigation کوتاه، error قابل اصلاح و visual hierarchy. |

---

## ۶. CDS، alert fatigue و AI

| منبع | نوع | یافته | قاعدهٔ حلقه |
|---|---|---|---|
| [Gholamzadeh et al., 2023](https://doi.org/10.1155/2023/8550905) | systematic review؛ 38 مقاله | knowledge-based CDSS عمدتاً patient-specific guidance، alerts و EBM adherence را هدف می‌گیرد؛ framework استاندارد لازم است. | evidence registry و rule lifecycle. |
| [Ronan et al., 2022](https://doi.org/10.1002/jhm.12825) | systematic review + meta-analysis | CDSS به‌طور کلی adoption مطلوب پزشک را فقط محدود/نامنظم افزایش داد. | count alert یا fire rate معیار موفقیت نیست. |
| [Shah et al., 2018](https://doi.org/10.1002/phar.2153) | narrative review alert fatigue | alert کم‌اهمیت و پرتعداد باعث desensitization و workaround می‌شود. | tiering، specificity، owner و alert budget. |
| [Halkin, 2020](https://doi.org/10.1002/cpt.1813) | clinical commentary | alert باید severity-tiered، patient-specific و کم‌اختلال باشد. | interruption فقط برای high-specificity safety event. |
| [Ayalew et al., 2026](https://doi.org/10.1002/widm.70089) | systematic review LLM medical summarization | hallucination، workflow integration و regulatory attention شکاف‌های اصلی‌اند. | LLM برای draft/summarize با citation؛ نه autonomous treatment. |

---

## ۷. گایدلاین‌ها و استانداردهای رسمی

| مرجع | کاربرد در حلقه | وضعیت استفاده |
|---|---|---|
| [KDIGO 2024 CKD Guideline](https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf) | staging، risk assessment، medication stewardship، models of care | باید rule-by-rule توسط nephrology + research review شود. |
| [2024 ESC Guidelines for elevated BP and hypertension](https://doi.org/10.1093/eurheartj/ehae178) | hypertension/risk framework | thresholdها بدون local clinical sign-off وارد کد نشوند. |
| ADA Standards of Care (annual) | diabetes evidence package | نسخهٔ سالانه باید pin شود؛ لینک/نسخه در دور clinical content audit نهایی شود. |
| [FHIR R5 CarePlan](https://hl7.org/fhir/R5/careplan.html) | تفکیک patient-specific care plan از generic protocol، goal/team/activity | alignment مفهومی؛ فعلاً الزام FHIR server نیست. |
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | accessibility، focus، target size، error prevention، accessible auth | هدف حداقل AA + تست انسانی سالمند/کم‌سواد. |
| [WHO Ethics and Governance of AI for Health](https://www.who.int/publications/i/item/9789240029200) | ethics، human rights، accountability و stakeholder governance | design constraint و governance reference. |
| [FDA Clinical Decision Support Software Guidance, Jan 2026](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software) | distinctionهای CDS، patient/caregiver-facing risk و independent review | مرجع محافظه‌کارانه؛ ادعای انطباق آمریکا نیست. |

---

## ۸. رجیستر قابلیت رقبا

این بخش capability mapping است. ادعاهای outcome صفحات فروش، مگر با مقالهٔ مستقل، **vendor-reported** محسوب می‌شوند.

| محصول | صفحه رسمی | قابلیت‌های قابل مشاهده | درس برای حلقه |
|---|---|---|---|
| MyChart | [mychart.org](https://www.mychart.org/) | schedule، medications، results، bills، information sharing، family care، virtual doctor، unified login | baseline پرتال: proxy/family، messaging/access، نتایج و billing. |
| Omada | [omadahealth.com](https://www.omadahealth.com/) | diabetes/HTN programs، coaching، connected devices، personal plan، lessons/community | device بدون coach/plan تمایز کافی نیست. |
| Teladoc Health | [teladochealth.com](https://www.teladochealth.com/) | virtual care، diabetes/HTN، coaching و connected care | chronic care باید به access و care team وصل باشد. |
| Dario | [dariohealth.com](https://www.dariohealth.com/) | multi-condition digital programs، cardiometabolic و behavioral/MSK | تجربهٔ یکپارچهٔ چندبیماری baseline جهانی است. |
| Welldoc | [welldoc.com](https://www.welldoc.com/) | cardiometabolic data integration، AI coaching، device-agnostic sources | data fragmentation و explainable actionable insight مسئلهٔ بازار است. |
| Huma | [huma.com](https://www.huma.com/) | remote patient monitoring، deployment/validation و enterprise scale | deployment governance و adaptability سازمانی مهم‌اند. |
| Cadence | [cadence.care](https://www.cadence.care/) | daily vitals/symptoms/meds، care team، triage، titration workflow و EHR integration | monitoring باید به تیم و protocol response متصل باشد. |
| پذیرش۲۴ | [paziresh24.com](https://www.paziresh24.com/) | discovery، نوبت و مشاوره | معیار UX رزرو و دسترسی ایران. |
| دکتورتو | [doctoreto.com](https://doctoreto.com/) | نوبت، مشاوره آنلاین/تلفنی، مراکز و آزمایش | marketplace/access قوی؛ تمایز حلقه باید care operations باشد. |
| دکترساینا | [drsaina.com](https://www.drsaina.com/) | ویزیت آنلاین، آزمایش در منزل، تفسیر آزمایش و راهنمای انتخاب تخصص | expectation بیمار برای service access و navigation بالا رفته است. |

### قابلیت‌های baseline که باید در gap analysis بمانند

```text
Patient account & recovery
Caregiver/proxy access
Care plan & goals
Secure messaging
Appointment and request management
Medication/refill workflow
Results and education
Connected-device onboarding
Consent/preferences/export
Accessible authentication
Human response workflow
```

---

## ۹. محدودیت‌های پژوهش این دور

- سرچ تازهٔ Consensus به‌علت تمام‌شدن سهمیهٔ ماهانه انجام نشد؛ replication پس از ۱ اوت ۲۰۲۶ لازم است.
- Scholar Gateway پوشش کامل همهٔ ناشران را تضمین نمی‌کند.
- هیچ مطالعهٔ منتشرشده مستقیماً محصول حلقه، context ایران یا workflow کلینیک هدف را ارزیابی نکرده است.
- نتایج vendor مستقل نیستند.
- threshold و medication ruleها در این دور audit خط‌به‌خط نشده‌اند.
- تحلیل رقبای ایرانی فقط بر صفحات عمومی قابل دسترس است؛ demo و مصاحبه مشتری انجام نشده است.
- شواهد digital health heterogeneous هستند؛ component، population، intensity و human support تفاوت دارند.

---

## ۱۰. کارهای اعتبارسنجی دور بعد

1. replication جستجوها با Consensus و PubMed/official guideline repositories؛
2. evidence appraisal رسمی برای diabetes، HTN و HF program package؛
3. demo-based competitor teardown با taskهای ثابت؛
4. مصاحبه با بیمار سالمند، caregiver و کاربران سه نوع مرکز؛
5. audit کامل rule catalog فعلی با version/source/owner؛
6. usability benchmark روی prototype صفحهٔ «امروز»؛
7. workflow capacity model برای review داده‌های خانگی؛
8. threat model patient auth، caregiver grant و messaging؛
9. تصمیم product boundary حسابداری؛
10. تدوین PRD و acceptance criteria پیش از شروع پیاده‌سازی portal.

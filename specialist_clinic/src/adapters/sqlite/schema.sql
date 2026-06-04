-- Specialist Clinic schema (independent DB: specialist.db)
-- All timestamps stored as Tehran local time.

-- Users (independent auth)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash BLOB NOT NULL,
    role TEXT NOT NULL DEFAULT 'staff',  -- 'manager', 'staff'
    full_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER DEFAULT 0,
    locked_until TEXT,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes'))
);

-- Patient links: local mirror + link to accounting patient (by national_id)
CREATE TABLE IF NOT EXISTS patient_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    national_id TEXT UNIQUE,
    accounting_patient_id INTEGER,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    gender TEXT,
    birthdate TEXT,
    address TEXT,
    notes TEXT,
    wallet_balance INTEGER NOT NULL DEFAULT 0,   -- credit balance (Toman)
    is_active INTEGER NOT NULL DEFAULT 1,
    enrolled_by TEXT,
    enrolled_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    updated_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes'))
);

-- Wallet transactions (the legal workaround for "discount/free": frame promotions as wallet credit/اعتبار)
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,            -- + credit added, - credit used
    balance_after INTEGER NOT NULL,
    reason TEXT,                        -- 'campaign','manual','redeem','expire'
    campaign_id INTEGER,
    note TEXT,
    expires_at TEXT,                    -- gregorian YYYY-MM-DD (optional)
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_patient ON wallet_transactions (patient_link_id, created_at DESC);

-- Conditions catalog
CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    code TEXT,
    is_active INTEGER DEFAULT 1
);

-- Patient conditions (diagnoses)
CREATE TABLE IF NOT EXISTS patient_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    condition_id INTEGER NOT NULL,
    stage TEXT,
    onset_date TEXT,                 -- gregorian YYYY-MM-DD
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    diagnosed_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY (condition_id) REFERENCES conditions(id)
);

-- Medications
CREATE TABLE IF NOT EXISTS patient_medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    drug_name TEXT NOT NULL,
    dose TEXT,
    schedule TEXT,
    start_date TEXT,                 -- gregorian YYYY-MM-DD
    refill_due_date TEXT,            -- gregorian YYYY-MM-DD
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Allergies
CREATE TABLE IF NOT EXISTS allergies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    substance TEXT NOT NULL,
    reaction TEXT,
    severity TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Vital readings (bp_systolic, bp_diastolic, fbs, hba1c, weight, bmi, pulse)
CREATE TABLE IF NOT EXISTS vital_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    measured_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    source TEXT DEFAULT 'clinic',    -- 'clinic', 'self'
    notes TEXT,
    recorded_by TEXT,
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Lab results
CREATE TABLE IF NOT EXISTS lab_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    test_name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    ref_low REAL,
    ref_high REAL,
    taken_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    notes TEXT,
    recorded_by TEXT,
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Appointments
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    scheduled_at TIMESTAMP NOT NULL,         -- gregorian datetime 'YYYY-MM-DD HH:MM:SS'
    appt_type TEXT,                          -- 'visit', 'lab', 'checkup'
    status TEXT NOT NULL DEFAULT 'scheduled',-- scheduled, done, no_show, cancelled
    recurrence_months INTEGER,               -- for periodic auto-appointments
    parent_appointment_id INTEGER,
    reminder_sent INTEGER DEFAULT 0,
    notes TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Follow-up tasks (worklist)
CREATE TABLE IF NOT EXISTS followup_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    due_date TEXT,                  -- gregorian YYYY-MM-DD
    reason TEXT,                    -- 'refill','uncontrolled','lapsed','visit_due','manual'
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- open, done, dismissed
    assigned_to TEXT,
    call_log TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    resolved_at TIMESTAMP,
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Care protocols (clinical decision support: periodic standard checks)
CREATE TABLE IF NOT EXISTS care_protocols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id INTEGER,
    name TEXT NOT NULL,
    interval_months INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (condition_id) REFERENCES conditions(id)
);

-- SMS templates
CREATE TABLE IF NOT EXISTS sms_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    body TEXT NOT NULL,             -- supports {name} placeholder
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes'))
);

-- SMS campaigns
CREATE TABLE IF NOT EXISTS sms_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    template_id INTEGER,
    body TEXT,
    segment TEXT,                   -- 'all','diabetes','hypertension','uncontrolled','lapsed','refill_due'
    campaign_type TEXT NOT NULL DEFAULT 'info',  -- 'info','wallet_credit','reminder'
    credit_amount INTEGER DEFAULT 0,             -- wallet credit granted per recipient (Toman)
    credit_expires_days INTEGER,                 -- optional credit expiry
    status TEXT NOT NULL DEFAULT 'draft',  -- draft, scheduled, sending, done, cancelled
    scheduled_at TIMESTAMP,
    total_recipients INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (template_id) REFERENCES sms_templates(id)
);

-- SMS messages (send log)
CREATE TABLE IF NOT EXISTS sms_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    patient_link_id INTEGER,
    recipient TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, sent, failed
    provider_msgid TEXT,
    delivery_status TEXT,
    error TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (campaign_id) REFERENCES sms_campaigns(id),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Settings (key/value: mediana api key + sending number + message type, thresholds, clinic info)
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes'))
);

-- Activity logs
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action_type TEXT,
    description TEXT,
    patient_link_id INTEGER,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pl_national ON patient_links (national_id);
CREATE INDEX IF NOT EXISTS idx_pc_patient ON patient_conditions (patient_link_id);
CREATE INDEX IF NOT EXISTS idx_vr_patient_type ON vital_readings (patient_link_id, type, measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_patient ON lab_results (patient_link_id, taken_at DESC);
CREATE INDEX IF NOT EXISTS idx_appt_sched ON appointments (scheduled_at);
CREATE INDEX IF NOT EXISTS idx_appt_patient ON appointments (patient_link_id);
CREATE INDEX IF NOT EXISTS idx_followup_status ON followup_tasks (status, due_date);
CREATE INDEX IF NOT EXISTS idx_sms_campaign ON sms_messages (campaign_id);

-- Seed conditions
INSERT OR IGNORE INTO conditions (id, name, code) VALUES (1, 'دیابت', 'diabetes');
INSERT OR IGNORE INTO conditions (id, name, code) VALUES (2, 'فشار خون', 'hypertension');
INSERT OR IGNORE INTO conditions (id, name, code) VALUES (3, 'چربی خون', 'hyperlipidemia');
INSERT OR IGNORE INTO conditions (id, name, code) VALUES (4, 'بیماری کلیوی مزمن', 'ckd');
INSERT OR IGNORE INTO conditions (id, name, code) VALUES (5, 'تیروئید', 'thyroid');

-- Seed care protocols (diabetes + hypertension standard periodic checks)
INSERT OR IGNORE INTO care_protocols (id, condition_id, name, interval_months) VALUES (1, 1, 'آزمایش HbA1c', 3);
INSERT OR IGNORE INTO care_protocols (id, condition_id, name, interval_months) VALUES (2, 1, 'معاینه فوندوس چشم', 12);
INSERT OR IGNORE INTO care_protocols (id, condition_id, name, interval_months) VALUES (3, 1, 'آزمایش عملکرد کلیه', 12);
INSERT OR IGNORE INTO care_protocols (id, condition_id, name, interval_months) VALUES (4, 2, 'کنترل فشار خون', 1);
INSERT OR IGNORE INTO care_protocols (id, condition_id, name, interval_months) VALUES (5, 2, 'نوار قلب (ECG)', 12);

-- Seed SMS templates
INSERT OR IGNORE INTO sms_templates (id, name, body) VALUES (1, 'یادآوری نوبت', 'سلام {name} عزیز، یادآوری نوبت شما در کلینیک تخصصی. لطفاً در زمان مقرر مراجعه فرمایید.');
INSERT OR IGNORE INTO sms_templates (id, name, body) VALUES (2, 'یادآوری تجدید دارو', 'سلام {name} عزیز، داروی شما رو به اتمام است. جهت تمدید نسخه با کلینیک تماس بگیرید.');
INSERT OR IGNORE INTO sms_templates (id, name, body) VALUES (3, 'دعوت به چکاپ دوره‌ای', 'سلام {name} عزیز، زمان چکاپ دوره‌ای شما فرارسیده است. برای حفظ سلامتی نوبت بگیرید.');

-- ============================================================================
-- Clinical decision rules engine (editable by the manager at /manager/rules)
-- Drives indicator metadata, red-flag thresholds, chart target lines,
-- per-disease dashboards, and the weighted risk score.
-- Source defaults: ADA Standards of Care (see docs/clinical_reference.md).
-- ============================================================================
CREATE TABLE IF NOT EXISTS clinical_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,          -- vital_readings.type key
    label TEXT NOT NULL,
    unit TEXT,
    category TEXT NOT NULL DEFAULT 'other',  -- glycemic, bp, lipid, kidney, anthro, other
    direction TEXT NOT NULL DEFAULT 'high',  -- 'high' = higher worse, 'low' = lower worse
    warn REAL,                         -- borderline threshold (NULL = no flag)
    danger REAL,                       -- red-flag threshold (NULL = no flag)
    target REAL,                       -- goal value, drawn as chart reference line
    goal_low REAL,                     -- optional goal range lower bound
    goal_high REAL,                    -- optional goal range upper bound
    conditions TEXT NOT NULL DEFAULT 'all',  -- comma list of condition codes, or 'all'
    risk_weight INTEGER NOT NULL DEFAULT 1,  -- contribution to the weighted risk score
    is_vital INTEGER NOT NULL DEFAULT 1,     -- show in vital entry / dashboard
    display_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

-- Seed indicators (ADA-based defaults; manager may edit afterwards)
INSERT OR IGNORE INTO clinical_indicators
  (key, label, unit, category, direction, warn, danger, target, goal_low, goal_high, conditions, risk_weight, display_order, notes) VALUES
  ('hba1c',        'HbA1c',              '%',          'glycemic', 'high', 7.0,  8.0,  7.0,  NULL, NULL, 'diabetes',                         3, 10, 'هدف اکثر بزرگسالان <۷٪؛ آسان‌گیرانه <۸٪'),
  ('fbs',          'قند ناشتا (FBS)',    'mg/dL',      'glycemic', 'high', 130,  180,  130,  80,   130,  'diabetes',                         2, 20, 'هدف ناشتا ۸۰–۱۳۰'),
  ('ppg',          'قند ۲ ساعت پس‌غذا',  'mg/dL',      'glycemic', 'high', 180,  250,  180,  NULL, NULL, 'diabetes',                         1, 25, 'اوج پس‌غذا <۱۸۰'),
  ('bp_systolic',  'فشار سیستول',        'mmHg',       'bp',       'high', 130,  140,  130,  NULL, NULL, 'diabetes,hypertension',            2, 30, 'هدف <۱۳۰/۸۰'),
  ('bp_diastolic', 'فشار دیاستول',       'mmHg',       'bp',       'high', 80,   90,   80,   NULL, NULL, 'diabetes,hypertension',            1, 40, 'هدف <۱۳۰/۸۰'),
  ('pulse',        'ضربان قلب',          'bpm',        'bp',       'high', 100,  120,  NULL, 60,   100,  'all',                              0, 110,'اطلاعاتی'),
  ('ldl',          'LDL کلسترول',        'mg/dL',      'lipid',    'high', 70,   100,  70,   NULL, NULL, 'diabetes,hypertension,hyperlipidemia', 2, 50, 'هدف فردی: <۷۰ پرخطر، <۵۵ ASCVD مستقر'),
  ('hdl',          'HDL کلسترول',        'mg/dL',      'lipid',    'low',  40,   35,   NULL, 40,   NULL, 'all',                              1, 60, 'هرچه بالاتر بهتر'),
  ('triglyceride', 'تری‌گلیسرید',        'mg/dL',      'lipid',    'high', 150,  500,  150,  NULL, NULL, 'diabetes,hypertension,hyperlipidemia', 1, 70, '≥۵۰۰ خطر پانکراتیت'),
  ('egfr',         'eGFR (عملکرد کلیه)', 'mL/min',     'kidney',   'low',  60,   30,   NULL, 60,   NULL, 'diabetes,hypertension,ckd',        3, 80, 'هرچه بالاتر بهتر؛ <۳۰ پرخطر'),
  ('uacr',         'UACR (آلبومین ادرار)','mg/g',      'kidney',   'high', 30,   300,  30,   NULL, NULL, 'diabetes,hypertension,ckd',        2, 90, '۳۰–۲۹۹ میکرو، ≥۳۰۰ ماکروآلبومینوری'),
  ('weight',       'وزن',                'kg',         'anthro',   'high', NULL, NULL, NULL, NULL, NULL, 'all',                              0, 100,'پایش روند'),
  ('bmi',          'BMI',                '',           'anthro',   'high', 25,   30,   NULL, NULL, 25,   'all',                              1, 105,'اضافه‌وزن ≥۲۵، چاقی ≥۳۰');

-- ============================================================================
-- Medication events: objective timeline of start / stop / dose changes.
-- Overlaid as vertical markers on indicator charts; used for pre/post effect.
-- ============================================================================
CREATE TABLE IF NOT EXISTS medication_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    medication_id INTEGER,             -- FK to patient_medications (nullable if med deleted)
    drug_name TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- 'start', 'stop', 'dose_change'
    dose TEXT,                         -- dose at/after this event
    event_date TEXT,                   -- gregorian YYYY-MM-DD
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_medevents_patient ON medication_events (patient_link_id, event_date);

-- ============================================================================
-- Clinical decision inputs (ADA T2D engines) — see docs/treatment_engine_plan.md
-- flag_catalog: editable catalog of categorical/boolean clinical inputs (ADA §2)
-- patient_flags: per-patient values for those inputs
-- drug_classes : editable catalog mapping medications to a pharmacologic class
-- ============================================================================
CREATE TABLE IF NOT EXISTS flag_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    flag_type TEXT NOT NULL DEFAULT 'bool',   -- bool | enum | date | text
    options TEXT,                             -- enum: "value|label,value|label,..."
    category TEXT NOT NULL DEFAULT 'other',    -- cardiac|renal|risk|hepatic|repro|lifestyle|functional|history|exam
    display_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS patient_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    flag_key TEXT NOT NULL,
    value TEXT,
    recorded_by TEXT,
    updated_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    UNIQUE (patient_link_id, flag_key),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_patient_flags ON patient_flags (patient_link_id);

CREATE TABLE IF NOT EXISTS drug_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    glucose_lowering INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- Seed clinical-flag catalog (ADA §2 decision inputs)
INSERT OR IGNORE INTO flag_catalog (flag_key, label, flag_type, options, category, display_order) VALUES
 ('ascvd', 'سابقهٔ ASCVD (بیماری قلبی-عروقی آترواسکلروتیک)', 'bool', NULL, 'cardiac', 10),
 ('cvd_high_risk', 'ریسک بسیار بالای قلبی-عروقی (≥۵۵ سال + ≥۲ ریسک‌فاکتور)', 'bool', NULL, 'cardiac', 20),
 ('hf', 'نارسایی قلب (HF)', 'bool', NULL, 'cardiac', 30),
 ('hf_type', 'نوع نارسایی قلب', 'enum', 'HFrEF|EF کاهش‌یافته,HFpEF|EF حفظ‌شده,unknown|نامشخص', 'cardiac', 40),
 ('hf_symptomatic', 'نارسایی قلبِ علامت‌دار', 'bool', NULL, 'cardiac', 50),
 ('ckd_stage_g', 'مرحلهٔ CKD بر اساس eGFR', 'enum', 'G1|G1 (≥۹۰),G2|G2 (۶۰–۸۹),G3a|G3a (۴۵–۵۹),G3b|G3b (۳۰–۴۴),G4|G4 (۱۵–۲۹),G5|G5 (<۱۵)', 'renal', 60),
 ('ckd_stage_a', 'مرحلهٔ آلبومینوری', 'enum', 'A1|A1 (<۳۰),A2|A2 (۳۰–۲۹۹),A3|A3 (≥۳۰۰)', 'renal', 70),
 ('hypo_risk', 'ریسک هیپوگلیسمی', 'enum', 'low|پایین,atrisk|در معرض,high|بالا', 'risk', 80),
 ('masld', 'کبد چربِ متابولیک (MASLD)', 'bool', NULL, 'hepatic', 90),
 ('mash_biopsy', 'MASH اثبات‌شده / ریسک بالای فیبروز', 'bool', NULL, 'hepatic', 100),
 ('pregnancy', 'بارداری', 'bool', NULL, 'repro', 110),
 ('childbearing_no_contraception', 'توان بارداری بدون پیشگیری', 'bool', NULL, 'repro', 120),
 ('smoking', 'مصرف دخانیات/ویپ', 'enum', 'never|هرگز,former|ترک‌کرده,current|فعلی,vape|ویپ', 'lifestyle', 130),
 ('frailty', 'وضعیت سلامت/فراژیلیتی (سالمند)', 'enum', 'robust|سالم,intermediate|میانی,complex|پیچیده/فراژیل', 'functional', 140),
 ('metabolic_surgery', 'سابقهٔ جراحی متابولیک', 'bool', NULL, 'history', 150),
 ('monofilament', 'مونوفیلامان ۱۰گرمی (حس محافظتی پا)', 'enum', 'normal|طبیعی,impaired|مختل,not_done|انجام‌نشده', 'exam', 160),
 ('eye_exam_date', 'آخرین معاینهٔ چشم (ته‌چشم گشاد)', 'date', NULL, 'exam', 170),
 ('foot_exam_date', 'آخرین معاینهٔ جامع پا', 'date', NULL, 'exam', 180);

-- ============================================================================
-- clinical_rules: the If/Then decision catalog covering EVERY section of the
-- ADA T2D document (diagnosis, screening, targets, medication, drug-safety,
-- insulin, monitoring, complication-screening, red-flags, hypoglycemia,
-- lifestyle, vaccination). Seeded idempotently from clinical_rules_seed.py.
-- Editable at /manager/decision-rules.
-- ============================================================================
CREATE TABLE IF NOT EXISTS clinical_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,        -- diagnosis|target|medication|drug_safety|insulin|
                                   -- monitoring|screening|redflag|hypo|lifestyle|vaccination|bp_rx|lipid_rx
    trigger_json TEXT,             -- machine-evaluable condition tree (NULL = informational/manual)
    human_if TEXT,
    recommendation TEXT,           -- the "Then" shown to the clinician
    dosage_titration TEXT,
    monitoring TEXT,
    contraindications TEXT,
    evidence_level TEXT,           -- A|B|C|E
    action_type TEXT NOT NULL DEFAULT 'educate',
                                   -- flag_risk|suggest_med|safety_alert|create_followup|
                                   -- schedule_screening|educate|classify|set_target|redflag|hypo|vaccine
    action_params_json TEXT,
    severity TEXT NOT NULL DEFAULT 'info',  -- info|warn|urgent
    priority INTEGER NOT NULL DEFAULT 100,
    source_ref TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_clinical_rules_cat ON clinical_rules (category, priority);

-- Physician action on engine suggestions (accountability; suggestion-only system)
CREATE TABLE IF NOT EXISTS suggestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    rule_code TEXT NOT NULL,
    suggestion_text TEXT,
    evidence_level TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|accepted|dismissed
    acted_by TEXT,
    acted_at TIMESTAMP,
    note TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    UNIQUE (patient_link_id, rule_code),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);

-- Seed drug-class catalog
INSERT OR IGNORE INTO drug_classes (class_key, label, glucose_lowering, display_order) VALUES
 ('metformin', 'متفورمین', 1, 10),
 ('sglt2i', 'مهارکنندهٔ SGLT2', 1, 20),
 ('glp1_ra', 'آگونیست GLP-1', 1, 30),
 ('dual_gip_glp1', 'آگونیست دوگانهٔ GIP/GLP-1 (تیرزپاتاید)', 1, 40),
 ('dpp4i', 'مهارکنندهٔ DPP-4', 1, 50),
 ('tzd', 'پیوگلیتازون (TZD)', 1, 60),
 ('su', 'سولفونیل‌اوره', 1, 70),
 ('meglitinide', 'مگلیتینید', 1, 80),
 ('insulin_basal', 'انسولین پایه', 1, 90),
 ('insulin_bolus', 'انسولین پراندیال (بولوس)', 1, 100),
 ('acei', 'مهارکنندهٔ ACE', 0, 110),
 ('arb', 'ARB', 0, 120),
 ('ccb', 'کلسیم‌بلاکر', 0, 130),
 ('thiazide', 'دیورتیک تیازیدی', 0, 140),
 ('statin', 'استاتین', 0, 150),
 ('ezetimibe', 'ازتیمایب', 0, 160),
 ('finerenone', 'فینرنون (nsMRA)', 0, 170),
 ('aspirin', 'آسپرین', 0, 180),
 ('other', 'سایر', 0, 999);

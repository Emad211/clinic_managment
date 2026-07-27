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
    sms_opt_out INTEGER NOT NULL DEFAULT 0,      -- patient opted out of automated SMS (engagement guardrail)
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
    idempotency_key TEXT,
    note TEXT,
    expires_at TEXT,                    -- gregorian YYYY-MM-DD (optional)
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_patient ON wallet_transactions (patient_link_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_tx_idempotency
    ON wallet_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Conditions catalog
CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    code TEXT,
    is_active INTEGER DEFAULT 1,
    is_chronic INTEGER NOT NULL DEFAULT 1,    -- shows as a managed disease module
    display_order INTEGER NOT NULL DEFAULT 100,
    description TEXT,                          -- plain-language summary for the per-disease manager page
    icon TEXT,                                -- svg sprite id (e.g. 'i-heart')
    color TEXT                                -- accent token (info|warn|danger|ok|violet)
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
    test_key TEXT,                                  -- canonical lab_test_catalog key; links lab results to the engine (NULL for free-text/legacy rows). ADR-0005.
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
    reason TEXT,                    -- 'refill','lapsed','visit_due','manual' or governed v2 task metadata
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- open, done, dismissed
    assigned_to TEXT,
    call_log TEXT,
    source_rule TEXT,
    source_event TEXT,
    appointment_id INTEGER,
    fulfillment TEXT DEFAULT 'in_person',
    source_engine TEXT,
    source_run_id TEXT,
    source_recommendation_event_id INTEGER,
    clinical_semantic_key TEXT,
    clinical_task_key TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    resolved_at TIMESTAMP,
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY (source_run_id) REFERENCES clinical_engine_runs(run_id),
    FOREIGN KEY (source_recommendation_event_id) REFERENCES clinical_recommendation_events(id)
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
    segment TEXT,                   -- descriptive/admin segments: all, condition, lapsed, refill_due
    campaign_type TEXT NOT NULL DEFAULT 'info',  -- 'info','wallet_credit','reminder'
    credit_amount INTEGER DEFAULT 0,             -- wallet credit granted per recipient (Toman)
    credit_expires_days INTEGER,                 -- optional credit expiry
    holdout_percent INTEGER NOT NULL DEFAULT 0,  -- % randomly held out as control group (incrementality)
    status TEXT NOT NULL DEFAULT 'draft',  -- draft, scheduled, sending, done, cancelled
    scheduled_at TIMESTAMP,
    total_recipients INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    delivered_count INTEGER DEFAULT 0,
    pending_count INTEGER DEFAULT 0,
    blacklist_count INTEGER DEFAULT 0,
    claim_token TEXT,
    claim_at TIMESTAMP,
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
    provider TEXT,
    provider_request_id TEXT,
    provider_msgid TEXT,
    idempotency_key TEXT,
    delivery_status TEXT,
    delivery_status_int INTEGER,
    delivery_checked_at TIMESTAMP,
    next_status_check_at TIMESTAMP,
    delivered_at TIMESTAMP,
    send_attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMP,
    retryable INTEGER NOT NULL DEFAULT 0,
    source_type TEXT,                       -- campaign | engagement | manual
    source_ref TEXT,                        -- stable source identifier for traceability
    error TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (campaign_id) REFERENCES sms_campaigns(id),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_messages_idempotency
    ON sms_messages(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sms_messages_delivery_due
    ON sms_messages(provider, next_status_check_at, delivery_status);

-- Campaign audience split (for incrementality / lift): who was treated vs held out.
-- Recorded at send time only when a campaign has holdout_percent > 0.
CREATE TABLE IF NOT EXISTS campaign_audience (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    patient_link_id INTEGER NOT NULL,
    accounting_patient_id INTEGER,          -- snapshot of the link, for revenue measurement
    grp TEXT NOT NULL DEFAULT 'treated',    -- 'treated' (sent) | 'control' (held out, not sent)
    assigned_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes')),
    FOREIGN KEY (campaign_id) REFERENCES sms_campaigns(id),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_audience ON campaign_audience (campaign_id, grp);

-- ============================================================================
-- Engagement engine (event -> channel): unifies automated reminders, follow-ups
-- and campaigns into one configurable layer. `engagement_events` is the
-- manager-editable routing table — each due event is dispatched to SMS and/or
-- the staff worklist per its `channel`. `engagement_dispatch` is the
-- idempotency/cooldown ledger so nothing is sent twice in a period.
-- ============================================================================
CREATE TABLE IF NOT EXISTS engagement_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'operational', -- operational | marketing
    channel TEXT NOT NULL DEFAULT 'worklist',    -- sms | worklist | both | off
    sms_template TEXT,                           -- {name} placeholder; used when channel includes sms
    lead_days INTEGER NOT NULL DEFAULT 0,        -- fire this many days before the due date
    cooldown_days INTEGER NOT NULL DEFAULT 30,   -- min days between repeats of this event per patient
    source_action TEXT,                          -- retained audit metadata; governed v2 tasks use their own worklist path
    priority INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS engagement_dispatch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    event_key TEXT NOT NULL,
    period_key TEXT NOT NULL,                    -- dedupe bucket (due date / month) — fire once per period
    channel TEXT NOT NULL,                       -- sms | worklist
    ref_id INTEGER,                              -- sms_messages.id or followup_tasks.id
    status TEXT NOT NULL DEFAULT 'done',
    created_at TIMESTAMP DEFAULT (datetime('now','+3 hours','+30 minutes')),
    UNIQUE (patient_link_id, event_key, period_key, channel),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_engagement_dispatch ON engagement_dispatch (patient_link_id, event_key);

-- Seed the default event -> channel routing (manager-editable afterwards).
-- Administrative outreach only. Clinical alerts and recommendations are projected by Clinical Engine v2.
INSERT OR IGNORE INTO engagement_events
  (event_key, label, category, channel, sms_template, lead_days, cooldown_days, source_action, priority) VALUES
  ('appointment_reminder','یادآوری نوبت','operational','sms','سلام {name} عزیز، یادآوری نوبت شما در کلینیک تخصصی. لطفاً در زمان مقرر مراجعه فرمایید.',1,1,NULL,10),
  ('refill_due','یادآوری تجدید دارو','operational','sms','سلام {name} عزیز، داروی شما رو به اتمام است. جهت تمدید نسخه با کلینیک تماس بگیرید.',7,25,NULL,20),
  ('lapsed','بدون مراجعه اخیر','operational','both','سلام {name} عزیز، مدتی است شما را در کلینیک ندیده‌ایم. برای ادامهٔ مراقبت نوبت بگیرید.',0,60,NULL,60),
  ('visit_invite','دعوت به نوبت (پیامکی)','operational','sms','سلام {name} عزیز، برای ادامهٔ روند درمان لطفاً جهت تعیینِ نوبتِ ویزیت با کلینیک تماس بگیرید.',0,7,NULL,15),
  -- Phase 2: invoice-triggered outreach (thank-you after invoice close + procedure follow-up invites). Manager-editable; gated by the approval queue.
  ('thank_you','تشکر پس از مراجعه','operational','sms','سلام {name} عزیز، از مراجعه و اعتمادِ شما به کلینیک سپاسگزاریم. سلامت و تندرست باشید.',0,1,NULL,16),
  ('ear_wash_invite','پیگیریِ شستشوی گوش','operational','sms','سلام {name} عزیز، جهتِ پیگیریِ شستشوی گوش در صورتِ نیاز با کلینیک هماهنگ کنید. اگر درد، ترشح یا کاهشِ شنوایی داشتید زودتر تماس بگیرید.',0,30,NULL,17),
  ('wound_care_invite','دعوتِ پانسمان/کشیدن بخیه','operational','sms','سلام {name} عزیز، برای تعویضِ پانسمان یا کشیدنِ بخیه لطفاً طبقِ زمانِ توصیه‌شدهٔ پزشک مراجعه کنید. برای هماهنگیِ نوبت تماس بگیرید.',0,30,NULL,18),
  -- Phase B (doctor-initiated visit invites): named SMS the physician triggers from the visit «مرحله بعد».
  -- Manager-editable; approval-gated; deliberately generic wording (no clinical claims / no drug names).
  ('lab_consult_invite','دعوتِ آزمایش و مشاوره','operational','sms','سلام {name} عزیز، طبقِ توصیهٔ پزشک برای انجامِ آزمایش و مشاورهٔ پیگیری لطفاً جهتِ تعیینِ نوبت با کلینیک تماس بگیرید.',0,14,NULL,19),
  ('bp_glucose_invite','یادآوریِ قند و فشار','operational','sms','سلام {name} عزیز، برای اندازه‌گیریِ دوره‌ایِ قند و فشارِ خون لطفاً جهتِ هماهنگیِ نوبت با کلینیک تماس بگیرید.',0,14,NULL,19);

-- Retire the pre-v2 threshold-driven worklist event on copied databases.
UPDATE engagement_events
SET is_active=0,
    channel='off',
    notes=COALESCE(notes,'') || '\nRetired: clinical interpretation moved to Clinical Engine v2.'
WHERE event_key IN (
    'uncontrolled','monitoring_due','screening_due','vaccine_due','red_flag'
);

-- Patient public-card access tokens (ADR-0004). Per-patient, unguessable, short-lived,
-- revocable. The PUBLIC card route only ever READS via get_by_token; issue/revoke are
-- staff actions. national_id is NEVER stored here or emitted by the card.
CREATE TABLE IF NOT EXISTS patient_card_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,                  -- secrets.token_urlsafe(32)
    issued_at TIMESTAMP DEFAULT (datetime('now','+3 hours','+30 minutes')),
    expires_at TEXT NOT NULL,                    -- Tehran local 'YYYY-MM-DD HH:MM:SS'
    revoked_at TEXT,
    issued_by TEXT,                              -- users.username who issued it
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_patient_card_token ON patient_card_tokens(token);

-- Settings (key/value: mediana api key + sending number + message type, thresholds, clinic info)
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT (datetime('now', '+3 hours', '+30 minutes'))
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('clinical_engine_v2_mode', 'off');

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
INSERT OR IGNORE INTO conditions (id, name, code, is_chronic, display_order, description, icon, color) VALUES
 (1, 'دیابت', 'diabetes', 1, 10, 'پایش قند، اهداف فردی، انتخاب دارو، غربالگری عوارض و واکسیناسیون.', 'i-activity', 'info'),
 (2, 'فشار خون', 'hypertension', 1, 20, 'کنترل فشار خون، انتخاب داروی ضدفشار، پایش کلیه/پتاسیم و هشدار بحران فشار.', 'i-heart', 'danger'),
 (3, 'چربی خون', 'hyperlipidemia', 1, 30, 'اهداف LDL، استاتین‌درمانی و پایش لیپید.', 'i-sigma', 'warn'),
 (4, 'بیماری کلیوی مزمن', 'ckd', 1, 40, 'مرحله‌بندی eGFR/آلبومینوری، داروهای محافظ کلیه و پایش.', 'i-clipboard', 'violet'),
 (5, 'تیروئید', 'thyroid', 1, 50, 'پایش TSH و تنظیم درمان تیروئید.', 'i-stethoscope', 'ok');

-- Seed care protocols (diabetes + hypertension standard periodic checks)

-- Seed SMS templates
INSERT OR IGNORE INTO sms_templates (id, name, body) VALUES (1, 'یادآوری نوبت', 'سلام {name} عزیز، یادآوری نوبت شما در کلینیک تخصصی. لطفاً در زمان مقرر مراجعه فرمایید.');
INSERT OR IGNORE INTO sms_templates (id, name, body) VALUES (2, 'یادآوری تجدید دارو', 'سلام {name} عزیز، داروی شما رو به اتمام است. جهت تمدید نسخه با کلینیک تماس بگیرید.');
INSERT OR IGNORE INTO sms_templates (id, name, body) VALUES (3, 'دعوت به چکاپ دوره‌ای', 'سلام {name} عزیز، زمان چکاپ دوره‌ای شما فرارسیده است. برای حفظ سلامتی نوبت بگیرید.');

-- ============================================================================
-- Descriptive measurement catalog.
-- Supplies labels, units, categories, disease applicability and display ordering.
-- It MUST NOT contain or drive clinical thresholds, treatment targets, risk scores,
-- alerts or recommendations; those belong exclusively to Clinical Engine v2 rules.
-- ============================================================================
CREATE TABLE IF NOT EXISTS clinical_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    unit TEXT,
    category TEXT NOT NULL DEFAULT 'other',
    conditions TEXT NOT NULL DEFAULT 'all',
    is_vital INTEGER NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

INSERT OR IGNORE INTO clinical_indicators
  (key, label, unit, category, conditions, display_order, notes) VALUES
  ('hba1c',        'HbA1c',               '%',            'glycemic', 'diabetes',                              10, 'نمایش روند'),
  ('fbs',          'قند ناشتا (FBS)',     'mg/dL',        'glycemic', 'diabetes',                              20, 'نمایش روند'),
  ('ppg',          'قند ۲ ساعت پس‌غذا',   'mg/dL',        'glycemic', 'diabetes',                              25, 'نمایش روند'),
  ('bp_systolic',  'فشار سیستول',         'mmHg',         'bp',       'diabetes,hypertension',                 30, 'نمایش روند'),
  ('bp_diastolic', 'فشار دیاستول',        'mmHg',         'bp',       'diabetes,hypertension',                 40, 'نمایش روند'),
  ('pulse',        'ضربان قلب',           'bpm',          'bp',       'all',                                  110, 'نمایش روند'),
  ('ldl',          'LDL کلسترول',         'mg/dL',        'lipid',    'diabetes,hypertension,hyperlipidemia',  50, 'نمایش روند'),
  ('hdl',          'HDL کلسترول',         'mg/dL',        'lipid',    'all',                                   60, 'نمایش روند'),
  ('triglyceride', 'تری‌گلیسرید',         'mg/dL',        'lipid',    'diabetes,hypertension,hyperlipidemia',  70, 'نمایش روند'),
  ('egfr',         'eGFR (عملکرد کلیه)',  'mL/min/1.73m²','kidney',   'diabetes,hypertension,ckd',             80, 'نمایش روند'),
  ('uacr',         'UACR (آلبومین ادرار)','mg/g',         'kidney',   'diabetes,hypertension,ckd',             90, 'نمایش روند'),
  ('weight',       'وزن',                 'kg',           'anthro',   'all',                                  100, 'نمایش روند'),
  ('bmi',          'BMI',                 '',             'anthro',   'all',                                  105, 'نمایش روند'),
  ('tsh',          'TSH (تیروئید)',       'mIU/L',        'other',    'thyroid',                              115, 'نمایش روند');

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
-- clinical_flag_events: typed append-only per-patient history
-- drug_classes : editable catalog mapping medications to a pharmacologic class
-- ============================================================================
CREATE TABLE IF NOT EXISTS flag_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    flag_type TEXT NOT NULL DEFAULT 'bool',   -- bool | enum | date | text
    options TEXT,                             -- retired input format; migration canonicalizes it
    options_json TEXT,                        -- canonical [{"value","label"}, ...]
    definition_hash TEXT,                     -- semantic identity (key/type/options/active/version)
    definition_version INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL DEFAULT 'other',   -- cardiac|renal|risk|hepatic|repro|lifestyle|functional|history|exam
    display_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    record_section TEXT,
    notes TEXT
);

-- Longitudinal, typed and append-only decision inputs. Audit triggers and strict
-- value/supersession guards are installed by clinical_flag_history_schema.py.
CREATE TABLE IF NOT EXISTS clinical_flag_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    flag_key TEXT NOT NULL CHECK (length(trim(flag_key)) > 0),
    status TEXT NOT NULL CHECK (status IN ('PRESENT','UNKNOWN','NOT_ASKED')),
    value_json TEXT,
    flag_type TEXT NOT NULL CHECK (flag_type IN ('bool','enum','date','text')),
    definition_hash TEXT NOT NULL CHECK (length(definition_hash)=64),
    verification TEXT NOT NULL DEFAULT 'CONFIRMED'
      CHECK (verification IN ('CONFIRMED','PROVISIONAL','UNVERIFIED','REFUTED')),
    source TEXT NOT NULL DEFAULT 'clinician'
      CHECK (source IN ('clinician','patient','caregiver','imported','system')),
    source_record_id TEXT,
    actor_user_id INTEGER,
    actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
    effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
    recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
    batch_id TEXT NOT NULL CHECK (length(trim(batch_id)) > 0),
    supersedes_event_id INTEGER,
    note TEXT,
    CHECK (datetime(effective_at) <= datetime(recorded_at)),
    CHECK (
      (status='PRESENT' AND value_json IS NOT NULL AND json_valid(value_json))
      OR (status<>'PRESENT' AND value_json IS NULL)
    ),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY (flag_key) REFERENCES flag_catalog(flag_key),
    FOREIGN KEY (actor_user_id) REFERENCES users(id),
    FOREIGN KEY (supersedes_event_id) REFERENCES clinical_flag_events(id)
);
CREATE INDEX IF NOT EXISTS idx_clinical_flag_events_projection
    ON clinical_flag_events(patient_link_id, flag_key, recorded_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_clinical_flag_events_effective
    ON clinical_flag_events(patient_link_id, effective_at, recorded_at, id);
CREATE INDEX IF NOT EXISTS idx_clinical_flag_events_batch
    ON clinical_flag_events(patient_link_id, batch_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_flag_events_one_per_batch
    ON clinical_flag_events(patient_link_id, batch_id, flag_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_flag_events_one_child
    ON clinical_flag_events(supersedes_event_id)
    WHERE supersedes_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS drug_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    glucose_lowering INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- Seed clinical-flag catalog (ADA §2 decision inputs)
INSERT OR IGNORE INTO flag_catalog (flag_key, label, flag_type, options, options_json, definition_hash, definition_version, category, display_order) VALUES
 ('ascvd', 'سابقهٔ ASCVD (بیماری قلبی-عروقی آترواسکلروتیک)', 'bool', NULL, '[]', '3d19e17c0e34a0fdfffed3508ec52bb78146435dc65042984addd4834c26304d', 1, 'cardiac', 10),
 ('cvd_high_risk', 'ریسک بسیار بالای قلبی-عروقی (≥۵۵ سال + ≥۲ ریسک‌فاکتور)', 'bool', NULL, '[]', 'f540af588404e0684fc37ec3b8ef2c064e9c48d97ec92348f9d76f10d1626fb4', 1, 'cardiac', 20),
 ('hf', 'نارسایی قلب (HF)', 'bool', NULL, '[]', '33a983fb8c46be7fafe64e76132912befd15592177351dfc4c94fdced858f221', 1, 'cardiac', 30),
 ('hf_type', 'نوع نارسایی قلب', 'enum', 'HFrEF|EF کاهش‌یافته,HFpEF|EF حفظ‌شده,unknown|نامشخص', '[{"label":"EF کاهش‌یافته","value":"HFrEF"},{"label":"EF حفظ‌شده","value":"HFpEF"},{"label":"نامشخص","value":"unknown"}]', '5357fb10b920702b86ac174ba8ed037e61137e150b9ab92fc1099dd5fba5928b', 1, 'cardiac', 40),
 ('hf_symptomatic', 'نارسایی قلبِ علامت‌دار', 'bool', NULL, '[]', '2998b151451e32396c1f08a8ff1c67c7f8e52830c671dbebb8616e9737eedcf4', 1, 'cardiac', 50),
 ('ckd_stage_g', 'مرحلهٔ CKD بر اساس eGFR', 'enum', 'G1|G1 (≥۹۰),G2|G2 (۶۰–۸۹),G3a|G3a (۴۵–۵۹),G3b|G3b (۳۰–۴۴),G4|G4 (۱۵–۲۹),G5|G5 (<۱۵)', '[{"label":"G1 (≥۹۰)","value":"G1"},{"label":"G2 (۶۰–۸۹)","value":"G2"},{"label":"G3a (۴۵–۵۹)","value":"G3a"},{"label":"G3b (۳۰–۴۴)","value":"G3b"},{"label":"G4 (۱۵–۲۹)","value":"G4"},{"label":"G5 (<۱۵)","value":"G5"}]', '8d8b96cd7e6fed405d5719e629333550f25368f93ee2c3f828160bcb531c5bc5', 1, 'renal', 60),
 ('ckd_stage_a', 'مرحلهٔ آلبومینوری', 'enum', 'A1|A1 (<۳۰),A2|A2 (۳۰–۲۹۹),A3|A3 (≥۳۰۰)', '[{"label":"A1 (<۳۰)","value":"A1"},{"label":"A2 (۳۰–۲۹۹)","value":"A2"},{"label":"A3 (≥۳۰۰)","value":"A3"}]', '9e394eea169c368f3e404abb5a40156afff8ebc24107cb824426597c181b4073', 1, 'renal', 70),
 ('hypo_risk', 'ریسک هیپوگلیسمی', 'enum', 'low|پایین,atrisk|در معرض,high|بالا', '[{"label":"پایین","value":"low"},{"label":"در معرض","value":"atrisk"},{"label":"بالا","value":"high"}]', '29eca6db11c90736cb5f3d43ffffa5b971f62dba1b027514ea3af3e46b40dcef', 1, 'risk', 80),
 ('masld', 'کبد چربِ متابولیک (MASLD)', 'bool', NULL, '[]', 'e4a61128e35c278f3af215487551450de0ba42c5110dfbf7abbbea59353b0267', 1, 'hepatic', 90),
 ('mash_biopsy', 'MASH اثبات‌شده / ریسک بالای فیبروز', 'bool', NULL, '[]', 'c6434309bd8a4fdbc8365cc2fb4e8dff8ce49080573bd2b14db5d03442b065b0', 1, 'hepatic', 100),
 ('pregnancy', 'بارداری', 'bool', NULL, '[]', '495d687e880cab3d73def759a3065d543fb89f1e6e3eb04572fa0db07244a797', 1, 'repro', 110),
 ('childbearing_no_contraception', 'توان بارداری بدون پیشگیری', 'bool', NULL, '[]', '02f08c682405d5483b58f9a8737e5d21c80b15653413b44c5ba9623623340b27', 1, 'repro', 120),
 ('smoking', 'مصرف دخانیات/ویپ', 'enum', 'never|هرگز,former|ترک‌کرده,current|فعلی,vape|ویپ', '[{"label":"هرگز","value":"never"},{"label":"ترک‌کرده","value":"former"},{"label":"فعلی","value":"current"},{"label":"ویپ","value":"vape"}]', '1a3a78d436c0cbeb05828eb329caef736aae75511b831153a512e8f0ce4cfa4a', 1, 'lifestyle', 130),
 ('frailty', 'وضعیت سلامت/فراژیلیتی (سالمند)', 'enum', 'robust|سالم,intermediate|میانی,complex|پیچیده/فراژیل', '[{"label":"سالم","value":"robust"},{"label":"میانی","value":"intermediate"},{"label":"پیچیده/فراژیل","value":"complex"}]', 'e8b9d3b5667ff5f5381f31376dc10f0f5f64968b6ad3ba5b336b2727d847e628', 1, 'functional', 140),
 ('metabolic_surgery', 'سابقهٔ جراحی متابولیک', 'bool', NULL, '[]', 'a621ae8b11e34ce52c1c37bd5730a4c10ad12d156ffcf8b7888a4e5aaa075c23', 1, 'history', 150),
 ('monofilament', 'مونوفیلامان ۱۰گرمی (حس محافظتی پا)', 'enum', 'normal|طبیعی,impaired|مختل,not_done|انجام‌نشده', '[{"label":"طبیعی","value":"normal"},{"label":"مختل","value":"impaired"},{"label":"انجام‌نشده","value":"not_done"}]', '1646698e884e9d59c93812662eb1d3302e7910baf71054c9b80ae0413d38d33e', 1, 'exam', 160),
 ('eye_exam_date', 'آخرین معاینهٔ چشم (ته‌چشم گشاد)', 'date', NULL, '[]', 'e8aaeac1db2b36bf5223ff3d3256c7e50315fe53bc9116eb93edd02cae6b442e', 1, 'exam', 170),
 ('foot_exam_date', 'آخرین معاینهٔ جامع پا', 'date', NULL, '[]', '3be3418d8cf3d798bed2c4ca9616907e8e79821913dc10f9d41d19677bd3e2c2', 1, 'exam', 180);

-- Clinical decision support is stored exclusively in the versioned v2 tables below.

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
 ('beta_blocker', 'بتابلاکر', 0, 190),
 ('loop_diuretic', 'دیورتیک لوپ', 0, 200),
 ('fibrate', 'فیبرات', 0, 210),
 ('mra', 'آنتاگونیست گیرنده مینرالوکورتیکوئید', 0, 220),
 ('thyroid_agent', 'داروی تیروئید/لووتیروکسین', 0, 230),
 ('antithyroid', 'ضدتیروئید', 0, 240),
 ('other', 'سایر', 0, 999);

-- ============================================================================
-- Record redesign / care-loop foundation (Phase 1 — docs/record_redesign_plan.md §2)
-- Lab/drug catalogs, per-disease lab mapping, the structured patient record
-- (surgery / medical history / clinical notes / prescriptions) and the
-- per-patient engagement approval queue. Catalog rows are seeded idempotently
-- from lab_catalog_seed.py / drug_catalog_seed.py at bootstrap.
-- ============================================================================

-- lab_test_catalog: editable catalog of lab tests (unit + reference range);
-- drives the record's lab-entry dropdown (name → unit / ref-range auto-fill).
CREATE TABLE IF NOT EXISTS lab_test_catalog (
    test_key TEXT PRIMARY KEY,
    name_fa TEXT NOT NULL,
    unit TEXT,
    ref_low REAL,
    ref_high REAL,
    category TEXT,
    display_order INTEGER DEFAULT 100,
    is_active INTEGER DEFAULT 1
);

-- condition_lab_tests: per-disease frequently-ordered tests (chips in the record).
CREATE TABLE IF NOT EXISTS condition_lab_tests (
    condition_code TEXT NOT NULL,
    lab_test_key TEXT NOT NULL,
    display_order INTEGER DEFAULT 100,
    PRIMARY KEY (condition_code, lab_test_key)
);

-- drug_catalog: drug names filtered by pharmacologic class + standard doses.
CREATE TABLE IF NOT EXISTS drug_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generic_fa TEXT NOT NULL,
    drug_class_key TEXT,
    standard_doses TEXT,
    is_active INTEGER DEFAULT 1
);

-- surgery_history: per-patient surgical history.
CREATE TABLE IF NOT EXISTS surgery_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    performed_on TEXT,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now','+3 hours','+30 minutes'))
    , FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_surgery_history_patient ON surgery_history(patient_link_id);

-- medical_history: per-patient past medical history / comorbidities.
CREATE TABLE IF NOT EXISTS medical_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    note TEXT,
    since TEXT,
    created_at TEXT DEFAULT (datetime('now','+3 hours','+30 minutes'))
    , FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_medical_history_patient ON medical_history(patient_link_id);

-- clinical_notes: free-text record notes; kind ∈ symptom|exam|lifestyle|general.
CREATE TABLE IF NOT EXISTS clinical_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    body TEXT,
    recorded_at TEXT DEFAULT (datetime('now','+3 hours','+30 minutes')),
    recorded_by TEXT
    , FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_clinical_notes_patient ON clinical_notes(patient_link_id);

-- prescriptions: prescription log; mode ∈ free|insurance. portal_rx_id/insurer
-- carry the insurance-portal fields used by the prescribing bridge (Phase 6).
CREATE TABLE IF NOT EXISTS prescriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    items TEXT,
    mode TEXT DEFAULT 'free',
    insurer TEXT,
    portal_rx_id TEXT,
    prescriber_user_id INTEGER,
    followup_task_id INTEGER,
    issued_at TEXT DEFAULT (datetime('now','+3 hours','+30 minutes'))
    , FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_prescriptions_patient ON prescriptions(patient_link_id);

-- engagement_approvals: per-patient physician approval queue (SMS only sent after
-- approval). period_key dedupes per cycle; offer is reserved for Phase 8 pricing.
CREATE TABLE IF NOT EXISTS engagement_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    event_key TEXT NOT NULL,
    channel TEXT,
    due_date TEXT,
    message TEXT,
    offer TEXT,
    status TEXT DEFAULT 'pending',
    period_key TEXT,
    appointment_id INTEGER,
    decided_by TEXT,
    decided_at TEXT,
    sent_at TEXT,
    sms_message_id INTEGER,
    send_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT DEFAULT (datetime('now','+3 hours','+30 minutes')),
    UNIQUE(patient_link_id, event_key, period_key)
    , FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
    , FOREIGN KEY (sms_message_id) REFERENCES sms_messages(id)
);
CREATE INDEX IF NOT EXISTS idx_engagement_approvals_patient ON engagement_approvals(patient_link_id);

-- processed_invoices: read-only invoice-sync ledger (ADR-0003 D3+). Idempotent record
-- of accounting invoices observed as CLOSED via the read-only bridge. The accounting DB
-- is never written. cursor lives in settings (key 'invoice_sync_last_id').
CREATE TABLE IF NOT EXISTS processed_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accounting_invoice_id INTEGER NOT NULL UNIQUE,   -- idempotency key
    patient_link_id INTEGER,                          -- NULL until/unless the patient is enrolled
    national_id TEXT,
    full_name TEXT,
    work_date TEXT,
    closed_at TEXT,
    total_amount REAL,
    status TEXT NOT NULL DEFAULT 'applied',           -- applied | pending_link
    outreach_done INTEGER NOT NULL DEFAULT 0,         -- 1 once thank-you/invite enqueue succeeded; retried until then (decoupled from the idempotency key)
    processed_at TIMESTAMP DEFAULT (datetime('now','+3 hours','+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_processed_invoices_patient ON processed_invoices(patient_link_id);
CREATE INDEX IF NOT EXISTS idx_processed_invoices_status ON processed_invoices(status);

-- doctor_visit_log: physician visit-queue state (phase3). The live queue is a read-only
-- read of OPEN accounting invoices; this table only holds the در‌نوبت/انجام‌شده state the
-- physician sets. status 'done' = physician pressed End Visit — it does NOT close the
-- accounting invoice (reception does). Idempotent via UNIQUE accounting_invoice_id.
CREATE TABLE IF NOT EXISTS doctor_visit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accounting_invoice_id INTEGER NOT NULL UNIQUE,
    patient_link_id INTEGER,
    national_id TEXT,
    full_name TEXT NOT NULL,
    work_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',   -- waiting | in_progress | done
    started_at TIMESTAMP,
    done_at TIMESTAMP,
    physician_notes TEXT,
    done_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','+3 hours','+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
CREATE INDEX IF NOT EXISTS idx_doctor_visit_log_workdate ON doctor_visit_log(work_date, status);

-- ============================================================================
-- Clinical Engine v2: immutable rule/ruleset versions and append-only audit.
-- This is the only clinical decision-rule storage contract. Runtime remains
-- disabled by clinical_engine_v2_mode=off until an activation seal is valid.
-- ============================================================================
CREATE TABLE IF NOT EXISTS clinical_rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code TEXT NOT NULL,
    version TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '2.0',
    dsl_version TEXT NOT NULL DEFAULT '2.0',
    phase TEXT NOT NULL CHECK (phase IN ('PREFLIGHT', 'SAFETY', 'ROUTINE')),
    action_type TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (lifecycle_status IN ('DRAFT', 'VALIDATED', 'APPROVED', 'SILENT',
                                    'ACTIVE', 'SUSPENDED', 'RETIRED')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    supersedes_rule_version_id INTEGER,
    retired_at TEXT,
    change_note TEXT,
    UNIQUE(rule_code, version),
    UNIQUE(content_hash),
    FOREIGN KEY(supersedes_rule_version_id) REFERENCES clinical_rule_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_rule_versions_code
ON clinical_rule_versions(rule_code, id DESC);
CREATE INDEX IF NOT EXISTS idx_rule_versions_status
ON clinical_rule_versions(lifecycle_status, phase);

CREATE TABLE IF NOT EXISTS clinical_rulesets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset_code TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'SILENT', 'ACTIVE', 'SUSPENDED', 'RETIRED')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_by TEXT,
    activated_at TEXT,
    retired_at TEXT,
    note TEXT,
    UNIQUE(ruleset_code, version),
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_rulesets_status
ON clinical_rulesets(ruleset_code, status);

CREATE TABLE IF NOT EXISTS clinical_ruleset_members (
    ruleset_id INTEGER NOT NULL,
    rule_version_id INTEGER NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('PREFLIGHT', 'SAFETY', 'ROUTINE')),
    sort_order INTEGER NOT NULL DEFAULT 100,
    PRIMARY KEY(ruleset_id, rule_version_id),
    FOREIGN KEY(ruleset_id) REFERENCES clinical_rulesets(id),
    FOREIGN KEY(rule_version_id) REFERENCES clinical_rule_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_ruleset_members_order
ON clinical_ruleset_members(ruleset_id, phase, sort_order, rule_version_id);

CREATE TABLE IF NOT EXISTS clinical_engine_runs (
    run_id TEXT PRIMARY KEY,
    patient_link_id INTEGER NOT NULL,
    encounter_key TEXT,
    as_of_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    run_status TEXT NOT NULL
        CHECK (run_status IN ('RUNNING', 'COMPLETED', 'COMPLETED_WITH_ERRORS',
                              'SAFETY_FAILED', 'FACT_BUILD_FAILED', 'AUDIT_FAILED')),
    engine_version TEXT NOT NULL,
    ruleset_id INTEGER,
    fact_snapshot_json TEXT NOT NULL,
    fact_snapshot_hash TEXT NOT NULL,
    summary_json TEXT,
    error_json TEXT,
    legacy_compare_json TEXT,
    created_by TEXT,
    FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY(ruleset_id) REFERENCES clinical_rulesets(id)
);
CREATE INDEX IF NOT EXISTS idx_engine_runs_patient_time
ON clinical_engine_runs(patient_link_id, as_of_at DESC);
CREATE INDEX IF NOT EXISTS idx_engine_runs_status
ON clinical_engine_runs(run_status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_engine_runs_ruleset
ON clinical_engine_runs(ruleset_id, started_at DESC);

CREATE TABLE IF NOT EXISTS clinical_rule_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    rule_version_id INTEGER NOT NULL,
    predicate_state TEXT NOT NULL
        CHECK (predicate_state IN ('TRUE', 'FALSE', 'UNKNOWN', 'ERROR')),
    outcome TEXT NOT NULL
        CHECK (outcome IN ('FIRED', 'NOT_FIRED', 'NEEDS_DATA', 'NOT_APPLICABLE',
                           'SUPPRESSED', 'ERROR')),
    trace_json TEXT NOT NULL,
    data_issues_json TEXT,
    recommendation_json TEXT,
    suppression_json TEXT,
    error_json TEXT,
    duration_ms REAL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, rule_version_id),
    FOREIGN KEY(run_id) REFERENCES clinical_engine_runs(run_id),
    FOREIGN KEY(rule_version_id) REFERENCES clinical_rule_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_rule_eval_run_outcome
ON clinical_rule_evaluations(run_id, outcome);
CREATE INDEX IF NOT EXISTS idx_rule_eval_rule
ON clinical_rule_evaluations(rule_version_id, outcome, created_at DESC);

CREATE TABLE IF NOT EXISTS clinical_recommendation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    evaluation_id INTEGER,
    recommendation_key TEXT NOT NULL,
    action_type TEXT NOT NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('CREATED', 'PRESENTED', 'SUPPRESSED', 'SUPERSEDED')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES clinical_engine_runs(run_id),
    FOREIGN KEY(evaluation_id) REFERENCES clinical_rule_evaluations(id)
);
CREATE INDEX IF NOT EXISTS idx_rec_events_run
ON clinical_recommendation_events(run_id, event_type, id);
CREATE INDEX IF NOT EXISTS idx_rec_events_key
ON clinical_recommendation_events(recommendation_key, created_at DESC);

CREATE TABLE IF NOT EXISTS clinical_decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_event_id INTEGER NOT NULL,
    patient_link_id INTEGER NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('ACCEPTED', 'DISMISSED', 'DEFERRED', 'CORRECTED')),
    reason_code TEXT,
    reason_text TEXT,
    actor_user_id INTEGER,
    actor_username TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    supersedes_event_id INTEGER,
    FOREIGN KEY(recommendation_event_id) REFERENCES clinical_recommendation_events(id),
    FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY(actor_user_id) REFERENCES users(id),
    FOREIGN KEY(supersedes_event_id) REFERENCES clinical_decision_events(id)
);
CREATE INDEX IF NOT EXISTS idx_decision_events_recommendation
ON clinical_decision_events(recommendation_event_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_decision_events_patient
ON clinical_decision_events(patient_link_id, occurred_at DESC);

-- A run may be finalized once; all terminal runs and audit children are immutable.
CREATE TRIGGER IF NOT EXISTS trg_engine_runs_terminal_no_update
BEFORE UPDATE ON clinical_engine_runs
WHEN OLD.run_status <> 'RUNNING'
BEGIN
    SELECT RAISE(ABORT, 'terminal clinical_engine_runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_engine_runs_identity_immutable
BEFORE UPDATE OF patient_link_id, encounter_key, as_of_at, started_at,
                 engine_version, ruleset_id, fact_snapshot_json,
                 fact_snapshot_hash, created_by
ON clinical_engine_runs
BEGIN
    SELECT RAISE(ABORT, 'clinical_engine_run identity and snapshot are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_engine_runs_no_delete
BEFORE DELETE ON clinical_engine_runs
BEGIN
    SELECT RAISE(ABORT, 'clinical_engine_runs cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_evaluations_no_update
BEFORE UPDATE ON clinical_rule_evaluations BEGIN
    SELECT RAISE(ABORT, 'clinical_rule_evaluations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_evaluations_running_insert_only
BEFORE INSERT ON clinical_rule_evaluations
WHEN (SELECT run_status FROM clinical_engine_runs WHERE run_id=NEW.run_id) <> 'RUNNING'
BEGIN
    SELECT RAISE(ABORT, 'evaluations require a RUNNING clinical_engine_run');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_evaluations_no_delete
BEFORE DELETE ON clinical_rule_evaluations BEGIN
    SELECT RAISE(ABORT, 'clinical_rule_evaluations cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_events_no_update
BEFORE UPDATE ON clinical_recommendation_events BEGIN
    SELECT RAISE(ABORT, 'clinical_recommendation_events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_events_no_delete
BEFORE DELETE ON clinical_recommendation_events BEGIN
    SELECT RAISE(ABORT, 'clinical_recommendation_events cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_events_running_insert_only
BEFORE INSERT ON clinical_recommendation_events
WHEN NEW.event_type IN ('CREATED', 'SUPPRESSED')
 AND (SELECT run_status FROM clinical_engine_runs WHERE run_id=NEW.run_id) <> 'RUNNING'
BEGIN
    SELECT RAISE(ABORT, 'created/suppressed recommendations require a RUNNING clinical_engine_run');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_events_terminal_presentation
BEFORE INSERT ON clinical_recommendation_events
WHEN NEW.event_type IN ('PRESENTED', 'SUPERSEDED')
 AND (SELECT run_status FROM clinical_engine_runs WHERE run_id=NEW.run_id) = 'RUNNING'
BEGIN
    SELECT RAISE(ABORT, 'presentation/supersession requires a terminal clinical_engine_run');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_evaluation_same_run
BEFORE INSERT ON clinical_recommendation_events
WHEN NEW.evaluation_id IS NOT NULL
 AND (SELECT run_id FROM clinical_rule_evaluations WHERE id=NEW.evaluation_id) <> NEW.run_id
BEGIN
    SELECT RAISE(ABORT, 'recommendation evaluation must belong to the same run');
END;
CREATE TRIGGER IF NOT EXISTS trg_decision_events_no_update
BEFORE UPDATE ON clinical_decision_events BEGIN
    SELECT RAISE(ABORT, 'clinical_decision_events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_decision_events_no_delete
BEFORE DELETE ON clinical_decision_events BEGIN
    SELECT RAISE(ABORT, 'clinical_decision_events cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_decision_events_terminal_run_only
BEFORE INSERT ON clinical_decision_events
WHEN (SELECT r.run_status
      FROM clinical_recommendation_events e
      JOIN clinical_engine_runs r ON r.run_id=e.run_id
      WHERE e.id=NEW.recommendation_event_id) = 'RUNNING'
BEGIN
    SELECT RAISE(ABORT, 'clinical decisions require a terminal engine run');
END;

-- Rule content and ruleset identity are versioned; lifecycle fields may change.
CREATE TRIGGER IF NOT EXISTS trg_rule_version_content_immutable
BEFORE UPDATE OF rule_code, version, schema_version, dsl_version, phase,
                 action_type, rule_json, content_hash,
                 created_by, created_at, supersedes_rule_version_id
ON clinical_rule_versions BEGIN
    SELECT RAISE(ABORT, 'clinical rule version content is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_versions_no_delete
BEFORE DELETE ON clinical_rule_versions BEGIN
    SELECT RAISE(ABORT, 'clinical rule versions cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_ruleset_identity_immutable
BEFORE UPDATE OF ruleset_code, version, content_hash, created_by, created_at
ON clinical_rulesets BEGIN
    SELECT RAISE(ABORT, 'clinical ruleset identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_rulesets_no_delete
BEFORE DELETE ON clinical_rulesets BEGIN
    SELECT RAISE(ABORT, 'clinical rulesets cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_ruleset_members_draft_insert_only
BEFORE INSERT ON clinical_ruleset_members
WHEN (SELECT status FROM clinical_rulesets WHERE id = NEW.ruleset_id) <> 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'members can only be added to a DRAFT ruleset');
END;
CREATE TRIGGER IF NOT EXISTS trg_ruleset_members_no_update
BEFORE UPDATE ON clinical_ruleset_members BEGIN
    SELECT RAISE(ABORT, 'create a new ruleset version');
END;
CREATE TRIGGER IF NOT EXISTS trg_ruleset_members_no_delete
BEFORE DELETE ON clinical_ruleset_members BEGIN
    SELECT RAISE(ABORT, 'retire the ruleset instead');
END;

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

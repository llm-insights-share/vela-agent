-- Demo PM product ops schema（星河控股 · 产品部）
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
  product_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT NOT NULL,
  stage TEXT NOT NULL,
  owner_pm TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roadmap_items (
  roadmap_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  title TEXT NOT NULL,
  quarter TEXT NOT NULL,
  priority TEXT NOT NULL,
  status TEXT NOT NULL,
  target_metric TEXT,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS backlog_items (
  backlog_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  priority_score REAL NOT NULL,
  status TEXT NOT NULL,
  owner_pm TEXT NOT NULL,
  effort_points INTEGER,
  description TEXT,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS competitors (
  competitor_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  pricing_model TEXT,
  strengths TEXT,
  weaknesses TEXT,
  last_reviewed TEXT
);

CREATE TABLE IF NOT EXISTS competitor_features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  competitor_id TEXT NOT NULL,
  feature_name TEXT NOT NULL,
  support_level TEXT NOT NULL,
  notes TEXT,
  FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
);

CREATE TABLE IF NOT EXISTS user_feedback (
  feedback_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  user_segment TEXT,
  sentiment TEXT NOT NULL,
  theme TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  linked_backlog_id TEXT,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS research_interviews (
  interview_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  persona TEXT NOT NULL,
  interviewee TEXT NOT NULL,
  interviewed_at TEXT NOT NULL,
  pain_points TEXT NOT NULL,
  jobs_to_be_done TEXT,
  quotes TEXT,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS metrics_daily (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT NOT NULL,
  metric_date TEXT NOT NULL,
  dau INTEGER,
  new_users INTEGER,
  activation_rate REAL,
  retention_d7 REAL,
  conversion_rate REAL,
  revenue_cny REAL,
  nps REAL,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS funnel_weekly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT NOT NULL,
  week_start TEXT NOT NULL,
  acquisition INTEGER,
  activation INTEGER,
  retention INTEGER,
  referral INTEGER,
  revenue INTEGER,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS event_definitions (
  event_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  event_name TEXT NOT NULL,
  trigger_timing TEXT NOT NULL,
  page_or_module TEXT NOT NULL,
  properties_json TEXT NOT NULL,
  owner_pm TEXT NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS experiments (
  exp_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  name TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  status TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  control_metric REAL,
  treatment_metric REAL,
  sample_size INTEGER,
  conclusion TEXT,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS prd_docs (
  prd_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  title TEXT NOT NULL,
  version TEXT NOT NULL,
  status TEXT NOT NULL,
  author TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  summary TEXT,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- Demo Office OA schema（星河控股 · 行政办公）
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS employees (
  emp_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  dept TEXT NOT NULL,
  title TEXT NOT NULL,
  email TEXT,
  manager_id TEXT
);

CREATE TABLE IF NOT EXISTS meeting_rooms (
  room_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  capacity INTEGER NOT NULL,
  floor TEXT NOT NULL,
  equipment TEXT,
  status TEXT NOT NULL DEFAULT 'available'
);

CREATE TABLE IF NOT EXISTS meetings (
  meeting_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  room_id TEXT,
  organizer_id TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  status TEXT NOT NULL,
  attendees TEXT,
  agenda TEXT,
  FOREIGN KEY (room_id) REFERENCES meeting_rooms(room_id),
  FOREIGN KEY (organizer_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS meeting_minutes (
  minutes_id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL,
  recorder_id TEXT NOT NULL,
  content_md TEXT NOT NULL,
  published_at TEXT,
  status TEXT NOT NULL,
  FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id),
  FOREIGN KEY (recorder_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS action_items (
  action_id TEXT PRIMARY KEY,
  meeting_id TEXT,
  title TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  due_date TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'P1',
  status TEXT NOT NULL,
  evidence TEXT,
  FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id),
  FOREIGN KEY (owner_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS travel_requests (
  travel_id TEXT PRIMARY KEY,
  emp_id TEXT NOT NULL,
  destination TEXT NOT NULL,
  purpose TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  budget_cny REAL NOT NULL,
  status TEXT NOT NULL,
  approved_by TEXT,
  FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS expense_claims (
  claim_id TEXT PRIMARY KEY,
  emp_id TEXT NOT NULL,
  travel_id TEXT,
  category TEXT NOT NULL,
  amount_cny REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'CNY',
  submitted_at TEXT NOT NULL,
  status TEXT NOT NULL,
  receipt_count INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  FOREIGN KEY (emp_id) REFERENCES employees(emp_id),
  FOREIGN KEY (travel_id) REFERENCES travel_requests(travel_id)
);

CREATE TABLE IF NOT EXISTS expense_items (
  item_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL,
  item_date TEXT NOT NULL,
  item_type TEXT NOT NULL,
  amount_cny REAL NOT NULL,
  vendor TEXT,
  receipt_ok INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY (claim_id) REFERENCES expense_claims(claim_id)
);

CREATE TABLE IF NOT EXISTS seal_requests (
  seal_id TEXT PRIMARY KEY,
  applicant_id TEXT NOT NULL,
  seal_type TEXT NOT NULL,
  doc_title TEXT NOT NULL,
  copies INTEGER NOT NULL DEFAULT 1,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  used_at TEXT,
  FOREIGN KEY (applicant_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS supply_items (
  sku TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  unit TEXT NOT NULL,
  stock_qty INTEGER NOT NULL,
  reorder_level INTEGER NOT NULL,
  unit_cost_cny REAL
);

CREATE TABLE IF NOT EXISTS supply_requests (
  req_id TEXT PRIMARY KEY,
  applicant_id TEXT NOT NULL,
  sku TEXT NOT NULL,
  qty INTEGER NOT NULL,
  status TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  FOREIGN KEY (applicant_id) REFERENCES employees(emp_id),
  FOREIGN KEY (sku) REFERENCES supply_items(sku)
);

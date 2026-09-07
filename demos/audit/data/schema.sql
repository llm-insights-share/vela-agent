-- Demo audit mock ERP / OA schema (星河控股 · 华北分公司)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS org_units (
  org_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id TEXT
);

CREATE TABLE IF NOT EXISTS employees (
  emp_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  title TEXT NOT NULL,
  dept TEXT NOT NULL,
  org_id TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT,
  FOREIGN KEY (org_id) REFERENCES org_units(org_id)
);

CREATE TABLE IF NOT EXISTS oa_archives (
  doc_id TEXT PRIMARY KEY,
  emp_id TEXT NOT NULL,
  doc_type TEXT NOT NULL,
  title TEXT NOT NULL,
  filed_at TEXT NOT NULL,
  summary TEXT NOT NULL,
  FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS gl_balances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  period TEXT NOT NULL,
  account_code TEXT NOT NULL,
  account_name TEXT NOT NULL,
  debit REAL NOT NULL DEFAULT 0,
  credit REAL NOT NULL DEFAULT 0,
  org_id TEXT NOT NULL,
  FOREIGN KEY (org_id) REFERENCES org_units(org_id)
);

CREATE TABLE IF NOT EXISTS ap_ar (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  counterparty TEXT NOT NULL,
  amount REAL NOT NULL,
  nature TEXT NOT NULL,
  period TEXT NOT NULL,
  related_party INTEGER NOT NULL DEFAULT 0,
  aging_days INTEGER NOT NULL DEFAULT 0,
  org_id TEXT NOT NULL,
  FOREIGN KEY (org_id) REFERENCES org_units(org_id)
);

CREATE TABLE IF NOT EXISTS contracts (
  contract_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  amount REAL NOT NULL,
  sign_date TEXT NOT NULL,
  counterparty TEXT NOT NULL,
  status TEXT NOT NULL,
  org_id TEXT NOT NULL,
  approval_no TEXT,
  FOREIGN KEY (org_id) REFERENCES org_units(org_id)
);

CREATE TABLE IF NOT EXISTS capex (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  budget REAL NOT NULL,
  actual REAL NOT NULL,
  approval_no TEXT,
  risk_flag INTEGER NOT NULL DEFAULT 0,
  org_id TEXT NOT NULL,
  FOREIGN KEY (org_id) REFERENCES org_units(org_id)
);

-- Demo HRIS schema (星河控股人事)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS departments (
  dept_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id TEXT
);

CREATE TABLE IF NOT EXISTS employees (
  emp_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  dept_id TEXT NOT NULL,
  title TEXT NOT NULL,
  level TEXT NOT NULL,
  hire_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  salary_band TEXT,
  FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
);

CREATE TABLE IF NOT EXISTS leave_balances (
  emp_id TEXT PRIMARY KEY,
  annual_remaining REAL NOT NULL DEFAULT 0,
  compensatory_remaining REAL NOT NULL DEFAULT 0,
  as_of TEXT NOT NULL,
  FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS leave_requests (
  request_id TEXT PRIMARY KEY,
  emp_id TEXT NOT NULL,
  leave_type TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  days REAL NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

CREATE TABLE IF NOT EXISTS job_requisitions (
  req_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  dept_id TEXT NOT NULL,
  level TEXT NOT NULL,
  status TEXT NOT NULL,
  headcount INTEGER NOT NULL DEFAULT 1,
  opened_at TEXT NOT NULL,
  FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
);

CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  req_id TEXT,
  status TEXT NOT NULL,
  source TEXT,
  summary TEXT,
  FOREIGN KEY (req_id) REFERENCES job_requisitions(req_id)
);

CREATE TABLE IF NOT EXISTS interviews (
  interview_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL,
  round_name TEXT NOT NULL,
  scheduled_at TEXT,
  interviewer TEXT,
  status TEXT NOT NULL,
  FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS attendance_monthly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  emp_id TEXT NOT NULL,
  month TEXT NOT NULL,
  work_days INTEGER NOT NULL,
  late_count INTEGER NOT NULL DEFAULT 0,
  absent_days REAL NOT NULL DEFAULT 0,
  FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
);

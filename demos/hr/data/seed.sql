DELETE FROM attendance_monthly;
DELETE FROM interviews;
DELETE FROM candidates;
DELETE FROM job_requisitions;
DELETE FROM leave_requests;
DELETE FROM leave_balances;
DELETE FROM employees;
DELETE FROM departments;

INSERT INTO departments (dept_id, name, parent_id) VALUES
  ('D_HQ', '星河控股', NULL),
  ('D_RD', '研发中心', 'D_HQ'),
  ('D_SALES', '销售部', 'D_HQ'),
  ('D_HR', '人力资源部', 'D_HQ'),
  ('D_FIN', '财务部', 'D_HQ');

INSERT INTO employees (emp_id, name, dept_id, title, level, hire_date, status, salary_band) VALUES
  ('H001', '周敏', 'D_RD', '研发总监', 'M3', '2018-04-01', 'active', 'P8'),
  ('H002', '韩磊', 'D_RD', '后端高级工程师', 'P6', '2019-07-15', 'active', 'P6'),
  ('H003', '苏晴', 'D_RD', '后端工程师', 'P5', '2021-03-01', 'active', 'P5'),
  ('H004', '马超', 'D_RD', '前端工程师', 'P5', '2020-09-10', 'active', 'P5'),
  ('H005', '林悦', 'D_RD', '测试工程师', 'P4', '2022-01-05', 'active', 'P4'),
  ('H006', '何伟', 'D_RD', '运维工程师', 'P5', '2021-11-20', 'active', 'P5'),
  ('H007', '徐娜', 'D_SALES', '销售经理', 'M2', '2017-06-01', 'active', 'P7'),
  ('H008', '高飞', 'D_SALES', '客户成功', 'P4', '2023-02-14', 'active', 'P4'),
  ('H009', '白露', 'D_HR', 'HRBP', 'P5', '2019-01-08', 'active', 'P5'),
  ('H010', '唐果', 'D_HR', '招聘专员', 'P3', '2024-01-15', 'active', 'P3'),
  ('H011', '沈凯', 'D_FIN', '会计', 'P4', '2020-05-01', 'active', 'P4'),
  ('H012', '任洁', 'D_RD', '试用期后端工程师', 'P4', '2025-11-01', 'probation', 'P4');

INSERT INTO leave_balances (emp_id, annual_remaining, compensatory_remaining, as_of) VALUES
  ('H001', 12.0, 2.0, '2026-09-01'),
  ('H002', 8.5, 1.0, '2026-09-01'),
  ('H003', 15.0, 0.0, '2026-09-01'),
  ('H004', 6.0, 3.5, '2026-09-01'),
  ('H005', 10.0, 0.5, '2026-09-01'),
  ('H006', 14.0, 0.0, '2026-09-01'),
  ('H007', 3.0, 0.0, '2026-09-01'),
  ('H008', 9.0, 1.0, '2026-09-01'),
  ('H009', 11.0, 0.0, '2026-09-01'),
  ('H010', 7.0, 0.0, '2026-09-01'),
  ('H011', 5.5, 2.0, '2026-09-01'),
  ('H012', 0.0, 0.0, '2026-09-01');

INSERT INTO leave_requests (request_id, emp_id, leave_type, start_date, end_date, days, status) VALUES
  ('LR01', 'H002', '年假', '2026-09-08', '2026-09-09', 2.0, 'approved'),
  ('LR02', 'H003', '年假', '2026-09-15', '2026-09-19', 5.0, 'pending'),
  ('LR03', 'H004', '调休', '2026-09-05', '2026-09-05', 1.0, 'approved'),
  ('LR04', 'H007', '事假', '2026-09-10', '2026-09-10', 1.0, 'approved'),
  ('LR05', 'H006', '病假', '2026-08-20', '2026-08-21', 2.0, 'approved'),
  ('LR06', 'H001', '年假', '2026-10-01', '2026-10-07', 5.0, 'pending'),
  ('LR07', 'H009', '年假', '2026-09-22', '2026-09-23', 2.0, 'approved'),
  ('LR08', 'H005', '年假', '2026-09-12', '2026-09-12', 1.0, 'rejected');

INSERT INTO job_requisitions (req_id, title, dept_id, level, status, headcount, opened_at) VALUES
  ('REQ-BE', '后端高级工程师', 'D_RD', 'P6', 'open', 2, '2026-07-01'),
  ('REQ-FE', '前端工程师', 'D_RD', 'P5', 'open', 1, '2026-08-10'),
  ('REQ-HR', 'HRBP', 'D_HR', 'P5', 'closed', 1, '2026-03-01');

INSERT INTO candidates (candidate_id, name, req_id, status, source, summary) VALUES
  ('C-LN', '李娜', 'REQ-BE', 'screening', '猎头', '5年 Python/FastAPI，缺 K8s 生产经验'),
  ('C-WQ', '王强', 'REQ-BE', 'screening', '社招', '偏前端 Vue/React，后端经验不足 1 年'),
  ('C-CX', '陈希', 'REQ-FE', 'interview', '内推', '4年前端，组件库经验丰富');

INSERT INTO interviews (interview_id, candidate_id, round_name, scheduled_at, interviewer, status) VALUES
  ('IV1', 'C-LN', '简历评估', '2026-09-02T10:00:00', '白露', 'done'),
  ('IV2', 'C-LN', '技术一面', NULL, '韩磊', 'planned'),
  ('IV3', 'C-WQ', '简历评估', '2026-09-01T15:00:00', '唐果', 'done'),
  ('IV4', 'C-CX', '技术一面', '2026-09-05T14:00:00', '马超', 'scheduled');

INSERT INTO attendance_monthly (emp_id, month, work_days, late_count, absent_days) VALUES
  ('H001', '2026-08', 22, 0, 0),
  ('H002', '2026-08', 22, 1, 0),
  ('H003', '2026-08', 22, 0, 0),
  ('H004', '2026-08', 21, 2, 1),
  ('H005', '2026-08', 22, 0, 0),
  ('H006', '2026-08', 22, 0, 0),
  ('H012', '2026-08', 0, 0, 0);

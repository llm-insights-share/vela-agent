DELETE FROM supply_requests;
DELETE FROM supply_items;
DELETE FROM seal_requests;
DELETE FROM expense_items;
DELETE FROM expense_claims;
DELETE FROM travel_requests;
DELETE FROM action_items;
DELETE FROM meeting_minutes;
DELETE FROM meetings;
DELETE FROM meeting_rooms;
DELETE FROM employees;

INSERT INTO employees (emp_id, name, dept, title, email, manager_id) VALUES
  ('O001', '白露', '人力资源部', 'HRBP', 'bailu@xinghe.demo', 'O010'),
  ('O002', '韩磊', '研发中心', '后端高级工程师', 'hanlei@xinghe.demo', 'O003'),
  ('O003', '周敏', '研发中心', '研发总监', 'zhoumin@xinghe.demo', NULL),
  ('O004', '徐娜', '销售部', '销售经理', 'xuna@xinghe.demo', NULL),
  ('O005', '沈凯', '财务部', '会计', 'shenkai@xinghe.demo', 'O011'),
  ('O006', '陈薇', '行政部', '行政主管', 'chenwei@xinghe.demo', NULL),
  ('O007', '赵宇', '行政部', '行政专员', 'zhaoyu@xinghe.demo', 'O006'),
  ('O008', '苏晴', '研发中心', '后端工程师', 'suqing@xinghe.demo', 'O003'),
  ('O009', '高飞', '销售部', '客户成功', 'gaofei@xinghe.demo', 'O004'),
  ('O010', '唐果', '人力资源部', '招聘专员', 'tangguo@xinghe.demo', 'O001'),
  ('O011', '钱进', '财务部', '财务经理', 'qianjin@xinghe.demo', NULL),
  ('O012', '林悦', '产品部', '产品经理', 'linyue@xinghe.demo', 'O013'),
  ('O013', '江河', '产品部', '产品总监', 'jianghe@xinghe.demo', NULL);

INSERT INTO meeting_rooms (room_id, name, capacity, floor, equipment, status) VALUES
  ('R301', '星辰厅', 12, '3F', '投屏,白板,视频会议', 'available'),
  ('R302', '银河厅', 8, '3F', '投屏,电话会议', 'available'),
  ('R501', '董事会会议室', 20, '5F', '投屏,录音,视频会议', 'available'),
  ('R201', '敏捷小会议室', 4, '2F', '白板', 'maintenance');

INSERT INTO meetings (meeting_id, title, room_id, organizer_id, start_at, end_at, status, attendees, agenda) VALUES
  ('M20260908', 'Q3 产品周会', 'R301', 'O012', '2026-09-08T10:00:00', '2026-09-08T11:00:00', 'completed',
   'O012,O013,O003,O002', '1.本周交付回顾 2.审批中心需求优先级 3.埋点验收'),
  ('M20260910', '华北客户拜访复盘', 'R302', 'O004', '2026-09-10T14:00:00', '2026-09-10T15:30:00', 'completed',
   'O004,O009,O012', '1.客户痛点 2.合同续约风险 3.下一步行动'),
  ('M20260912', '行政例会·会议督办', 'R301', 'O006', '2026-09-12T09:30:00', '2026-09-12T10:00:00', 'scheduled',
   'O006,O007,O011,O001', '1.上周督办销项 2.差旅超标案例 3.用印台账抽查'),
  ('M20260915', '差旅报销制度宣贯', 'R501', 'O011', '2026-09-15T15:00:00', '2026-09-15T16:00:00', 'scheduled',
   'O011,O005,O006,O004,O003', '1.新标准说明 2.常见驳回原因 3.Q&A');

INSERT INTO meeting_minutes (minutes_id, meeting_id, recorder_id, content_md, published_at, status) VALUES
  ('MM001', 'M20260908', 'O012',
   '# Q3 产品周会纪要

**时间**：2026-09-08 10:00-11:00  **地点**：星辰厅
**主持人**：江河  **记录人**：林悦

## 决议
1. 审批中心 MVP 本迭代优先交付（责任人：林悦，截止 2026-09-20）
2. 埋点清单需在评审前冻结（责任人：苏晴，截止 2026-09-12）

## 待办
- 输出竞品对比一页纸给销售（林悦，2026-09-11）
',
   '2026-09-08T18:00:00', 'published'),
  ('MM002', 'M20260910', 'O009',
   '# 华北客户拜访复盘纪要

**时间**：2026-09-10 14:00-15:30

## 决议
1. 续约方案在 9/18 前提交客户（徐娜）
2. 产品侧补充「批量导出」需求进 backlog（林悦）
',
   '2026-09-10T19:00:00', 'published');

INSERT INTO action_items (action_id, meeting_id, title, owner_id, due_date, priority, status, evidence) VALUES
  ('A001', 'M20260908', '冻结审批中心埋点清单', 'O008', '2026-09-12', 'P0', 'done', '埋点表 v1.2 已入库'),
  ('A002', 'M20260908', '审批中心 MVP 需求评审', 'O012', '2026-09-20', 'P0', 'in_progress', NULL),
  ('A003', 'M20260908', '竞品对比一页纸（销售用）', 'O012', '2026-09-11', 'P1', 'overdue', NULL),
  ('A004', 'M20260910', '提交华北续约方案', 'O004', '2026-09-18', 'P0', 'open', NULL),
  ('A005', 'M20260910', '批量导出需求进 backlog', 'O012', '2026-09-16', 'P1', 'open', NULL),
  ('A006', 'M20260912', '抽查 8 月用印台账完整性', 'O007', '2026-09-14', 'P2', 'open', NULL);

INSERT INTO travel_requests (travel_id, emp_id, destination, purpose, start_date, end_date, budget_cny, status, approved_by) VALUES
  ('T001', 'O004', '北京', '华北客户拜访与续约谈判', '2026-09-09', '2026-09-10', 4500.00, 'approved', 'O011'),
  ('T002', 'O012', '上海', '参加产品经理大会并竞品调研', '2026-09-18', '2026-09-20', 6200.00, 'approved', 'O013'),
  ('T003', 'O002', '深圳', '技术交流与供应商对接', '2026-09-22', '2026-09-24', 5800.00, 'pending', NULL),
  ('T004', 'O009', '杭州', '客户成功培训', '2026-08-12', '2026-08-13', 2800.00, 'approved', 'O004');

INSERT INTO expense_claims (claim_id, emp_id, travel_id, category, amount_cny, submitted_at, status, receipt_count, note) VALUES
  ('E001', 'O004', 'T001', '差旅', 4860.50, '2026-09-11T09:00:00', 'pending_review', 5, '含客户宴请 1 次'),
  ('E002', 'O009', 'T004', '差旅', 2650.00, '2026-08-15T11:20:00', 'approved', 4, NULL),
  ('E003', 'O007', NULL, '办公采购', 890.00, '2026-09-05T16:00:00', 'approved', 2, '打印机耗材'),
  ('E004', 'O012', 'T002', '差旅', 0.00, '2026-09-01T00:00:00', 'draft', 0, '行程未开始'),
  ('E005', 'O002', NULL, '交通', 320.00, '2026-09-03T14:00:00', 'rejected', 1, '缺少行程事由说明');

INSERT INTO expense_items (item_id, claim_id, item_date, item_type, amount_cny, vendor, receipt_ok) VALUES
  ('EI01', 'E001', '2026-09-09', '机票', 1680.00, '东方航空', 1),
  ('EI02', 'E001', '2026-09-09', '酒店', 980.00, '如家商务', 1),
  ('EI03', 'E001', '2026-09-09', '市内交通', 186.50, '滴滴', 1),
  ('EI04', 'E001', '2026-09-10', '业务招待', 1680.00, '金悦轩', 1),
  ('EI05', 'E001', '2026-09-10', '市内交通', 334.00, '滴滴', 1),
  ('EI06', 'E002', '2026-08-12', '高铁', 560.00, '12306', 1),
  ('EI07', 'E002', '2026-08-12', '酒店', 720.00, '全季', 1),
  ('EI08', 'E002', '2026-08-12', '餐费', 180.00, '食堂/外卖', 1),
  ('EI09', 'E002', '2026-08-13', '市内交通', 190.00, '滴滴', 1),
  ('EI10', 'E003', '2026-09-04', '耗材', 890.00, '得力', 1),
  ('EI11', 'E005', '2026-09-02', '打车', 320.00, '滴滴', 0);

INSERT INTO seal_requests (seal_id, applicant_id, seal_type, doc_title, copies, reason, status, applied_at, used_at) VALUES
  ('S001', 'O004', '合同章', '华北客户续约框架协议-草案', 2, '客户续约盖章', 'approved', '2026-09-11T10:00:00', NULL),
  ('S002', 'O001', '公章', '员工在职证明-任洁', 1, '银行贷款材料', 'used', '2026-09-02T09:30:00', '2026-09-02T15:00:00'),
  ('S003', 'O012', '公章', '产品合作意向书-星云科技', 1, '生态合作意向', 'pending', '2026-09-11T16:20:00', NULL),
  ('S004', 'O005', '财务章', '供应商付款申请单-08月', 3, '月结付款', 'used', '2026-09-01T11:00:00', '2026-09-01T14:30:00'),
  ('S005', 'O007', '公章', '会议室改造报价确认函', 1, '行政采购', 'rejected', '2026-08-28T13:00:00', NULL);

INSERT INTO supply_items (sku, name, category, unit, stock_qty, reorder_level, unit_cost_cny) VALUES
  ('SP-A4', 'A4 复印纸 70g', '纸张', '包', 18, 20, 28.00),
  ('SP-PEN', '中性笔 0.5mm', '文具', '盒', 35, 10, 15.00),
  ('SP-TONER', '激光打印机碳粉', '耗材', '支', 4, 5, 220.00),
  ('SP-BADGE', '访客胸牌', '接待', '个', 60, 30, 3.50),
  ('SP-TEA', '会议茶歇套装', '接待', '套', 12, 8, 45.00),
  ('SP-HDMI', 'HDMI 线 2m', '设备配件', '根', 2, 5, 39.00);

INSERT INTO supply_requests (req_id, applicant_id, sku, qty, status, requested_at) VALUES
  ('SR01', 'O007', 'SP-A4', 10, 'approved', '2026-09-10T09:00:00'),
  ('SR02', 'O012', 'SP-HDMI', 2, 'pending', '2026-09-11T11:00:00'),
  ('SR03', 'O004', 'SP-TEA', 3, 'fulfilled', '2026-09-08T08:30:00'),
  ('SR04', 'O002', 'SP-TONER', 1, 'pending', '2026-09-11T14:00:00');

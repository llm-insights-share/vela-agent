DELETE FROM prd_docs;
DELETE FROM experiments;
DELETE FROM event_definitions;
DELETE FROM funnel_weekly;
DELETE FROM metrics_daily;
DELETE FROM research_interviews;
DELETE FROM user_feedback;
DELETE FROM competitor_features;
DELETE FROM competitors;
DELETE FROM backlog_items;
DELETE FROM roadmap_items;
DELETE FROM products;

INSERT INTO products (product_id, name, code, stage, owner_pm) VALUES
  ('P-VELA', 'Vela Agent 工作台', 'vela-agent', 'growth', '林悦'),
  ('P-APPROVAL', '星河审批中心', 'approval-hub', 'mvp', '林悦'),
  ('P-CS', '客户成功助手', 'cs-copilot', 'discovery', '江河');

INSERT INTO roadmap_items (roadmap_id, product_id, title, quarter, priority, status, target_metric) VALUES
  ('RM01', 'P-APPROVAL', '审批中心 MVP：待办聚合 + 一键通过/驳回', '2026Q3', 'P0', 'in_progress', '审批处理时长 -40%'),
  ('RM02', 'P-APPROVAL', '批量导出与审计日志', '2026Q3', 'P1', 'planned', '客诉「无法导出」清零'),
  ('RM03', 'P-VELA', 'Self-Opt 实验门禁可视化', '2026Q4', 'P0', 'planned', '错误变更回滚率 <2%'),
  ('RM04', 'P-VELA', 'Execution Story 回放增强', '2026Q3', 'P1', 'in_progress', 'Demo 完成率 +15%'),
  ('RM05', 'P-CS', '客户健康分试点', '2026Q4', 'P2', 'ideation', '续约风险提前 14 天预警');

INSERT INTO backlog_items (backlog_id, product_id, title, source, priority_score, status, owner_pm, effort_points, description) VALUES
  ('BL01', 'P-APPROVAL', '待办列表支持筛选（类型/状态/申请人）', '销售反馈', 92, 'ready', '林悦', 5, '华北客户要求按类型过滤'),
  ('BL02', 'P-APPROVAL', '批量导出 CSV', '客户拜访', 88, 'ready', '林悦', 3, '见会议 M20260910'),
  ('BL03', 'P-APPROVAL', '移动端简易审批', 'NPS 调研', 70, 'grooming', '林悦', 8, '移动端完成率低'),
  ('BL04', 'P-VELA', 'HITL 审批意见模板', '内部运营', 75, 'in_dev', '林悦', 2, NULL),
  ('BL05', 'P-VELA', '工具调用费用预算告警', '财务', 60, 'backlog', '江河', 5, NULL),
  ('BL06', 'P-CS', '续约风险标签', 'CS 访谈', 55, 'backlog', '江河', 5, '健康分前置依赖');

INSERT INTO competitors (competitor_id, name, category, pricing_model, strengths, weaknesses, last_reviewed) VALUES
  ('CP01', 'FlowApprove', '审批协同', '按席位订阅', '移动体验好;模板丰富', '缺审计日志导出;多租户弱', '2026-09-01'),
  ('CP02', 'AgentForge', 'Agent 平台', '用量+席位', '工具生态全;Observability 强', '中文场景与 HITL 弱', '2026-08-20'),
  ('CP03', 'Notion AI', '知识+协作', '席位订阅', '文档体验顶尖', '非审批域;权限模型偏轻', '2026-07-15'),
  ('CP04', 'ProcessOn BPM', '流程引擎', '项目制', '复杂流程编排强', 'AI Agent 能力弱;上手成本高', '2026-08-05');

INSERT INTO competitor_features (competitor_id, feature_name, support_level, notes) VALUES
  ('CP01', '待办聚合', 'full', '含移动端'),
  ('CP01', '批量导出', 'partial', '仅管理员'),
  ('CP01', '审计日志', 'none', '客户高频痛点'),
  ('CP01', 'HITL 人机协同', 'none', NULL),
  ('CP02', '多 Agent 编排', 'full', NULL),
  ('CP02', 'HITL 人机协同', 'partial', '仅回调 webhook'),
  ('CP02', '中文知识库', 'partial', '分词一般'),
  ('CP02', '审批域模板', 'none', NULL),
  ('CP03', '文档协作', 'full', NULL),
  ('CP03', '审批流', 'partial', '轻量 approve'),
  ('CP04', '复杂流程', 'full', NULL),
  ('CP04', 'AI 起草', 'partial', '规则+LLM 插件');

INSERT INTO user_feedback (feedback_id, product_id, channel, user_segment, sentiment, theme, content, created_at, linked_backlog_id) VALUES
  ('FB01', 'P-APPROVAL', '工单', '企业管理员', 'neg', '导出', '无法批量导出审批记录给内审', '2026-09-09T10:00:00', 'BL02'),
  ('FB02', 'P-APPROVAL', '访谈', '业务审批人', 'neg', '筛选', '类型太多，找不到自己的单', '2026-09-08T15:00:00', 'BL01'),
  ('FB03', 'P-APPROVAL', 'NPS', '销售', 'neu', '移动', '出差时只能用电脑批', '2026-09-01T09:00:00', 'BL03'),
  ('FB04', 'P-VELA', 'Demo回访', '技术负责人', 'pos', '可观测', 'Execution Story 对排障很有帮助', '2026-09-05T11:00:00', NULL),
  ('FB05', 'P-VELA', '工单', '平台运营', 'neg', '费用', '偶发工具循环导致 token 飙升', '2026-09-07T16:30:00', 'BL05'),
  ('FB06', 'P-CS', '访谈', '客户成功', 'neg', '预警', '续约风险发现太晚', '2026-08-28T14:00:00', 'BL06');

INSERT INTO research_interviews (interview_id, product_id, persona, interviewee, interviewed_at, pain_points, jobs_to_be_done, quotes) VALUES
  ('RI01', 'P-APPROVAL', '企业管理员', '华北某制造·信息部张工', '2026-09-03',
   '导出困难;审计抽查耗时长;权限变更无痕迹',
   '在季度内审前 1 天导出完整审批流水',
   '「你们要是能一键导出，我就续约」'),
  ('RI02', 'P-APPROVAL', '业务审批人', '销售经理徐娜（内部）', '2026-09-04',
   '待办噪音大;移动端缺失',
   '出差路上 2 分钟完成通过/驳回',
   '「筛选做好我就少漏单」'),
  ('RI03', 'P-VELA', '平台管理员', '星河 IT 沈凯', '2026-09-06',
   '费用不可见;变更缺少门禁',
   '对异常 Agent 会话做预算熔断',
   '「先让我看见钱花在哪」');

INSERT INTO metrics_daily (product_id, metric_date, dau, new_users, activation_rate, retention_d7, conversion_rate, revenue_cny, nps) VALUES
  ('P-APPROVAL', '2026-09-01', 420, 18, 0.46, 0.38, 0.12, 0, 32),
  ('P-APPROVAL', '2026-09-02', 435, 15, 0.47, 0.39, 0.11, 0, 32),
  ('P-APPROVAL', '2026-09-03', 451, 22, 0.48, 0.40, 0.13, 0, 34),
  ('P-APPROVAL', '2026-09-04', 448, 12, 0.47, 0.40, 0.12, 0, 33),
  ('P-APPROVAL', '2026-09-05', 460, 20, 0.49, 0.41, 0.14, 0, 35),
  ('P-APPROVAL', '2026-09-08', 472, 25, 0.50, 0.42, 0.14, 0, 36),
  ('P-APPROVAL', '2026-09-09', 481, 19, 0.51, 0.42, 0.15, 0, 36),
  ('P-APPROVAL', '2026-09-10', 490, 21, 0.52, 0.43, 0.15, 0, 37),
  ('P-VELA', '2026-09-08', 128, 6, 0.61, 0.55, 0.22, 18000, 41),
  ('P-VELA', '2026-09-09', 132, 4, 0.62, 0.56, 0.21, 0, 42),
  ('P-VELA', '2026-09-10', 140, 8, 0.63, 0.57, 0.23, 22000, 44);

INSERT INTO funnel_weekly (product_id, week_start, acquisition, activation, retention, referral, revenue) VALUES
  ('P-APPROVAL', '2026-08-25', 1200, 540, 310, 40, 18),
  ('P-APPROVAL', '2026-09-01', 1320, 620, 350, 48, 22),
  ('P-APPROVAL', '2026-09-08', 1405, 690, 380, 55, 25),
  ('P-VELA', '2026-09-01', 210, 130, 95, 12, 9),
  ('P-VELA', '2026-09-08', 236, 148, 108, 15, 11);

INSERT INTO event_definitions (event_id, product_id, event_name, trigger_timing, page_or_module, properties_json, owner_pm, status) VALUES
  ('EV01', 'P-APPROVAL', 'approval_list_view', '进入待办列表成功渲染后', '待办列表',
   '{"user_id":"string","filter_type":"string","result_count":"int"}', '林悦', 'active'),
  ('EV02', 'P-APPROVAL', 'approval_action_click', '点击通过/驳回时', '待办详情',
   '{"user_id":"string","action":"approve|reject","ticket_type":"string","latency_ms":"int"}', '林悦', 'active'),
  ('EV03', 'P-APPROVAL', 'approval_export_click', '点击导出按钮时', '待办列表',
   '{"user_id":"string","format":"csv","row_count":"int"}', '林悦', 'draft'),
  ('EV04', 'P-VELA', 'agent_session_start', '创建会话成功', 'AgentChat',
   '{"user_id":"string","agent_id":"string","agent_type":"SINGLE|COMPOSITE"}', '林悦', 'active'),
  ('EV05', 'P-VELA', 'tool_call_budget_warn', '会话工具费用超过阈值', '运行时',
   '{"session_id":"string","spent_usd":"float","threshold_usd":"float"}', '江河', 'planned');

INSERT INTO experiments (exp_id, product_id, name, hypothesis, status, start_date, end_date, control_metric, treatment_metric, sample_size, conclusion) VALUES
  ('EX01', 'P-APPROVAL', '待办默认筛选=与我相关', '减少噪音可提升日均处理单量', 'running', '2026-09-05', NULL, 6.2, 7.1, 800, NULL),
  ('EX02', 'P-VELA', 'HITL 意见模板', '模板可降低审批填写时长', 'completed', '2026-08-01', '2026-08-28', 48.0, 31.0, 420, '显著降低填写时长，建议全量'),
  ('EX03', 'P-APPROVAL', '导出入口强化', '提高导出发现率', 'draft', NULL, NULL, NULL, NULL, NULL, NULL);

INSERT INTO prd_docs (prd_id, product_id, title, version, status, author, updated_at, summary) VALUES
  ('PRD01', 'P-APPROVAL', '审批中心 MVP PRD', 'v0.9', 'review', '林悦', '2026-09-10', '待办聚合+动作+基础权限'),
  ('PRD02', 'P-APPROVAL', '批量导出与审计日志 PRD', 'v0.3', 'draft', '林悦', '2026-09-11', '对齐内审导出诉求'),
  ('PRD03', 'P-VELA', 'Self-Opt 门禁可视化 PRD', 'v0.1', 'ideation', '江河', '2026-09-08', '实验门禁与回滚可视化');

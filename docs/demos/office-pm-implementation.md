# 日常办公 + 产品经理 Demo：Mock 数据与实现方案

本文是两组新 Demo 的总设计说明；可执行资产已落在 `demos/office`、`demos/pm`，并由 `backend/scripts/seed_demo.py` 幂等导入。

## 1. 目标与边界

| 场景 | 目标用户 | Agent 形态 | 核心价值 |
|------|----------|------------|----------|
| 日常办公 | 行政 / 部门助理 / 财务预审 | COMPOSITE（3 专家） | 会议督办闭环、报销合规、用印与物资 |
| 产品经理 | PM / 产品负责人 | COMPOSITE（3 专家） | 竞品+反馈证据、指标验证、PRD/埋点产出 |

统一约束（对齐现有 audit/hr Demo）：

1. 制度与方法论文档进 KB（`kb_search`），**禁止凭记忆编制度条款**
2. 业务数字一律来自 `local_python` → SQLite mock，**禁止臆造金额/指标**
3. 写操作进 `outbox/` + `require_approval=true`（HITL）
4. Demo Agent `tool_loading.mode=eager`，避免 deferred Tool Search 丢绑定工具
5. 虚构企业统一为 **星河控股**，人物与 HR Demo 交叉（白露/韩磊/林悦等）

## 2. 组 A：日常办公（office）

### 2.1 Agent 设计

```
demo-office-coordinator (COMPOSITE)
├── demo-office-meeting   会议/纪要/督办
├── demo-office-expense   差旅/报销预审
└── demo-office-facility  会议室/用印/物资
```

| Agent | Skills | KB | Tools（读 / 写） |
|-------|--------|----|------------------|
| meeting | `demo-office-meeting-followup` | policies + templates | list/get meetings, action_items / submit_minutes |
| expense | `demo-office-expense-check` | policies | list_travel, get_expense / submit_review_note |
| facility | `demo-office-facility-ops` | policies | rooms, seals, supplies |
| coordinator | — | policies | 无直连工具，靠分派 |

### 2.2 外部系统 Mock（SQLite）

路径：`demos/office/data/{schema,seed}.sql` → `demo_office.db`（seed 时镜像到 `backend/data/`）

**表与规模**

| 表 | 行数级 | 说明 |
|----|--------|------|
| employees | 13 | 含行政陈薇/赵宇、产品林悦/江河 |
| meeting_rooms | 4 | R201 maintenance |
| meetings | 4 | 已完成周会/客户复盘 + 待开行政例会 |
| meeting_minutes | 2 | 已发布 Markdown |
| action_items | 6 | **A003 overdue** 作验收锚点 |
| travel_requests | 4 | T001 徐娜已批 |
| expense_claims + items | 5 + 11 | **E001** 招待费争议；**E005** 缺事由驳回 |
| seal_requests | 5 | pending / approved / used / rejected |
| supply_items + requests | 6 + 4 | A4/碳粉/HDMI 低于水位 |

**关键 Mock 事实（验收断言）**

- `A003` owner=林悦 status=`overdue` due=`2026-09-11`
- `E001` amount=`4860.5`，明细含业务招待 `1680`
- 低库存 SKU：`SP-A4`(18<20)、`SP-TONER`(4<5)、`SP-HDMI`(2<5)

### 2.3 知识库文档（网络公开实践改写）

| 文档 | 借鉴来源类型 |
|------|----------------|
| 会议纪要与督办管理办法 | 行政会议督办闭环 SOP（会后 24–48h、台账销项五要素） |
| 差旅与费用报销制度 | Handbook / Expense Reimbursement Policy（事前申请、限额、发票、时限） |
| 印章使用管理办法 | 企业用印专人保管+台账+双人核验实践 |
| 会议室与办公用品管理规定 | 行政 SOP 预约/申领/水位补货 |
| 会议纪要模板 | 标准纪要字段表 |

### 2.4 推荐对话流

1. Coordinator：「汇总逾期督办 + 预审 E001 + 低库存」
2. meeting → 列出 A003 并建议升级江河/行政
3. expense → 对照经理级招待人均标准，结论「有条件通过/补充事前批准」
4. facility → 输出补货清单
5. 可选：提交预审意见 → outbox HITL

## 3. 组 B：产品经理（pm）

### 3.1 Agent 设计

```
demo-pm-coordinator (COMPOSITE)
├── demo-pm-research   竞品/反馈/访谈
├── demo-pm-analytics  指标/漏斗/实验
└── demo-pm-prd        PRD/埋点起草
```

| Agent | Skills | KB | 关键 Tools |
|-------|--------|----|-----------|
| research | competitor-brief | playbooks+artifacts | competitors, matrix, feedback, interviews, backlog |
| analytics | metrics-insight | playbooks | metrics, funnel, experiments, events, roadmap |
| prd | prd-draft | playbooks+artifacts | backlog, feedback, interviews, events, prds, submit_prd |
| coordinator | — | playbooks | 分派汇总 |

### 3.2 外部系统 Mock（产品数据中台简化）

| 表 | 亮点数据 |
|----|----------|
| products | approval-hub / vela-agent / cs-copilot |
| backlog_items | BL01=92 筛选；BL02=88 导出（续约） |
| competitors + features | FlowApprove 审计日志=`none` |
| user_feedback | FB01 导出 neg；映射 BL02 |
| research_interviews | RI01 金句「一键导出就续约」 |
| metrics_daily | 审批 DAU 420→490，NPS↑ |
| funnel_weekly | AARRR 三周上升 |
| experiments | EX01 running；EX02 完成显著 |
| event_definitions | `approval_export_click`=`draft`（PRD 应补齐） |
| prd_docs | PRD01 review / PRD02 draft |

### 3.3 知识库

**Playbooks（方法论）**：PRD 撰写规范、竞品分析框架、埋点需求规范、访谈提纲模板  
**Artifacts（半成品）**：FlowApprove 竞品快报、审批 MVP PRD 摘录、张工访谈纪要  

公开参考：PRD 最佳实践与模板、人人都是产品经理埋点/策略 PRD、竞品多维矩阵、pm-playbook 结构。

### 3.4 推荐对话流

1. Coordinator：「竞品+反馈 → 数据验证 → 起草批量导出 PRD」
2. research → FlowApprove 差异化三点 + 映射 BL02
3. analytics → DAU/漏斗/EX01 信号；指出 export 埋点仍 draft
4. prd → 按规范输出 Markdown，`pm_submit_prd_draft` → HITL

## 4. 实现清单（已落地）

```
demos/office/
  data/schema.sql, seed.sql
  kb/policies/*.md, kb/templates/*.md
  skills/*.md
  tools/office_tools.py
demos/pm/
  data/schema.sql, seed.sql
  kb/playbooks/*.md, kb/artifacts/*.md
  skills/*.md
  tools/pm_tools.py
backend/demo_tools/__init__.py   # 导出 office_* / pm_*
backend/scripts/seed_demo.py     # 构建 DB + 注册 Agent/Skill/KB/Tool
docs/demos/office-assistant.md
docs/demos/pm-assistant.md
```

## 5. 接入步骤

```bash
cd backend
python -m scripts.seed_demo
```

验收：

1. UI Agent 列表出现 `demo-office-*`、`demo-pm-*`（已 publish）
2. 对 Coordinator 发送推荐开场白
3. 写工具触发审批中心 / outbox 文件
4. 重跑 seed 幂等（KB 仅在 doc_count=0 时灌入；Agent 绑定覆盖更新）

## 6. 后续可扩展（未做）

| 项 | 说明 |
|----|------|
| DataQuery 连接器 | 已镜像 `backend/data/demo_*.db`，可再绑只读 SQL 工具 |
| 与 HR DB 联表 | 办公员工 emp_id 与 HR H00x 映射表 |
| 日历/邮件 MCP | 用真实 MCP 替换部分 mock 读接口 |
| 评测集 | 固定话术 + 期望工具调用轨迹（对齐 selfopt/eval） |

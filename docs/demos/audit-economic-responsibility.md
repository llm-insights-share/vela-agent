# Demo A：经济责任审计立项（COMPOSITE）

虚构企业：**星河控股 · 华北分公司**。对齐 `vela-agent-types-requirements.md` §2.3。

## Agent 拓扑

| 名称 | 类型 | 职责 |
|------|------|------|
| `demo-audit-coordinator` | COMPOSITE | 分派 / 汇总 / 交付前 HITL |
| `demo-audit-collector` | SINGLE | OA/财务取数、资料清单 |
| `demo-audit-risk` | SINGLE | 法规检索 + 风险识别 |
| `demo-audit-reporter` | SINGLE | 立项说明书起草；提交草案需审批 |

`composition_config` 关键：`dispatch_strategy=llm`，`hitl_before_delivery=true`，`max_dispatch_rounds=6`。  
子 Agent 关系写入 `agent_compositions`（非仅 JSON specialists）。

## 资源清单

| 类型 | 名称 |
|------|------|
| Skill | `demo-audit-collect-checklist` / `demo-audit-risk-identify` / `demo-audit-report-draft` |
| KB | `demo-audit-regulations` / `demo-audit-templates` |
| Tools | `audit_lookup_employee`、`audit_list_oa_docs`、`audit_query_gl`、`audit_query_related_party`、`audit_list_contracts`、`audit_list_capex`、`audit_submit_engagement_draft`（HITL） |
| DB | `demos/audit/data/demo_audit.db`（由 schema+seed 生成） |

## 数据字典（核心表）

| 表 | 用途 | 预置亮点 |
|----|------|----------|
| `employees` | 被审计人 | E1001 张伟 / 华北总经理 / 2021-03-01~ |
| `org_units` | 组织 | `OU_HB` 华北分公司 |
| `oa_archives` | OA 档案 | 任职、述职、关联决策、廉政披露 |
| `gl_balances` | 总账 | 2024 年月主营收入等 |
| `ap_ar` | 往来 | **星河供应链** 应收账龄 210/185 天 |
| `contracts` | 合同 | 框架采购 **缺审批号** |
| `capex` | 投资 | 数字化仓库 **实际/预算=1.35**，`risk_flag=1` |

## 验收话术

1. （可直接对 collector）「张伟 2024 经济责任审计要收哪些资料？」
2. （risk）「华北分公司关联交易有什么风险？」
3. （reporter）「根据已收集信息起草立项说明书」
4. （reporter）「提交立项草案」→ outbox + HITL
5. （coordinator）完整开场白 → 多轮分派后汇总，可能进入交付审批

## 实现说明

- Mock DB 由 `schema.sql` + `seed.sql` 在 seed 时生成（`*.db` gitignore）
- Demo Agent 默认 `composition_config.tool_loading.mode=eager`，避免系统级 deferred Tool Search 导致绑定工具不可见
- 可选启动自动 seed：`VELA_SEED_DEMO=1`

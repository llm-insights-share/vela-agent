# Demo D：产品经理工作台（COMPOSITE）

虚构企业：**星河控股 · 产品部**。主产品线：`approval-hub`（审批中心）、`vela-agent`、`cs-copilot`。  
Coordinator：`demo-pm-coordinator`。

方法论文档对齐公开 PRD / 竞品矩阵 / 埋点 PRD / 用户访谈模板（问题导向、SMART、In/Out、事件表字段、三角验证），并沉淀 Demo 制品（竞品快报、PRD 摘录、访谈纪要）。

## Agent 拓扑

| 名称 | 类型 | 职责 |
|------|------|------|
| `demo-pm-coordinator` | COMPOSITE | 调研 → 数据 → PRD 编排 |
| `demo-pm-research` | SINGLE | 竞品 / 反馈 / 访谈 |
| `demo-pm-analytics` | SINGLE | 指标 / 漏斗 / 实验 |
| `demo-pm-prd` | SINGLE | PRD 与埋点起草（HITL 提交） |

## 绑定资源

| 类型 | 名称 |
|------|------|
| Skill | `demo-pm-competitor-brief` / `demo-pm-metrics-insight` / `demo-pm-prd-draft` |
| KB | `demo-pm-playbooks` / `demo-pm-artifacts` |
| Tools | `pm_list_*`、`pm_query_metrics`、`pm_query_funnel`、`pm_get_competitor_matrix`、`pm_submit_prd_draft`（HITL） |
| DB | `demos/pm/data/demo_pm.db` |

## 数据字典（亮点）

| 表 | 预置亮点 |
|----|----------|
| `backlog_items` | `BL01` 筛选 score=92；`BL02` 批量导出=88（续约卡点） |
| `competitors` | FlowApprove **无审计日志**；AgentForge HITL 仅 partial |
| `user_feedback` / `research_interviews` | FB01/RI01：「一键导出就续约」 |
| `metrics_daily` | 审批中心 DAU 420→490（9/1–9/10），NPS 32→37 |
| `experiments` | `EX01` 默认筛选 running；`EX02` HITL 模板已完成显著 |
| `event_definitions` | `approval_export_click` 仍为 **draft** |

## 验收话术

1. 「对比 FlowApprove，我们差异化该打哪三点？」
2. 「审批中心最近指标与漏斗怎么变？实验 EX01 有无信号？」
3. 「根据反馈和访谈，起草批量导出 PRD 草案并提交」
4. （Coordinator）竞品+数据+PRD 一条龙

## 参考来源（公开资料，非原文照搬）

- PRD 最佳实践 / VibeVibe PRD 模板 / 人人都是产品经理 BRD·MRD·PRD 分工
- 竞品多维矩阵与用户调研模板库
- 埋点 PRD 事件表字段规范（触发时机 / 属性 / 正反例）
- GitHub pm-playbook（访谈 / Persona / Roadmap 结构）

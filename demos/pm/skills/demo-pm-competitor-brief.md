---
name: demo-pm-competitor-brief
description: 输出竞品一页纸与 backlog 启示
trigger_keywords:
  - 竞品
  - 对标
  - 一页纸
  - FlowApprove
version: 1.0.0
tool_budget:
  max_tool_rounds: 8
---

# 竞品分析技能

1. `pm_list_competitors` / `pm_get_competitor_matrix` 取数
2. `kb_search` 对照《竞品分析框架》与已有竞品快报
3. 可选：`pm_list_feedback` 用客户原话作证据
4. 输出：
   - 一句话结论
   - 功能对照表
   - 跟进 / 差异化 / 不跟进
   - 对 backlog 的具体建议（引用 backlog_id）

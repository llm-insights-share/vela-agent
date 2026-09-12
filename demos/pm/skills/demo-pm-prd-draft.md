---
name: demo-pm-prd-draft
description: 按规范起草或补强 PRD / 埋点表
trigger_keywords:
  - PRD
  - 需求文档
  - 埋点
  - 用户故事
version: 1.0.0
tool_budget:
  max_tool_rounds: 10
---

# PRD 起草技能

1. 用 `pm_list_backlog` / `pm_list_feedback` / `pm_list_interviews` / `pm_list_events` 收集证据
2. `kb_search`《PRD撰写规范》《埋点需求规范》
3. 按精简版或完整版结构输出 Markdown
4. 正式提交草案时调用 `pm_submit_prd_draft`（需审批）
5. 每个目标指标必须能对应到 event 或 metrics 字段

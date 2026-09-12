---
name: demo-office-meeting-followup
description: 会议纪要整理与督办闭环跟进
trigger_keywords:
  - 会议纪要
  - 督办
  - 待办
  - 周会
version: 1.0.0
tool_budget:
  max_tool_rounds: 8
---

# 会议督办技能

1. 用 `office_list_meetings` / `office_get_meeting` 定位目标会议
2. 用 `office_list_action_items` 拉取待办，标注 `overdue` / `open` / `in_progress`
3. 对照 `kb_search`《会议纪要与督办管理办法》检查：是否有责任人、时限、证据
4. 输出结构：
   - 会议摘要
   - 督办看板（按优先级）
   - 逾期升级建议
   - 若用户要求起草纪要：按模板输出 Markdown，写操作调用 `office_submit_minutes_draft`（需审批）

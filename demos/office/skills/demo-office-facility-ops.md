---
name: demo-office-facility-ops
description: 会议室、用印与办公用品办理指引
trigger_keywords:
  - 会议室
  - 用印
  - 印章
  - 办公用品
  - 库存
version: 1.0.0
tool_budget:
  max_tool_rounds: 8
---

# 行政事务技能

1. 会议室：`office_list_rooms` → 冲突检查 → 给出可选房间
2. 用印：`office_list_seal_requests` + 《印章使用管理办法》说明审批链与状态
3. 物资：`office_list_supplies` 关注低于 reorder_level 的 SKU，给出补货建议
4. 输出简洁 checklist，区分「可自助查询」与「需人工审批」

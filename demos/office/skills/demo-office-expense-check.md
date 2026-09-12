---
name: demo-office-expense-check
description: 差旅报销合规预审与驳回原因说明
trigger_keywords:
  - 报销
  - 差旅
  - 费用
  - 发票
version: 1.0.0
tool_budget:
  max_tool_rounds: 8
---

# 报销预审技能

1. 用 `office_list_travel` / `office_get_expense_claim` 取行程与报销明细
2. 用 `kb_search` 对照《差旅与费用报销制度》限额与流程
3. 输出固定结构：
   - 合规结论：通过 / 有条件通过 / 建议驳回
   - 明细对照表（类型|金额|是否超标|依据）
   - 缺失材料清单
   - 给申请人的修改建议（3 条以内）
4. 禁止编造金额；全部数字来自工具

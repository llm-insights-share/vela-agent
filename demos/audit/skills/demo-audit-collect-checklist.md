---
name: demo-audit-collect-checklist
description: 经济责任审计资料收集清单与取数顺序
trigger_keywords:
  - 资料收集
  - 任职期间
  - 财务资料
  - OA档案
  - 立项
version: 1.0.0
tool_budget:
  max_tool_rounds: 8
---

# 资料收集技能

## 目标

围绕被审计人任职期间，系统取数并输出可核对的资料清单。

## 步骤

1. 使用 `audit_lookup_employee` 确认被审计人 `emp_id`、岗位、任职起止、所属 `org_id`
2. 使用 `audit_list_oa_docs` 拉取任职文件、述职、会议纪要、决策与廉政档案
3. 使用 `audit_query_gl` 拉取审计期间收入/成本/往来科目余额
4. 使用 `audit_query_related_party`、`audit_list_contracts`、`audit_list_capex` 补齐往来、合同、投资
5. 输出 Markdown 表格：**资料名 | 来源系统 | 关键字段/摘要 | 状态(已获取/缺口)**

## 红线

- 禁止估算未查询到的金额
- 所有数字必须标注工具返回来源

---
name: demo-audit-risk-identify
description: 对照法规识别经济责任审计风险点
trigger_keywords:
  - 风险识别
  - 审计风险
  - 异常
  - 关联交易
version: 1.0.0
tool_budget:
  max_tool_rounds: 6
---

# 风险识别技能

## 输出结构（每条风险）

1. **风险标题**
2. **等级**：高 / 中 / 低（依据内部审计准则）
3. **法规依据**：通过 `kb_search` 引用法规/指引原文要点
4. **证据字段**：来自资料收集结果或财务工具
5. **建议审计程序**

## 优先检查

- 关联方 + 账龄 >180 天
- Capex 实际/预算 ≥130% 或 `risk_flag=1`
- 重大合同缺 `approval_no`

禁止在无证据时下「已构成违规/应追责」的结论，只能写「风险关注 / 建议核实」。

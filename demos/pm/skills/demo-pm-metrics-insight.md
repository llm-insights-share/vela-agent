---
name: demo-pm-metrics-insight
description: 基于指标与漏斗输出数据洞察
trigger_keywords:
  - 指标
  - 漏斗
  - DAU
  - 留存
  - AARRR
  - 实验
version: 1.0.0
tool_budget:
  max_tool_rounds: 8
---

# 数据洞察技能

1. `pm_query_metrics` / `pm_query_funnel` / `pm_list_experiments` 取数
2. 禁止编造；对比周环比或实验组对照组
3. 输出结构：
   - 关键变化（↑↓）
   - 可能原因（假设，标注置信度）
   - 建议动作（映射 roadmap/backlog）
   - 需要补的埋点/实验

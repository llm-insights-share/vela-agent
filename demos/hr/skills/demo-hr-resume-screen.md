---
name: demo-hr-resume-screen
description: 对照 JD 做简历筛选与面试建议
trigger_keywords:
  - 简历筛选
  - 面试评估
  - 候选人
  - JD匹配
version: 1.0.0
tool_budget:
  max_tool_rounds: 6
---

# 简历筛选技能

1. 用 `kb_search` 拉取目标 JD 与候选人简历
2. 用 `hr_get_candidate` / `hr_list_open_requisitions` 核对招聘需求状态
3. 输出固定结构：
   - 匹配度（0-100）
   - 硬性要求对照表（必须项：满足/不满足/部分）
   - 风险点
   - 建议面试题 3 道
4. 引用《招聘管理规定》中的轮次与背调要求

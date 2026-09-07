# Demo B：HR 智能助手（SINGLE）

虚构企业：**星河控股**。Agent：`demo-hr-assistant`。

## 绑定资源

| 类型 | 名称 |
|------|------|
| Skill | `demo-hr-resume-screen`、`demo-hr-onboarding` |
| KB | `demo-hr-policies`、`demo-hr-jd-resume` |
| Tools | `hr_search_employees`、`hr_get_leave_balance`、`hr_list_open_requisitions`、`hr_get_candidate`、`hr_create_interview_note`（HITL） |
| DB | `demos/hr/data/demo_hr.db` |

## 数据字典

| 表 | 规模 / 要点 |
|----|-------------|
| `departments` | 研发中心 / 销售 / HR / 财务 |
| `employees` | 12 人；含试用期 `H012` |
| `leave_balances` | 研发中心 Top 年假：苏晴 15、何伟 14、周敏 12（as_of 2026-09-01） |
| `job_requisitions` | `REQ-BE` 后端高级工程师 open |
| `candidates` | 李娜（匹配较高）、王强（反例偏前端） |
| `interviews` | 李娜技术一面 planned |

敏感列：`employees.salary_band` 仅在 `include_compensation=true` 时返回。

## 验收话术

1. 「年假怎么算？试用期能不能请？」→ `kb_search` + 制度
2. 「李娜和后端高工 JD 匹配吗？」→ 简历技能 + JD/简历 KB，结构化输出
3. 「研发中心年假余额 Top3」→ `hr_get_leave_balance(department=研发中心)`
4. 「给李娜安排技术一面注意事项」→ candidate 工具 + 招聘规定轮次
5. （可选）写面试纪要 → outbox + 审批

## 实现说明

- `demo-hr-assistant` 使用 eager 工具加载；人事数字一律来自 `hr_*` local_python → SQLite
- 薪资带宽默认脱敏；写面试纪要走 outbox + HITL

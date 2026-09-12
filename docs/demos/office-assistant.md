# Demo C：日常办公助手（COMPOSITE）

虚构企业：**星河控股**。Coordinator：`demo-office-coordinator`。

制度文档骨架来自公开行政实践（会议督办闭环 SOP、差旅报销/Accountable Plan、印章专人保管与台账、会议室与物资申领规范），改写为星河内部制度摘要。

## Agent 拓扑

| 名称 | 类型 | 职责 |
|------|------|------|
| `demo-office-coordinator` | COMPOSITE | 分派 / 汇总 / 交付前 HITL |
| `demo-office-meeting` | SINGLE | 会议、纪要、督办 |
| `demo-office-expense` | SINGLE | 差旅与报销预审 |
| `demo-office-facility` | SINGLE | 会议室 / 用印 / 物资 |

## 绑定资源

| 类型 | 名称 |
|------|------|
| Skill | `demo-office-meeting-followup` / `demo-office-expense-check` / `demo-office-facility-ops` |
| KB | `demo-office-policies` / `demo-office-templates` |
| Tools | `office_list_meetings`、`office_get_meeting`、`office_list_action_items`、`office_list_travel`、`office_get_expense_claim`、`office_list_rooms`、`office_list_seal_requests`、`office_list_supplies`、`office_submit_minutes_draft`（HITL）、`office_submit_expense_review_note`（HITL） |
| DB | `demos/office/data/demo_office.db` |

## 数据字典（亮点）

| 表 | 预置亮点 |
|----|----------|
| `meetings` / `action_items` | `A003` 竞品一页纸 **overdue**（林悦） |
| `expense_claims` | `E001` 徐娜差旅 **4860.5**，含业务招待 1680（待预审） |
| `expense_claims` | `E005` 韩磊交通缺事由 → **rejected** |
| `seal_requests` | `S001` 合同章已批未用；`S003` 公章 pending |
| `supply_items` | `SP-A4` / `SP-TONER` / `SP-HDMI` **低于 reorder_level** |

## 验收话术

1. 「本周逾期督办有哪些？该升级给谁？」
2. 「预审徐娜报销单 E001，对照差旅制度给结论」
3. 「哪些办公用品该补货？有没有 pending 领用单？」
4. 「查一下待审批的用印」
5. （Coordinator 开场白）汇总逾期督办 + 预审 E001 + 低库存

## 参考来源（公开资料，非原文照搬）

- 会议纪要与督办闭环 SOP / 行政人员日常工作 SOP（会后 24–48h 出纪要、督办台账）
- Employee Handbook / Expense Reimbursement Policy 模板（事前申请、限额、发票、提交时限）
- 企业印章保管与用印台账规范

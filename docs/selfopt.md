# SelfOptGateway（Agent 自优化）

可选子系统：基于 TRACE/反馈归因 → 结构化提案 → 离线评测 → **在线轮询 A/B** → **用户决定是否正式上线**。

## 开关（默认关闭）

`backend/vela.yaml`：

```yaml
selfopt:
  enabled: false
  schedule_enabled: false
  ab_enabled: true
  reflect_model_service_id: ""   # 空 = 跟随目标 Agent 的 model_service_id
  agent_ids: []                  # 白名单；空 = 不针对任何 Agent
```

- API：`GET/PUT /api/v1/config/selfopt`
- 前端：系统配置 →「自优化」；Agent 管理菜单始终有「自优化」入口
- Agent 级否决：`agents.selfopt_enabled=False`
- **关闭时**：会话创建不查实验表；调度不跑；写 API 返回 `selfopt_disabled`

### 反思模型解析顺序

1. 本次 Job 传入的 `reflect_model_service_id`
2. 全局 `selfopt.reflect_model_service_id`
3. 目标 Agent 的 `model_service_id`

### 白名单

`enabled=true` 且 `agent_id ∈ agent_ids` 且未否决，才会跑 Job / 调度 / A/B 分流。白名单为空时即使开启总开关也不生效。

## 闭环

1. `POST /api/v1/selfopt/jobs` — 采集 → 反思 → 提案 → 离线评测（可带 `reflect_model_service_id`）
2. `GET /api/v1/selfopt/overview` — 闭环阶段与计数（Hub 看板）
3. `POST /api/v1/selfopt/proposals/{id}/start-ab` — 候选 Version + 轮询实验
4. `GET /api/v1/selfopt/ab/{id}/report` — 按 arm 对比
5. `POST .../promote` | `keep-control` | `abort`

### 离线评测

Job 会按 Agent 复用/创建 `SelfOpt-{name}-auto` Dataset：从窗口内历史对话抽取用户问句 + 最终回复（`AgentRun.summary`）作为回归用例，再对控制版 / 候选版各跑一次 `rerun` EvalJob 并 `compare_jobs`。未通过的提案保持 `drafted`，不可启动 A/B。

## 风险分级

| change_kind | Tier |
|-------------|------|
| retrieval_params | T0 |
| prompt_fewshot | T1 |
| tool_routing / skill_distill | T2 |
| guardrail / audit / observability / auth | FORBIDDEN |

## 后续扩展（Phase 2+）

- T0 自动进入待启动 A/B 队列
- treatment 劣化 Inbox 告警
- 百分比 / caller 哈希分流
- 技能蒸馏；可选微调

## 关键文件

- `backend/services/selfopt/`
- `backend/routes/selfopt.py`
- `frontend/src/views/selfopt/SelfOptHub.vue`

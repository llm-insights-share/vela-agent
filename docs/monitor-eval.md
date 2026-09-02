# Monitor & Eval

Trace 单一事实来源：监控（Observability & Tracing）与评测（Evaluation）共用 `agent_runs` + `agent_spans`。

## 数据模型

| 表 | 用途 |
|----|------|
| `agent_runs` | 一次用户消息→助手完成的根 Trace |
| `agent_spans` | chat / execute_tool / guard_decision 等 Span |
| `agent_scores` | 规则/Judge/用户评分（含 `data_type`） |
| `agent_feedback` | 👍👎 反馈（自动绑定 `run_id`） |
| `eval_datasets` / `eval_cases` / `eval_jobs` | 离线评测（含 `expected_output`、`run_mode`） |
| `eval_rule_evaluators` | 可配置规则 Evaluator |
| `eval_judge_evaluators` | LLM-as-Judge（采样率） |
| `annotation_queues` | 人工标注队列 |
| `monitor_alert_rules` | 可配置告警 + Webhook |

Eval 支持两种 Experiment 模式：
- **replay**（默认）：回放历史 Run 规则打分
- **rerun**：对 Item 输入真实重跑 Agent 后打分

## UI 入口

| 页面 | 路径 | 能力 |
|------|------|------|
| **监控** | `/monitor` | Traces / Observations / Sessions / Users / 告警设置；Trace 树 + I/O + 图谱 |
| **评测** | `/eval` | Datasets / Experiments / Scores / Evaluators / Annotation |
| Dataset 详情 | `/eval/datasets/:id` | Items（含 expected_output）、Experiments |

闭环：负反馈 → 监控 Trace → 加入 Dataset → Experiment 对比 → Evaluators 配置化 → CI gate。

## Monitor API（新增）

- `GET /monitor/observations` — 跨 Trace Span 浏览
- `GET /monitor/sessions` — Session 列表 + 成本
- `GET /monitor/users` — 按 caller 聚合用量/成本
- `GET /monitor/alert-rules` / POST / PATCH / DELETE — 告警规则 + Webhook
- `GET /monitor/saved-views` / POST — 保存筛选视图
- `GET /monitor/runs? q=` — 摘要关键词搜索
- `GET /monitor/summary` — 含 `timeseries`、`estimated_cost_usd`

反馈 `POST /monitor/feedback` 会在缺少 `run_id` 时按 `session_id + message_index` 自动解析。

## Eval API（新增）

- `GET/POST/PATCH/DELETE /eval/evaluators` — 规则 Evaluator
- `GET/POST/PATCH /eval/judge-evaluators` — LLM Judge
- `GET /eval/jobs/compare?job_a=&job_b=` — Item 级并排对比
- `POST /eval/datasets/{id}/import-feedback` — 负反馈批量入库
- `GET/POST /eval/annotation-queues` — 标注队列

Jobs 创建时可传 `run_mode: replay|rerun`、`evaluator_id`。

## CI

`scripts/run_eval_gate.sh` — 离线 Experiment 门禁，可与 GitHub Action 对接。

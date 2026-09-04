# Monitor & Eval

Trace 单一事实来源：监控（Observability & Tracing）与评测（Evaluation）共用 `agent_runs` + `agent_spans`。

运行时埋点遵循 [OpenInference](https://arize-ai.github.io/openinference/spec/)（基于 OpenTelemetry）：关键路径同步打 span，属性使用 `openinference.span.kind` 与 `llm.*` / `tool.*` 等语义键；结束后双写投影到 Postgres，供自研 Monitor/Eval UI 使用。

## 架构（OpenInference 双写）

```
AgentLoop (AGENT)
  ├── LLM spans          (model_provider / chat.completions)
  ├── TOOL spans         (真实工具执行)
  ├── GUARDRAIL spans    (before_tool / before_reply)
  └── RETRIEVER spans    (knowledge search)
        │
        ├─► BufferSpanProcessor ──► agent_runs / agent_spans (Monitor UI)
        └─► BatchSpanProcessor  ──► OTLP（可选，Phoenix / Collector）
```

配置见 `backend/vela.yaml`（也可在前端 **系统配置 → 工具配置 → 可观测性** 中修改并热加载）：

```yaml
observability:
  otel_enabled: true
  otlp_endpoint: ""   # 例如 http://127.0.0.1:6006 ；空则仅本地双写
  success_sample_rate: 1.0
```

API：`GET/PUT /api/v1/config/observability`。环境变量 `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SDK_DISABLED` 仍可覆盖运行时行为。

## 数据模型

| 表 | 用途 |
|----|------|
| `agent_runs` | 一次用户消息→助手完成的根 Trace |
| `agent_spans` | OpenInference 投影后的 Span（`kind` 列保留旧 UI 值，attrs 含 OI 键） |
| `agent_scores` | 规则/Judge/用户评分（含 `data_type`）；Judge 同时写入 `evaluations.*`） |
| `agent_feedback` | 👍👎 反馈（自动绑定 `run_id`） |
| `eval_datasets` / `eval_cases` / `eval_jobs` | 离线评测（含 `expected_output`、`run_mode`） |
| `eval_rule_evaluators` | 可配置规则 Evaluator |
| `eval_judge_evaluators` | LLM-as-Judge（采样率） |
| `annotation_queues` | 人工标注队列 |
| `monitor_alert_rules` | 可配置告警 + Webhook |

## OpenInference Kind ↔ UI kind

| OpenInference | `AgentSpan.kind`（兼容列） |
|---------------|---------------------------|
| `AGENT` | `agent` |
| `LLM` | `chat` |
| `TOOL` | `execute_tool` |
| `GUARDRAIL` | `guard_decision` |
| `RETRIEVER` | `retriever` |
| `EVALUATOR` | `evaluator` |
| `CHAIN` | `internal` |

Span `attrs_json` 始终包含 `openinference.span.kind`。LLM 示例键：`llm.model_name`、`llm.input_messages.0.message.role`、`llm.token_count.prompt`、`input.value` / `output.value`。

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

## Monitor API

- `GET /monitor/observations` — 跨 Trace Span 浏览
- `GET /monitor/sessions` — Session 列表 + 成本
- `GET /monitor/users` — 按 caller 聚合用量/成本
- `GET /monitor/alert-rules` / POST / PATCH / DELETE — 告警规则 + Webhook
- `GET /monitor/saved-views` / POST — 保存筛选视图
- `GET /monitor/runs? q=` — 摘要关键词搜索
- `GET /monitor/summary` — 含 `timeseries`、`estimated_cost_usd`
- `GET /monitor/runs/{id}/export/otel` — OpenInference JSON 导出（调试用；生产采集走 OTLP）

反馈 `POST /monitor/feedback` 会在缺少 `run_id` 时按 `session_id + message_index` 自动解析。

## Eval API

- `GET/POST/PATCH/DELETE /eval/evaluators` — 规则 Evaluator
- `GET/POST/PATCH /eval/judge-evaluators` — LLM Judge
- `GET /eval/jobs/compare?job_a=&job_b=` — Item 级并排对比
- `POST /eval/datasets/{id}/import-feedback` — 负反馈批量入库
- `GET/POST /eval/annotation-queues` — 标注队列

Jobs 创建时可传 `run_mode: replay|rerun`、`evaluator_id`。

## CI

`scripts/run_eval_gate.sh` — 离线 Experiment 门禁，可与 GitHub Action 对接。

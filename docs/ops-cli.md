# Vela CLI 与应用操作助手

## 概述

`vela` CLI 是平台管理命令行，对后端 `/api/v1/*` 做真实 HTTP 调用（不模拟）。内置智能体 `vela-ops-assistant` 通过 LOCAL_PYTHON 工具包装 CLI，完成智能体 / 工具 / 审批等操作。前端右下角指令按钮打开悬浮对话面板。

## 安装与入口

在 `backend/` 目录：

```bash
pip install -r requirements.txt   # 含 typer、rich
python -m vela_cli --help
```

可选 alias：

```bash
alias vela='cd /path/to/backend && python -m vela_cli'
```

环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `VELA_API_BASE` | `http://127.0.0.1:8000/api/v1` | API 根路径 |
| `VELA_API_TOKEN` | （空） | Bearer token；优先于本地凭证文件 |

登录后凭证写入 `~/.vela/credentials.json`。

## 鉴权

```bash
python -m vela_cli auth login -u <username> -p <password>
python -m vela_cli auth whoami
python -m vela_cli --json auth whoami
```

智能体调用 CLI 时，服务端会按会话 `caller_id` 签发 JWT，并注入 `VELA_API_TOKEN`，因此权限与当前登录用户一致。

## 常用命令

所有写操作都是真实 API；`--json` 放在根命令上，便于 Agent 解析：

```bash
python -m vela_cli --json agents list
python -m vela_cli --json agents get <agent_id>
python -m vela_cli --json agents create --name demo-x --model-service-id <ms_id>
python -m vela_cli --json agents publish <agent_id>
python -m vela_cli --json tools list
python -m vela_cli --json tools create --json-body '{"name":"...","tool_type":"local_python",...}'
python -m vela_cli --json approvals list --status PENDING
python -m vela_cli --json approvals approve <approval_id> --session-id <sid>
python -m vela_cli --json skills list
python -m vela_cli --json kb list
python -m vela_cli --json sessions list
python -m vela_cli --json models list
python -m vela_cli --json schedules list
python -m vela_cli --json connectors list
```

自保护：CLI 拒绝删除 / deprecate 名为 `vela-ops-assistant` 的智能体。

## 模型配置

在 Web 控制台 **系统配置 → 应用操作智能体** 卡片中，可为 `vela-ops-assistant` 选择供应商与模型服务。保存后通过 Agent 更新接口写回，已发布状态下会自动发版。

也可直接：

```bash
python -m vela_cli --json agents update <agent_id> --json-body '{"model_service_id":"<ms_id>","change_summary":"切换模型"}'
```

## 种子内置智能体

```bash
cd backend
python -m scripts.seed_demo
# 或启动时：VELA_SEED_DEMO=1
```

会幂等创建并发布 `vela-ops-assistant`，绑定 `services.ops_cli_tools` 中的 `vela_*` 工具。写类工具默认 `require_approval=True`。

## 前端悬浮面板

登录后任意业务页右下角出现 64×64 指令图标；点击打开与 AgentChat 同风格的悬浮对话（消息气泡、ExecutionStory、HITL 批准/拒绝、新对话）。若未 seed，面板会提示先运行 seed。

## 验收清单

1. `auth login` → `agents list` 返回真实数据  
2. Seed 后对话「列出所有工具」→ 工具调用 CLI → 列表与 UI 一致  
3. 「创建一个名为 X 的草稿智能体」→ HITL 批准后 Agent 列表可见  
4. FAB 在各业务页可见，面板可多轮对话  

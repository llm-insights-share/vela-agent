# Letta 记忆服务（独立进程）

Vela 的记忆引擎由本目录下的自托管 Letta 提供。Letta **不能**安装进 vela 主 venv（会与 sqlalchemy / pydantic 版本冲突）；此处使用独立虚拟环境。

## 依赖

1. vela 后端已启动（默认 `http://127.0.0.1:8000`），提供 `/llm-gateway/v1` 给 Letta 回连 chat / embeddings
2. Python **3.10–3.13**（已验证 `letta==0.16.8` 支持 3.13）

## 安装与启动

一键随 vela 启停（推荐）：

```bash
./start-all.sh    # 或 ./start.sh — 后端 → Letta → 前端
./stop-all.sh     # 或 ./stop.sh
./restart-all.sh  # 或 ./restart.sh
```

仅启动 Letta：

```bash
cd backend/letta
chmod +x start_letta.sh
./start_letta.sh
```

首次运行会创建 `.venv` 并 `pip install letta==0.16.8`（依赖较多，首次可能需数分钟）。`start_letta.sh` 还会：

- 安装软依赖：`asyncpg` / `aiosqlite` / `sqlite-vec` / `pg8000`
- 应用 `patches/` 下的 SQLite 兼容补丁（见下）

数据目录为 `.letta/`（可用 `LETTA_DIR` 覆盖），默认 SQLite 文件：`.letta/sqlite.db`。

默认监听：`http://127.0.0.1:8283`  
默认密码：`vela-letta-dev`（对应 `vela.yaml` → `memory.letta.password`）

## SQLite 补丁说明（重要）

Letta `0.16.8` 官方 `server/db.py` 实际按 Postgres 路径硬编码；本仓库在启动时自动打补丁，使本地默认可用 SQLite：

| 补丁 | 作用 |
|------|------|
| `patches/db_sqlite_compat.py` | 无 `LETTA_PG_URI` 时用 `sqlite+aiosqlite` + `create_all` |
| `patches/orm_base_sqlite.py` 等 | 修正 `server_default=func.now()` / `"now()"`，避免 DateTime 解析成字面量 `'now()'` |

升级 Letta 版本后若启动失败，请对照 `patches/` 重新适配，或改用 Postgres（见下）。

## 可选：Postgres + pgvector

```bash
export LETTA_PG_URI='postgresql+pg8000://letta:letta@localhost:5432/letta'
./start_letta.sh
```

需已创建数据库并启用 `CREATE EXTENSION vector;`。生产环境更推荐此路径。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `LETTA_DIR` | `./.letta` | 数据目录（SQLite） |
| `OPENAI_API_BASE` | `http://127.0.0.1:8000/llm-gateway/v1` | 回连 vela 网关 |
| `OPENAI_API_KEY` / `VELA_LLM_GATEWAY_TOKEN` | `vela-local-gateway` | 网关共享密钥 |
| `LETTA_SERVER_PASSWORD` | `vela-letta-dev` | Letta API Bearer |
| `LETTA_PORT` | `8283` | 服务端口 |
| `SECURE` | `true` | 启用密码保护 |
| `LETTA_PG_URI` | （空 → SQLite） | 设置后改用 Postgres |

## 版本说明

- 固定版本：`letta==0.16.8`（见 `start_letta.sh`）
- 本地默认 **SQLite**；官方对跨大版本迁移支持有限。升级前请备份 `.letta/`。

## 与 vela 的关系

- vela 侧只安装轻量 SDK：`letta-client`
- 记忆 agent 的 LLM / embedding 全部走 vela 网关：
  - chat → ModelService / ModelProvider
  - embeddings → 知识库同款 `BAAI/bge-large-zh-v1.5`（1024 维）
- `vela.yaml` 中 `memory.letta.enabled: false` 时，vela 全程不触碰 Letta（聊天降级为无长期记忆）

## 迁移存量记忆

```bash
cd backend
.venv/bin/python scripts/migrate_memory_to_letta.py
```

将 `memory_records` 中 `status=active` 的记录写入 Letta blocks / passages（可重复执行；按 `record:<id>` tag 去重）。

## 验收自检

```bash
# Letta 自身
curl -H "Authorization: Bearer vela-letta-dev" http://127.0.0.1:8283/v1/health/

# 经 vela（需登录 JWT）
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/memory/letta/status
# 期望：healthy=true, embedding_dim=1024, version=0.16.8
```

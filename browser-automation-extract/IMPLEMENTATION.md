# Hermes Agent 浏览器自动化 — 详细实现方案

> 抽取自 hermes-agent 仓库，覆盖架构、后端选择、会话生命周期、工具接口、安全策略与关键代码路径。

---

## 1. 目标与能力边界

Hermes 的 `browser` toolset 让 Agent 像人一样操作网页：打开页面、读可访问性树、点击、填表、滚动、按键、看截图、读控制台。

| 场景 | 推荐路径 |
|------|----------|
| 只需查信息 | `web_search` / `web_extract`（更快更便宜） |
| 需要点击、登录、填表、动态页 | `browser_*` 工具 |
| 要看验证码 / 复杂布局 | `browser_vision` |

**不支持：** 从浏览器下载文件到本地（文档明确限制）。

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  AIAgent / CLI / Gateway                                     │
│  handle_function_call("browser_navigate", ...)               │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  tools/registry.py  ← browser_tool.py 导入时 registry.register │
│  toolset = "browser", check_fn = check_browser_requirements  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  tools/browser_tool.py  （统一门面）                           │
│  1. 安全检查：密钥外泄 / SSRF / website_policy                 │
│  2. 后端路由：Camofox? → REST；否则 → agent-browser CLI        │
│  3. 会话：按 task_id 隔离，云厂商创建 CDP 会话                   │
└───────┬─────────────────────┬───────────────────┬───────────┘
        │                     │                   │
        ▼                     ▼                   ▼
┌───────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ Camofox REST  │   │ agent-browser   │   │ Cloud Providers  │
│ browser_camofox│   │ CLI (--json)    │   │ (返回 cdp_url)   │
│ CAMOFOX_URL   │   │ --cdp / --session│   │ Browserbase /    │
└───────────────┘   └─────────────────┘   │ Browser Use /    │
                                          │ Firecrawl        │
                                          └──────────────────┘
```

### 核心设计原则

1. **对模型统一接口**：无论后端是本地 Chromium、云浏览器还是 Camofox，Agent 看到的都是同一套 `browser_navigate / snapshot / click / type / ...`。
2. **可访问性树（a11y snapshot）优先**：页面用文本树 + `@e1` 等 ref，适合 LLM；像素操作靠 `browser_vision` 兜底。
3. **执行层统一走 `agent-browser` CLI**（Camofox 除外）：云模式用 `--cdp <ws>` 连远程浏览器；本地模式用 `--session <name>` 起 headless Chromium。
4. **按 task_id 隔离会话**：多任务 / 子 Agent 不会互相污染 cookies 与标签页。

---

## 3. 目录与文件清单

| 路径 | 作用 |
|------|------|
| `tools/browser_tool.py` | 主实现：会话、CLI 调用、10 个工具、注册、清理 |
| `tools/browser_camofox.py` | Camofox 本地反检测后端（REST，1:1 映射工具） |
| `tools/browser_camofox_state.py` | Profile 级持久化 identity（cookies/登录跨重启） |
| `tools/browser_providers/base.py` | `CloudBrowserProvider` ABC |
| `tools/browser_providers/browserbase.py` | Browserbase 云会话 |
| `tools/browser_providers/browser_use.py` | Browser Use / Nous managed 网关 |
| `tools/browser_providers/firecrawl.py` | Firecrawl 云会话 |
| `tools/tool_backend_helpers.py` | `normalize_browser_cloud_provider` 等 |
| `tools/url_safety.py` | SSRF：拦截私网/内网 URL |
| `tools/website_policy.py` | 站点黑白名单策略 |
| `tools/managed_tool_gateway.py` | Nous 托管工具网关解析（Browser Use） |
| `hermes_cli/tools_config.py` | `hermes tools` 交互配置浏览器后端 |
| `toolsets.py` | `browser` toolset 工具名列表 |
| `model_tools.py` | `_discover_tools()` 导入 `tools.browser_tool` |
| `cli.py` | `/browser connect\|disconnect\|status` CDP 附着 |
| `website/docs/user-guide/features/browser.md` | 用户文档 |

本 zip 已包含上述核心源码、测试与文档；`toolsets.py` / `model_tools.py` / `cli.py` 仅抽取相关片段到 `config-snippets/`。

---

## 4. 后端选择与优先级

`browser_tool._get_cloud_provider()` + Camofox / CDP 覆盖决定实际后端：

```
1. CAMOFOX_URL 已设置？
      → 全部操作走 Camofox REST（不需要 agent-browser）

2. BROWSER_CDP_URL 已设置？（/browser connect）
      → agent-browser --cdp <解析后的 websocket>
      → 不创建云会话、不启本地 Chromium

3. config.yaml: browser.cloud_provider
      - "local"     → 本地 agent-browser --session
      - "browserbase" / "browser-use" / "firecrawl"
                    → 对应 Provider.create_session() 拿 cdp_url

4. cloud_provider 未配置时自动探测：
      BrowserUse.is_configured() → 用 Browser Use
      否则 Browserbase.is_configured() → 用 Browserbase
      否则 → 本地模式
```

### 各后端凭证

| 后端 | 环境变量 / 配置 |
|------|-----------------|
| Local Chromium | `npm` 安装 `agent-browser`，再 `agent-browser install` |
| Browserbase | `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` |
| Browser Use | `BROWSER_USE_API_KEY`（或 Nous managed gateway） |
| Firecrawl | `FIRECRAWL_API_KEY`，可选 `FIRECRAWL_API_URL` / `FIRECRAWL_BROWSER_TTL` |
| Camofox | `CAMOFOX_URL=http://localhost:9377`；可选 `browser.camofox.managed_persistence` |
| Live Chrome CDP | CLI：`/browser connect [ws://host:port]` → 写 `BROWSER_CDP_URL` |

可选 Browserbase 调优：`BROWSERBASE_PROXIES`、`BROWSERBASE_ADVANCED_STEALTH`、`BROWSERBASE_KEEP_ALIVE`、`BROWSERBASE_SESSION_TIMEOUT`。

---

## 5. Cloud Provider 抽象

`CloudBrowserProvider`（`browser_providers/base.py`）约定：

```python
class CloudBrowserProvider(ABC):
    def provider_name(self) -> str: ...
    def is_configured(self) -> bool: ...          # 仅查 env，不联网
    def create_session(self, task_id: str) -> dict:
        # 必须返回:
        #   session_name  — agent-browser 本地会话名（兼容）
        #   bb_session_id — 厂商会话 ID（关闭用，命名历史遗留）
        #   cdp_url       — CDP WebSocket
        #   features      — 已启用特性
    def close_session(self, session_id: str) -> bool: ...
    def emergency_cleanup(self, session_id: str) -> None: ...
```

注册表（`browser_tool.py`）：

```python
_PROVIDER_REGISTRY = {
    "browserbase": BrowserbaseProvider,
    "browser-use": BrowserUseProvider,
    "firecrawl": FirecrawlProvider,
}
```

**Browserbase**：创建会话时可开 proxies / keepAlive / advanced stealth / 自定义 timeout；计划不支持时自动降级（先关 keepAlive，再关 proxies）。

**Browser Use**：支持直连 API Key，或通过 `managed_tool_gateway` 走 Nous 托管；创建会话有 idempotency key，处理 409 “already in progress”。

**Firecrawl**：`POST /v2/browser` 创建，`DELETE /v2/browser/{id}` 释放，返回 `cdpUrl`。

---

## 6. 会话生命周期

### 6.1 创建

`_get_session_info(task_id)`：

- 缓存命中 → 更新活跃时间，返回已有 session。
- 有 `BROWSER_CDP_URL` → `_create_cdp_session`（只存 cdp_url）。
- 有 cloud provider → `provider.create_session(task_id)`。
- 否则 → `_create_local_session`（仅 `session_name`，无 cdp_url）。

### 6.2 命令执行（非 Camofox）

`_run_browser_command(task_id, command, args)`：

1. 定位 `agent-browser` 可执行文件（PATH / Hermes 自带 Node / Homebrew node@N / `npx agent-browser` 回退）。
2. 取 session：有 `cdp_url` 则 `agent-browser --cdp <url> --json <cmd> ...`；否则 `--session <name>`。
3. **禁止**同时传 `--session` 与 `--cdp`（agent-browser ≥0.13 会忽略 CDP）。
4. 为每个 session 设独立 `AGENT_BROWSER_SOCKET_DIR`（避免并发冲突；macOS 用短路径避免 AF_UNIX 104 字节限制）。
5. stdout/stderr 写临时文件而非 pipe（后台 daemon 会继承 fd，pipe 会导致 `communicate` 挂死）。

典型映射：

| Hermes 工具 | agent-browser 命令 |
|-------------|-------------------|
| `browser_navigate` | `open <url>` |
| `browser_snapshot` | `snapshot` / `snapshot -c` |
| `browser_click` | `click @eN` |
| `browser_type` | `fill @eN <text>` |
| `browser_scroll` | `scroll up\|down` |
| `browser_back` | `back` |
| `browser_press` | `press <key>` |
| `browser_console` | `console` + `errors` |
| `browser_get_images` | `eval <js>` |
| `browser_vision` | `screenshot` + 辅助视觉模型 |

### 6.3 清理

- 后台线程约每 30s 扫一次，默认 **120s** 无活动则关闭（`BROWSER_INACTIVITY_TIMEOUT`）。
- `cleanup_browser(task_id)`：`close` + 云 `close_session`。
- `atexit` / 信号：`_emergency_cleanup_all_sessions`。
- 截图缓存 `~/.hermes/cache/screenshots/` 超 24h 清理；录像 `browser_recordings/` 超 72h 清理。

### 6.4 Camofox 会话

- HTTP 调 `CAMOFOX_URL` 的 REST（navigate/snapshot/click/...）。
- 默认每次随机 userId（登录不持久）。
- `browser.camofox.managed_persistence: true` 时，用 `browser_camofox_state.get_camofox_identity()` 生成 **profile 稳定** 的 `user_id`，服务端需配 `CAMOFOX_PROFILE_DIR`。
- headed 模式可从 `/health` 发现 `vncPort`，导航响应里带 VNC 链接供人眼观看。

---

## 7. Agent 可用工具（对模型暴露）

全部 `toolset="browser"`，`check_fn=check_browser_requirements`：

1. `browser_navigate(url)` — 首调初始化会话；成功时直接带 compact snapshot。
2. `browser_snapshot(full=false)` — 可交互元素 + ref；`full=true` 完整树；超约 8000 字符截断或 LLM 摘要。
3. `browser_click(ref)` — 如 `@e5`。
4. `browser_type(ref, text)` — 先清空再填。
5. `browser_scroll(direction)` — `up` / `down`。
6. `browser_back()`。
7. `browser_press(key)` — Enter / Tab / Escape / 方向键等。
8. `browser_get_images()`。
9. `browser_vision(question, annotate=false)` — 截图 + 多模态分析。
10. `browser_console(clear=false, expression=optional)`。

`check_browser_requirements()`：

- Camofox：只要有 `CAMOFOX_URL` 即 True。
- 其他：必须能找到 `agent-browser`；云模式还要 provider `is_configured()`。

---

## 8. 登录与站内搜索的典型编排

Agent 不单独实现「登录工具」，而是组合原子操作：

```
登录:
  navigate → snapshot → type(账号) → type(密码) → press(Enter) 或 click(提交)
  → snapshot 确认 → 必要时 vision 处理验证码

站内搜索:
  navigate → snapshot → type(搜索框, 关键词) → press(Enter)
  → snapshot(full) / scroll → 读取结果
```

有 Camofox managed persistence 或 `/browser connect` 到已登录 Chrome 时，可复用现有 cookies。

---

## 9. 安全机制

| 层 | 实现 | 说明 |
|----|------|------|
| 密钥外泄 | `agent.redact._PREFIX_RE` | URL 含 API key 形态则拦截 navigate |
| SSRF | `url_safety.is_safe_url` | 云后端拦截私网；本地/Camofox 默认跳过（本机已有终端权限） |
| 可配置放行 | `browser.allow_private_urls` | 云模式也允许内网 |
| 站点策略 | `website_policy.check_website_access` | 黑白名单 |
| 重定向 SSRF | navigate 后检查 `final_url`，危险则跳到 `about:blank` | |

---

## 10. CLI 实时 Chrome（`/browser connect`）

`cli.py::_handle_browser_command`：

- `connect`：探测 `ws://localhost:9222` 或用户传入地址；必要时自动拉起带 `--remote-debugging-port=9222` 的 Chrome；写入 `BROWSER_CDP_URL`。
- `disconnect`：清除 env，回到默认本地/云模式。
- `status`：显示当前 CDP。

`_resolve_cdp_override` 支持：完整 `ws://.../devtools/browser/...`、HTTP `/json/version` 发现、裸 `ws://host:port`。

---

## 11. 配置面

### config.yaml 示例

```yaml
browser:
  cloud_provider: local   # local | browserbase | browser-use | firecrawl
  command_timeout: 30
  inactivity timeout via env: BROWSER_INACTIVITY_TIMEOUT=120
  allow_private_urls: false
  record_sessions: false
  camofox:
    managed_persistence: false
```

### 启用 toolset

`hermes config set toolsets '["hermes-cli", "browser"]'`，或在平台启用的 toolsets 中包含 `browser`。

### 交互安装

`hermes tools` → Browser Automation → 选后端；`post_setup: agent_browser` 会尝试 `npm install` 装 `agent-browser`。

---

## 12. 数据流时序（云模式 navigate）

```
Agent
  │ browser_navigate(url)
  ▼
browser_tool
  │ 安全检查
  │ _get_session_info(task_id)
  │   └─ Provider.create_session → {cdp_url, bb_session_id, ...}
  │ _run_browser_command(..., "open", [url])
  │   └─ subprocess: agent-browser --cdp ws://... --json open url
  │ 可选：自动 snapshot -c
  ▼
JSON { success, title, url, snapshot, features, ... }
```

---

## 13. 测试覆盖（本包 `tests/`）

| 测试文件 | 关注点 |
|----------|--------|
| `test_browser_camofox.py` | Camofox 路由与 API |
| `test_browser_camofox_persistence.py` | managed persistence |
| `test_browser_camofox_state.py` | identity 稳定/隔离 |
| `test_browser_cdp_override.py` | CDP URL 解析 |
| `test_browser_cleanup.py` | 会话清理 |
| `test_browser_console.py` | console/errors |
| `test_browser_content_none_guard.py` | 空内容防护 |
| `test_browser_homebrew_paths.py` | macOS Node PATH |
| `test_browser_secret_exfil.py` | URL 密钥拦截 |
| `test_browser_ssrf_local.py` | SSRF / 本地后端跳过 |
| `test_managed_browserbase_and_modal.py` | managed 网关 |
| `test_cli_browser_connect.py` | `/browser connect` |

---

## 14. 依赖与运行时要求

- **Python**：`requests`、现有 Hermes 工具注册与辅助 LLM（`agent.auxiliary_client.call_llm` 用于 snapshot 摘要 / vision）。
- **Node**：`agent-browser` CLI + Chromium（本地/云 CDP 连接都需要 CLI，Camofox 除外）。
- **可选服务**：Browserbase / Browser Use / Firecrawl 账号，或自建 Camofox。

---

## 15. 局限与运维注意

1. 交互基于 a11y 树，不是像素坐标（复杂 Canvas/游戏页可能失效）。
2. 大页 snapshot 会被截断或摘要，可能丢细节。
3. 云会话有厂商超时与费用；本地 `/browser connect` 或 `cloud_provider: local` 可降本。
4. 无浏览器内文件下载能力。
5. macOS 注意 Unix socket 路径长度；代码已用 `_socket_safe_tmpdir()` 规避。
6. Prompt caching：不要在对话中途改 toolset / 系统提示；浏览器工具属于固定 toolset 注册。

---

## 16. 快速接入清单（落地）

1. `npm install`（或全局 `npm i -g agent-browser && agent-browser install`）。
2. 选后端：本地 / 填云密钥 / 起 Camofox 并设 `CAMOFOX_URL`。
3. 启用 `browser` toolset。
4. 验证：`python -m tools.browser_tool` 看 Mode / requirements。
5. 让 Agent：「打开 https://example.com，snapshot，在搜索框输入 xxx」。

---

## 17. 本压缩包结构

```
browser-automation-extract/
├── IMPLEMENTATION.md          ← 本文档
├── README.md                  ← 使用说明
├── docs/
│   ├── browser.md             ← 官方用户文档
│   ├── example_browser_tasks.jsonl
│   └── run_browser_tasks.sh
├── tools/
│   ├── browser_tool.py
│   ├── browser_camofox.py
│   ├── browser_camofox_state.py
│   ├── tool_backend_helpers.py
│   ├── url_safety.py
│   ├── website_policy.py
│   ├── managed_tool_gateway.py
│   └── browser_providers/
├── tests/
│   ├── tools/...
│   └── cli/test_cli_browser_connect.py
└── config-snippets/
    ├── toolsets_browser_refs.txt
    ├── model_tools_browser_refs.txt
    ├── tools_config_browser_section.py
    └── cli_browser_connect.py
```

这些文件在原仓库中位于相同相对路径（`tools/`、`tests/` 等），依赖 Hermes 其它模块（`tools.registry`、`hermes_constants`、`agent.auxiliary_client` 等），**不能单独作为可运行包**；本 zip 用于阅读、评审与二次移植参考。

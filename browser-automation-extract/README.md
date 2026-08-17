# Hermes Browser Automation Extract

本目录从 **hermes-agent** 抽取浏览器自动化相关源码、测试与实现方案文档。

## 先读

1. **[IMPLEMENTATION.md](./IMPLEMENTATION.md)** — 详细实现方案（架构、后端、会话、安全、登录编排）
2. **[docs/browser.md](./docs/browser.md)** — 官方用户指南（配置与工具说明）

## 内容

| 目录 | 说明 |
|------|------|
| `tools/` | 核心实现与云 Provider、SSRF/站点策略依赖 |
| `tests/` | 相关单测 |
| `config-snippets/` | 从 `toolsets.py` / `model_tools.py` / `cli.py` / `tools_config.py` 抽取的接入片段 |
| `docs/` | 用户文档与 datagen 示例 |

## 注意

- 代码依赖 Hermes 主工程其它模块，**不可独立运行**。
- 回填到完整仓库时保持原路径：`tools/browser_tool.py` 等。

抽取日期：2026-07-13

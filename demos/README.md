# Vela Demo 资产

两组可一键导入的领域 Demo：**经济责任审计（COMPOSITE）**、**人力助手（SINGLE）**。

## 快速开始

```bash
cd backend
# 需已存在至少一个 ModelService（可在 UI「模型服务」中创建并填 API Key）
# 可选：export VELA_DEMO_MODEL_SERVICE_ID=<uuid>
python -m scripts.seed_demo
```

启动时自动 seed（可选）：

```bash
export VELA_SEED_DEMO=1
# 再启动后端
```

## 目录

| 路径 | 说明 |
|------|------|
| `audit/` | 审计法规 KB、模板、技能、SQLite schema/seed、local_python 工具 |
| `hr/` | 人事制度/JD/简历 KB、技能、HRIS mock、工具 |
| `*/outbox/` | HITL 写工具输出目录（gitignore） |
| `../docs/demos/` | 场景说明、数据字典、验收话术 |
| `../backend/scripts/seed_demo.py` | 幂等导入 |
| `../backend/demo_tools/` | 运行时可 import 的工具桥接 |

## 推荐开场白

**审计 Coordinator（`demo-audit-coordinator`）**

> 请对华北分公司总经理张伟开展 2024 年度经济责任审计立项：收集任职期间经营与财务资料，识别主要风险点，并起草立项说明书草案。

**HR 助手（`demo-hr-assistant`）**

> 帮我看看候选人李娜是否适合后端高级工程师，并对照招聘与试用期制度给出面试建议；另外查一下研发中心剩余年假最多的 3 人。

详细说明见：

- [docs/demos/audit-economic-responsibility.md](../docs/demos/audit-economic-responsibility.md)
- [docs/demos/hr-assistant.md](../docs/demos/hr-assistant.md)

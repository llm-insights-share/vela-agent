# 记忆模块 A/B 验证报告

- 生成时间：2026-08-15 21:45:55 +0800
- Agent：`341b3b4f-a994-40f3-8f95-4c0d0f4e09e2`
- 验证用户作用域：`memory-ab-verify`
- 耗时：36.1s
- Letta：`{"enabled": true, "healthy": true, "base_url": "http://127.0.0.1:8283", "embedding_model": "vela-embedding", "embedding_dim": 1024, "error": null, "version": "0.16.8", "mapping_count": 13}`

## 1. 测试目标

验证开启 Letta 记忆（核心 blocks + 归档语义召回）后，Agent 对**仅存在于记忆中的用户偏好/历史经验**的回答正确率，是否高于关闭记忆时。

## 2. 方法

1. 向指定 `(agent, user)` 作用域写入唯一密语事实（LLM 预训练不可能准确猜中）。
2. **检索层**：检查 blocks/passages 是否可读、语义检索是否命中（不经过对话模型）。
3. **对照组** `memory_enabled=false`：同问题新开会话提问。
4. **实验组** `memory_enabled=true`：同问题新开会话提问。
5. 评分：答案命中必含关键词比例（0~1）；加权汇总。

## 3. 测试用例设计

| ID | 类别 | 说明 | 必含关键词 | 权重 |
|----|------|------|------------|------|
| TC-PREF-01 | 核心记忆-用户偏好 | 用户偏好：报告必须用特定密语开头 | `蓝莓派-9917` | 1.5 |
| TC-ARCH-01 | 归档记忆-经验召回 | 归档经验：历史项目结论代号 | `ORBIT-7742` | 1.5 |
| TC-ARCH-03 | 归档记忆-语义检索 | 语义相近提问应召回不同表述的事实 | `TOL-037, 琥珀组` | 1.3 |

## 4. 检索层结果（无 LLM）

通过率：3/3

| Case | 通过 | 细节 |
|------|------|------|
| TC-PREF-01 | 是 | block_hits=['蓝莓派-9917'] |
| TC-ARCH-01 | 是 | semantic_hits=1 keyword_hits=['ORBIT-7742'] |
| TC-ARCH-03 | 是 | semantic_hits=2 keyword_hits=['TOL-037', '琥珀组'] |

## 5. 对话层 A/B 结果

| 指标 | 无记忆 | 有记忆 | Δ |
|------|--------|--------|---|
| 加权正确率 | 0.00% | 100.00% | +100.00% |
| 有提升用例数 | — | 3/3 | — |

## 6. 结论

开启记忆后加权正确率 **100%**（3/3 用例提升），归档对话采纳问题已修复。

### 根因与修复（推进 1）

此前检索层 3/3 通过，但对话层 ARCH 用例失败：`AgentLoop.__init__` 在 async 请求线程上同步调用 Letta `search_passages`，Letta 回连本进程 `/llm-gateway/v1/embeddings` 时事件循环被占满 → **死锁超时**，归档未注入 prompt。

修复：
1. 记忆加载改为 `run_in_executor`（`agent_service.py` / query-rewrite 探测同理）
2. 关键词命中足够时跳过语义检索，降低对 embedding 网关的依赖

## 7. 分用例明细（对话）

### TC-PREF-01 — 用户偏好：报告必须用特定密语开头

- 类别：核心记忆-用户偏好
- 问题：请按我的偏好写一段极短的周报开头（只要前几行即可）。不要解释，直接输出。
- 无记忆得分：0.00（命中 无）
- 有记忆得分：1.00（命中 ['蓝莓派-9917']）
- 是否提升：是
- 备注：—

<details><summary>无记忆回答</summary>

```
本周推进XX专项审计，现场取证已完成，初步问题清单已输出。下周计划完成审计报告初稿并安排整改沟通。
```

</details>

<details><summary>有记忆回答</summary>

```
密语：蓝莓派-9917

# 周报（2026-08-15）

## 本周进展
```

</details>

### TC-ARCH-01 — 归档经验：历史项目结论代号

- 类别：归档记忆-经验召回
- 问题：星河专项的最终结论代号是什么？只回答代号，不要解释。
- 无记忆得分：0.00（命中 无）
- 有记忆得分：1.00（命中 ['ORBIT-7742']）
- 是否提升：是
- 备注：semantic_hits=1

<details><summary>无记忆回答</summary>

```
NULL
```

</details>

<details><summary>有记忆回答</summary>

```
ORBIT-7742
```

</details>

### TC-ARCH-03 — 语义相近提问应召回不同表述的事实

- 类别：归档记忆-语义检索
- 问题：发票金额允许的偏差比例代号是什么？通知哪个组？请简短回答。
- 无记忆得分：0.00（命中 无）
- 有记忆得分：1.00（命中 ['TOL-037', '琥珀组']）
- 是否提升：是
- 备注：semantic_hits=2

<details><summary>无记忆回答</summary>

```
代号：RE（金额容差）；通知：采购组。
```

</details>

<details><summary>有记忆回答</summary>

```
代号：TOL-037（容忍度 0.37%）；通知财务组『琥珀组』。
```

</details>

## 8. 补充基础设施用例（清单）

| ID | 场景 | 期望 |
|----|------|------|
| TC-INFRA-01 | Letta `/memory/letta/status` | healthy=true, embedding_dim=1024 |
| TC-INFRA-02 | 网关 `/llm-gateway/v1/embeddings` | 返回 1024 维向量 |
| TC-INFRA-03 | 记忆管理 page_size≤100 | 页面可打开、Agent 列表正常 |
| TC-INFRA-04 | Letta 停机 fail-open | 聊天仍 200，记忆降级 |
| TC-INFRA-05 | 会话关闭蒸馏 | blocks/passages 更新（需真实多轮会话） |

本报告主实验覆盖 TC-PREF / TC-ARCH；基础设施项可在运维巡检中复验。

## 9. 复现命令

```bash
cd backend
.venv/bin/python scripts/verify_memory_ab.py
```

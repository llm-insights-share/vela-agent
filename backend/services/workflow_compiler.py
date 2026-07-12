"""
WF: 工作流编排图编译与校验
WF-IMP-01~05
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from models import Agent, AgentStatus, AgentType, ModelService, ModelServiceStatus


VALID_NODE_TYPES = {
    "start", "llm", "tool", "condition", "hitl", "cron", "subgraph", "end", "screenpilot"
}


@dataclass
class CompiledWorkflow:
    """编译后的工作流图"""
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    adjacency: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    start_node_id: Optional[str] = None
    end_node_ids: List[str] = field(default_factory=list)
    cron_node_ids: List[str] = field(default_factory=list)
    hitl_node_ids: List[str] = field(default_factory=list)


class WorkflowCompiler:

    @staticmethod
    def validate(db: Session, definition: Dict[str, Any]) -> Dict[str, Any]:
        errors: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []

        nodes = definition.get("nodes") or []
        edges = definition.get("edges") or []

        if not nodes:
            errors.append({"field": "workflow_definition", "message": "工作流未定义任何节点"})
            return {"errors": errors, "warnings": warnings, "passed": False}

        node_map: Dict[str, Dict[str, Any]] = {}
        for n in nodes:
            nid = n.get("id")
            if not nid:
                errors.append({"field": "nodes", "message": "存在缺少 id 的节点"})
                continue
            if nid in node_map:
                errors.append({"field": "nodes", "message": f"节点 ID 重复: {nid}"})
            ntype = n.get("type")
            if ntype not in VALID_NODE_TYPES:
                errors.append({"field": "nodes", "message": f"未知节点类型: {ntype} ({nid})"})
            node_map[nid] = n

        start_nodes = [nid for nid, n in node_map.items() if n.get("type") == "start"]
        if len(start_nodes) == 0:
            errors.append({"field": "nodes", "message": "工作流必须包含一个 start 节点"})
        elif len(start_nodes) > 1:
            errors.append({"field": "nodes", "message": "工作流只能有一个 start 节点"})

        end_nodes = [nid for nid, n in node_map.items() if n.get("type") == "end"]
        if not end_nodes:
            warnings.append({"field": "nodes", "message": "建议添加 end 节点作为流程出口"})

        # WF-IMP-02: 连通性校验
        if start_nodes and not errors:
            reachable = WorkflowCompiler._bfs_reachable(start_nodes[0], edges)
            for nid in node_map:
                if nid not in reachable:
                    errors.append({
                        "field": "nodes",
                        "message": f"孤立节点不可达: {nid} ({node_map[nid].get('type')})",
                    })

        # WF-IMP-03: 环路死锁检测
        if start_nodes and not errors:
            cycle_warnings = WorkflowCompiler._detect_cycle_warnings(
                start_nodes[0], node_map, edges
            )
            warnings.extend(cycle_warnings)

        # WF-IMP-04: Cron 安全校验
        cron_nodes = [nid for nid, n in node_map.items() if n.get("type") == "cron"]
        hitl_nodes = [nid for nid, n in node_map.items() if n.get("type") == "hitl"]
        for cron_id in cron_nodes:
            if not hitl_nodes:
                errors.append({
                    "field": "nodes",
                    "message": f"Cron 节点 {cron_id} 存在但工作流无 HITL 节点（WF-CFG-12 安全红线）",
                })
            else:
                cron_reachable = WorkflowCompiler._bfs_reachable(cron_id, edges)
                if not any(h in cron_reachable for h in hitl_nodes):
                    errors.append({
                        "field": "nodes",
                        "message": f"Cron 节点 {cron_id} 无法到达任何 HITL 审批节点",
                    })

        # WF-IMP-05: 节点级模型路由校验
        for nid, n in node_map.items():
            ntype = n.get("type")
            data = n.get("data") or {}
            if ntype == "llm":
                ms_id = data.get("model_service_id")
                if not ms_id:
                    warnings.append({
                        "field": "nodes",
                        "message": f"LLM 节点 {nid} 未配置 model_service_id，将使用 Agent 默认模型",
                    })
                else:
                    ms = db.query(ModelService).filter(
                        ModelService.model_service_id == ms_id
                    ).first()
                    if not ms:
                        errors.append({
                            "field": "nodes",
                            "message": f"LLM 节点 {nid} 的模型服务不存在: {ms_id}",
                        })
                    elif ms.status != ModelServiceStatus.ACTIVE:
                        errors.append({
                            "field": "nodes",
                            "message": f"LLM 节点 {nid} 的模型服务未激活: {ms_id}",
                        })
            elif ntype == "subgraph":
                child_id = data.get("child_agent_id")
                if not child_id:
                    errors.append({
                        "field": "nodes",
                        "message": f"子图节点 {nid} 未绑定单体 Agent",
                    })
                else:
                    child = db.query(Agent).filter(Agent.agent_id == child_id).first()
                    if not child:
                        errors.append({
                            "field": "nodes",
                            "message": f"子图节点 {nid} 引用的 Agent 不存在: {child_id}",
                        })
                    elif child.agent_type != AgentType.SINGLE:
                        errors.append({
                            "field": "nodes",
                            "message": f"子图节点 {nid} 只能引用 SINGLE 类型 Agent",
                        })
                    elif child.status != AgentStatus.PUBLISHED:
                        warnings.append({
                            "field": "nodes",
                            "message": f"子图节点 {nid} 引用的 Agent 未发布: {child.name}",
                        })
            elif ntype == "tool":
                if not data.get("tool_id") and not data.get("tool_name"):
                    errors.append({
                        "field": "nodes",
                        "message": f"工具节点 {nid} 未配置 tool_id 或 tool_name",
                    })
            elif ntype == "condition":
                if not data.get("expression"):
                    errors.append({
                        "field": "nodes",
                        "message": f"条件节点 {nid} 未配置 expression",
                    })
            elif ntype == "screenpilot":
                if not data.get("system_id") and not data.get("skill_id"):
                    errors.append({
                        "field": "nodes",
                        "message": f"ScreenPilot 节点 {nid} 需配置 system_id 或 skill_id",
                    })
                op = (data.get("operation") or "navigate").lower()
                if op not in ("navigate", "observe", "replay", "extract", "act", "run_task"):
                    errors.append({
                        "field": "nodes",
                        "message": f"ScreenPilot 节点 {nid} 未知 operation: {op}",
                    })

        passed = len(errors) == 0
        return {"errors": errors, "warnings": warnings, "passed": passed}

    @staticmethod
    def compile(definition: Dict[str, Any]) -> CompiledWorkflow:
        """WF-IMP-01: 将画布定义编译为可执行结构"""
        nodes_list = definition.get("nodes") or []
        edges = definition.get("edges") or []

        nodes: Dict[str, Dict[str, Any]] = {}
        for n in nodes_list:
            nid = n.get("id")
            if nid:
                nodes[nid] = n

        adjacency: Dict[str, List[Dict[str, Any]]] = {nid: [] for nid in nodes}
        for e in edges:
            src = e.get("source")
            if src and src in adjacency:
                adjacency[src].append(e)

        start_node_id = next(
            (nid for nid, n in nodes.items() if n.get("type") == "start"), None
        )
        end_node_ids = [nid for nid, n in nodes.items() if n.get("type") == "end"]
        cron_node_ids = [nid for nid, n in nodes.items() if n.get("type") == "cron"]
        hitl_node_ids = [nid for nid, n in nodes.items() if n.get("type") == "hitl"]

        return CompiledWorkflow(
            nodes=nodes,
            edges=edges,
            adjacency=adjacency,
            start_node_id=start_node_id,
            end_node_ids=end_node_ids,
            cron_node_ids=cron_node_ids,
            hitl_node_ids=hitl_node_ids,
        )

    @staticmethod
    def _bfs_reachable(start_id: str, edges: List[Dict[str, Any]]) -> Set[str]:
        adj: Dict[str, List[str]] = {}
        for e in edges:
            src, tgt = e.get("source"), e.get("target")
            if src and tgt:
                adj.setdefault(src, []).append(tgt)

        visited: Set[str] = set()
        queue = [start_id]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            for nxt in adj.get(cur, []):
                if nxt not in visited:
                    queue.append(nxt)
        return visited

    @staticmethod
    def _detect_cycle_warnings(
        start_id: str,
        node_map: Dict[str, Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """WF-IMP-03: 检测可能无退出条件的环路"""
        warnings: List[Dict[str, str]] = []
        adj: Dict[str, List[str]] = {}
        for e in edges:
            src, tgt = e.get("source"), e.get("target")
            if src and tgt:
                adj.setdefault(src, []).append(tgt)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in node_map}
        cycle_nodes: Set[str] = set()

        def dfs(u: str):
            color[u] = GRAY
            for v in adj.get(u, []):
                if v not in color:
                    continue
                if color[v] == GRAY:
                    cycle_nodes.add(u)
                    cycle_nodes.add(v)
                elif color[v] == WHITE:
                    dfs(v)
            color[u] = BLACK

        if start_id in color:
            dfs(start_id)

        for nid in cycle_nodes:
            ntype = node_map.get(nid, {}).get("type")
            if ntype == "condition":
                out_edges = [e for e in edges if e.get("source") == nid]
                handles = {e.get("sourceHandle", "default") for e in out_edges}
                if "true" not in handles or "false" not in handles:
                    warnings.append({
                        "field": "nodes",
                        "message": f"条件节点 {nid} 在环路中且缺少 true/false 双出口，可能死锁",
                    })
            elif ntype not in ("end", "hitl"):
                warnings.append({
                    "field": "nodes",
                    "message": f"节点 {nid} ({ntype}) 可能参与无退出环路",
                })

        return warnings

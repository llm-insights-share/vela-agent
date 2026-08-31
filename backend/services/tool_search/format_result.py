"""Format tool_search results for LLM consumption."""
from __future__ import annotations

from typing import List

from services.tool_search.catalog import ToolCatalogEntry


def format_tool_search_result(
    query: str,
    matches: List[ToolCatalogEntry],
    activated: List[str],
    *,
    already_loaded: List[str],
    max_loaded: int,
) -> str:
    lines = ["## 工具搜索结果"]
    lines.append(f"- 查询: {query}")
    if not matches:
        lines.append("\n未找到匹配工具。请换关键词，或使用 execute_code 完成任务。")
        return "\n".join(lines)

    lines.append(f"\n### 命中 ({len(matches)})")
    for i, e in enumerate(matches, 1):
        block = [f"#### {i}. `{e.name}`"]
        if e.display_name and e.display_name != e.name:
            block.append(f"- 显示名: {e.display_name}")
        if e.description:
            block.append(f"- 说明: {e.description[:300]}")
        if e.tool_type:
            block.append(f"- 类型: {e.tool_type}")
        if e.mcp_server_name:
            block.append(f"- MCP: {e.mcp_server_name}")
        if e.parameters_summary:
            block.append(f"- 参数: {e.parameters_summary}")
        lines.append("\n".join(block))

    if activated:
        lines.append(f"\n### 已激活\n{', '.join(f'`{n}`' for n in activated)}")
    elif already_loaded:
        lines.append(f"\n### 会话已加载\n{', '.join(f'`{n}`' for n in already_loaded)}")

    if len(already_loaded) >= max_loaded:
        lines.append(
            f"\n> 已达本会话加载上限 ({max_loaded})。如需更换工具，请完成当前任务或开启新对话。"
        )
    else:
        lines.append("\n> 已激活的工具在下一轮 LLM 调用中可用；请直接调用工具名。")

    return "\n".join(lines)

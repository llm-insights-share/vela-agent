"""Tool catalog for deferred loading / tool_search."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional, Set

from services.builtin_tools import BuiltinTool


@dataclass
class ToolCatalogEntry:
    name: str
    display_name: str
    description: str
    tool_type: str
    mcp_server_name: str = ""
    parameters_summary: str = ""
    is_builtin: bool = False
    tool_id: Optional[str] = None

    def document_text(self) -> str:
        parts = [
            self.name,
            self.display_name or "",
            self.description or "",
            self.tool_type or "",
            self.mcp_server_name or "",
            self.parameters_summary or "",
        ]
        return " ".join(p for p in parts if p).strip()


def _summarize_parameters_schema(schema: Any, limit: int = 400) -> str:
    if not schema or not isinstance(schema, dict):
        return ""
    try:
        props = schema.get("properties") or {}
        if not isinstance(props, dict):
            return ""
        keys = list(props.keys())[:12]
        required = schema.get("required") or []
        if isinstance(required, list):
            req = [k for k in required if k in keys]
            if req:
                return f"params: {', '.join(keys)}; required: {', '.join(req)}"
        return f"params: {', '.join(keys)}"
    except Exception:
        text = json.dumps(schema, ensure_ascii=False)
        return text[:limit]


def build_catalog_from_tools(tools: List[Any]) -> "ToolCatalog":
    entries: List[ToolCatalogEntry] = []
    for t in tools or []:
        if isinstance(t, BuiltinTool):
            entries.append(
                ToolCatalogEntry(
                    name=t.name,
                    display_name=t.name,
                    description=(t.description or "")[:2000],
                    tool_type="builtin",
                    parameters_summary=_summarize_parameters_schema(t.parameters),
                    is_builtin=True,
                )
            )
            continue
        name = getattr(t, "name", "") or ""
        if not name:
            continue
        mcp_name = ""
        server = getattr(t, "mcp_server", None)
        if server is not None:
            mcp_name = getattr(server, "display_name", "") or getattr(server, "name", "") or ""
        tool_type = getattr(getattr(t, "tool_type", None), "value", None) or str(getattr(t, "tool_type", "") or "")
        entries.append(
            ToolCatalogEntry(
                name=name,
                display_name=getattr(t, "display_name", "") or name,
                description=(getattr(t, "description", "") or "")[:2000],
                tool_type=str(tool_type).lower(),
                mcp_server_name=mcp_name,
                parameters_summary=_summarize_parameters_schema(getattr(t, "parameters_schema", None)),
                is_builtin=False,
                tool_id=getattr(t, "tool_id", None),
            )
        )
    return ToolCatalog(entries)


class ToolCatalog:
    def __init__(self, entries: List[ToolCatalogEntry]):
        self.entries = entries
        self._by_name = {e.name: e for e in entries if e.name}

    def all_names(self) -> Set[str]:
        return set(self._by_name.keys())

    def get(self, name: str) -> Optional[ToolCatalogEntry]:
        return self._by_name.get(name)

    def deferred_entries(self, core_names: Set[str]) -> List[ToolCatalogEntry]:
        """User/MCP tools eligible for tool_search (excludes platform builtins)."""
        return [
            e
            for e in self.entries
            if e.name not in core_names and not e.is_builtin and e.name != "tool_search"
        ]

"""Session-scoped loaded tool names for deferred mode."""
from __future__ import annotations

from typing import Any, List, Set


class SessionToolRegistry:
    def __init__(
        self,
        session: Any,
        *,
        max_loaded: int = 12,
        initial: Set[str] | None = None,
    ):
        self.session = session
        self.max_loaded = max(1, max_loaded)
        self.loaded: Set[str] = set(initial or [])

    @classmethod
    def from_session(cls, session: Any, *, max_loaded: int = 12) -> "SessionToolRegistry":
        pending = dict(getattr(session, "pending_context", None) or {})
        raw = pending.get("loaded_tool_names") or []
        initial = {str(n) for n in raw if n}
        return cls(session, max_loaded=max_loaded, initial=initial)

    def activate(self, names: List[str], *, core_names: Set[str]) -> List[str]:
        added: List[str] = []
        for name in names:
            n = (name or "").strip()
            if not n or n in core_names or n in self.loaded:
                continue
            if len(self.loaded) >= self.max_loaded:
                break
            self.loaded.add(n)
            added.append(n)
        if added:
            self._persist()
        return added

    def is_loaded(self, name: str, *, core_names: Set[str]) -> bool:
        n = (name or "").strip()
        if not n:
            return False
        if n in core_names:
            return True
        return n in self.loaded

    def loaded_list(self) -> List[str]:
        return sorted(self.loaded)

    def tool_search_calls(self) -> int:
        pending = dict(getattr(self.session, "pending_context", None) or {})
        return int(pending.get("tool_search_calls") or 0)

    def record_search_call(self) -> None:
        self._persist(search_delta=1)

    def _persist(self, search_delta: int = 0) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        pending = dict(getattr(self.session, "pending_context", None) or {})
        pending["loaded_tool_names"] = self.loaded_list()
        if search_delta:
            pending["tool_search_calls"] = int(pending.get("tool_search_calls") or 0) + search_delta
        self.session.pending_context = pending
        flag_modified(self.session, "pending_context")

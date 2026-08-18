"""Session-level workspace for Code Interpreter."""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.code_exec.config import WORKSPACES_ROOT, load_code_exec_config

ARTIFACT_EXT_MAP = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".csv": "table",
    ".tsv": "table",
    ".xlsx": "table",
    ".xls": "table",
    ".json": "data",
    ".xml": "data",
    ".yaml": "data",
    ".yml": "data",
    ".py": "code",
    ".js": "code",
    ".html": "code",
    ".md": "code",
    ".txt": "code",
    ".pdf": "other",
    ".zip": "other",
}

SKIP_DIRS = {".state", "__pycache__", ".git", ".matplotlib", ".tmp"}


class SessionWorkspace:
    """Per-session working directory with artifact tracking."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.root = Path(WORKSPACES_ROOT) / session_id
        self.outputs = self.root / "outputs"
        self.state_dir = self.root / ".state"
        self.scripts = self.root / "scripts"
        self._cfg = load_code_exec_config()

    def ensure(self) -> Path:
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.scripts.mkdir(parents=True, exist_ok=True)
        return self.root

    @classmethod
    def from_output_dir(cls, output_dir: str) -> "SessionWorkspace":
        """Derive session_id from backend/data/outputs/{session_id}."""
        session_id = os.path.basename(os.path.normpath(output_dir))
        return cls(session_id)

    def snapshot(self) -> Dict[str, Tuple[float, int]]:
        """Return {relative_path: (mtime, size)} for all tracked files."""
        self.ensure()
        snap: Dict[str, Tuple[float, int]] = {}
        for base in (self.root, self.outputs):
            if not base.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fn in filenames:
                    if fn.startswith(".") and fn.endswith(".pkl"):
                        continue
                    full = Path(dirpath) / fn
                    try:
                        st = full.stat()
                        rel = str(full.relative_to(self.root))
                        snap[rel] = (st.st_mtime, st.st_size)
                    except OSError:
                        pass
        return snap

    def sweep_artifacts(
        self,
        before: Dict[str, Tuple[float, int]],
        after: Dict[str, Tuple[float, int]],
    ) -> List[Dict[str, Any]]:
        """Detect new/changed files and classify as artifacts."""
        max_bytes = self._cfg.max_artifact_mb * 1024 * 1024
        artifacts: List[Dict[str, Any]] = []

        for rel, (mtime, size) in after.items():
            prev = before.get(rel)
            if prev is not None and prev == (mtime, size):
                continue
            if rel.startswith(".state/") or rel.startswith("scripts/"):
                continue
            if rel.startswith(".matplotlib/") or rel.startswith(".tmp/"):
                continue

            full = self.root / rel
            if not full.is_file():
                continue

            if size > max_bytes:
                artifacts.append({
                    "path": str(full),
                    "name": full.name,
                    "relative": rel,
                    "kind": "skipped",
                    "size": size,
                    "warning": f"超过 {self._cfg.max_artifact_mb}MB 限制，未收集",
                })
                continue

            ext = full.suffix.lower()
            kind = ARTIFACT_EXT_MAP.get(ext, "other")
            artifacts.append({
                "path": str(full),
                "name": full.name,
                "relative": rel,
                "kind": kind,
                "size": size,
                "ext": ext,
            })

        return artifacts

    def reset_state(self) -> None:
        """Clear persisted variable state."""
        state_file = self.state_dir / "globals.pkl"
        if state_file.exists():
            state_file.unlink()

    def list_files(self, subpath: str = "") -> List[Dict[str, Any]]:
        """List workspace files for list_workspace tool."""
        self.ensure()
        target = self.root / subpath if subpath else self.root
        if not target.exists():
            return []

        resolved = target.resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise ValueError("路径不在工作区内")

        items: List[Dict[str, Any]] = []
        if target.is_file():
            st = target.stat()
            return [{
                "path": str(target.relative_to(self.root)),
                "size": st.st_size,
                "type": "file",
            }]

        for entry in sorted(target.iterdir()):
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            if entry.is_dir():
                items.append({"path": str(entry.relative_to(self.root)), "type": "dir"})
            elif entry.is_file():
                st = entry.stat()
                items.append({
                    "path": str(entry.relative_to(self.root)),
                    "size": st.st_size,
                    "type": "file",
                })
        return items

    def next_script_path(self, language: str = "python") -> Path:
        self.ensure()
        ext = ".py" if language == "python" else ".js"
        existing = list(self.scripts.glob(f"run_*{ext}"))
        idx = len(existing) + 1
        return self.scripts / f"run_{idx:04d}{ext}"

    def copy_artifact_to_output(self, artifact_path: str, output_dir: str) -> Optional[str]:
        """Copy artifact into session output dir for download API."""
        src = Path(artifact_path)
        if not src.is_file():
            return None
        os.makedirs(output_dir, exist_ok=True)
        dest = Path(output_dir) / src.name
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        return str(dest)

"""Load code_exec settings from vela.yaml."""

import os
from dataclasses import dataclass, field
from typing import List

import yaml

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
CONFIG_PATH = os.path.join(_BACKEND_DIR, "vela.yaml")
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
DEFAULT_VENV_PATH = os.path.join(DATA_DIR, "sandbox-venv")
WORKSPACES_ROOT = os.path.join(DATA_DIR, "workspaces")

DEFAULT_PACKAGE_ALLOWLIST = [
    "pandas",
    "numpy",
    "matplotlib",
    "scipy",
    "openpyxl",
    "pillow",
    "seaborn",
    "tabulate",
    "dill",
]


@dataclass
class CodeExecConfig:
    enabled: bool = True
    venv_path: str = ""
    wall_timeout: int = 60
    cpu_seconds: int = 30
    memory_mb: int = 2048
    max_output_bytes: int = 65536
    max_artifact_mb: int = 20
    allow_network: bool = False
    allow_install: bool = True
    package_allowlist: List[str] = field(default_factory=lambda: list(DEFAULT_PACKAGE_ALLOWLIST))
    state_persist: bool = True

    @property
    def resolved_venv_path(self) -> str:
        return self.venv_path or DEFAULT_VENV_PATH

    @property
    def python_executable(self) -> str:
        if os.name == "nt":
            return os.path.join(self.resolved_venv_path, "Scripts", "python.exe")
        return os.path.join(self.resolved_venv_path, "bin", "python")

    @property
    def pip_executable(self) -> str:
        if os.name == "nt":
            return os.path.join(self.resolved_venv_path, "Scripts", "pip.exe")
        return os.path.join(self.resolved_venv_path, "bin", "pip")


def _load_yaml() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_code_exec_config() -> CodeExecConfig:
    raw = (_load_yaml().get("code_exec") or {})
    allowlist = raw.get("package_allowlist")
    if allowlist is None:
        allowlist = list(DEFAULT_PACKAGE_ALLOWLIST)
    return CodeExecConfig(
        enabled=bool(raw.get("enabled", True)),
        venv_path=str(raw.get("venv_path") or ""),
        wall_timeout=int(raw.get("wall_timeout", 60)),
        cpu_seconds=int(raw.get("cpu_seconds", 30)),
        memory_mb=int(raw.get("memory_mb", 2048)),
        max_output_bytes=int(raw.get("max_output_bytes", 65536)),
        max_artifact_mb=int(raw.get("max_artifact_mb", 20)),
        allow_network=bool(raw.get("allow_network", False)),
        allow_install=bool(raw.get("allow_install", True)),
        package_allowlist=list(allowlist),
        state_persist=bool(raw.get("state_persist", True)),
    )


def save_code_exec_config(cfg: CodeExecConfig) -> None:
    config = _load_yaml()
    config["code_exec"] = {
        "enabled": cfg.enabled,
        "venv_path": cfg.venv_path,
        "wall_timeout": cfg.wall_timeout,
        "cpu_seconds": cfg.cpu_seconds,
        "memory_mb": cfg.memory_mb,
        "max_output_bytes": cfg.max_output_bytes,
        "max_artifact_mb": cfg.max_artifact_mb,
        "allow_network": cfg.allow_network,
        "allow_install": cfg.allow_install,
        "package_allowlist": cfg.package_allowlist,
        "state_persist": cfg.state_persist,
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

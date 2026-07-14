import os
from typing import Any, Dict

import yaml

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VELA_YAML = os.path.join(_BACKEND_DIR, "vela.yaml")

SCREENPILOT_DATA_DIR = os.path.join(
    os.path.dirname(_BACKEND_DIR),
    "data",
    "screenpilot",
)
ARTIFACTS_DIR = os.path.join(SCREENPILOT_DATA_DIR, "artifacts")

# P2: Integration Gateway OAuth2.1 客户端
SCREENPILOT_OAUTH_TOKEN_URL = os.getenv("SCREENPILOT_OAUTH_TOKEN_URL", "")
SCREENPILOT_OAUTH_CLIENT_ID = os.getenv("SCREENPILOT_OAUTH_CLIENT_ID", "")
SCREENPILOT_OAUTH_CLIENT_SECRET = os.getenv("SCREENPILOT_OAUTH_CLIENT_SECRET", "")
SCREENPILOT_OAUTH_SCOPE = os.getenv("SCREENPILOT_OAUTH_SCOPE", "")

# 会话闲置回收（秒）；CDP 附着地址（空则本地 launch）
SCREENPILOT_INACTIVITY_TIMEOUT = int(os.getenv("SCREENPILOT_INACTIVITY_TIMEOUT", "300") or "300")
SCREENPILOT_CDP_URL = os.getenv("SCREENPILOT_CDP_URL", "")
# Vision 兜底：指定 model_service_id 或 model_name；空则尝试找带 vision 能力的服务
SCREENPILOT_VISION_MODEL_SERVICE_ID = os.getenv("SCREENPILOT_VISION_MODEL_SERVICE_ID", "")
SCREENPILOT_VISION_MODEL_NAME = os.getenv("SCREENPILOT_VISION_MODEL_NAME", "")

os.makedirs(ARTIFACTS_DIR, exist_ok=True)

CU_TOOL_NAMES = (
    "cu_navigate",
    "cu_observe",
    "cu_act",
    "cu_extract",
    "cu_replay_skill",
    "cu_compile_skill",
    "cu_search_skills",
    "cu_run_task",
    "cu_wait_for_otp",
    "cu_vision",
)

# 历史 ui_* 名称，关闭/迁移时一并清理
LEGACY_UI_TOOL_NAMES = (
    "ui_navigate",
    "ui_observe",
    "ui_act",
    "ui_extract",
    "ui_replay_skill",
    "ui_compile_skill",
    "ui_search_skills",
    "ui_run_task",
)


def _env_enabled() -> bool:
    return os.getenv("SCREENPILOT_ENABLED", "false").lower() in ("1", "true", "yes")


def _load_vela_yaml() -> Dict[str, Any]:
    if not os.path.isfile(_VELA_YAML):
        return {}
    with open(_VELA_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_vela_yaml(config: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_VELA_YAML), exist_ok=True)
    with open(_VELA_YAML, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def is_screenpilot_enabled() -> bool:
    """优先读 vela.yaml 中的 screenpilot.enabled；未配置时回退环境变量。"""
    cfg = _load_vela_yaml()
    sp = cfg.get("screenpilot")
    if isinstance(sp, dict) and "enabled" in sp:
        return bool(sp["enabled"])
    return _env_enabled()


def set_screenpilot_enabled(enabled: bool) -> None:
    cfg = _load_vela_yaml()
    if "screenpilot" not in cfg or not isinstance(cfg.get("screenpilot"), dict):
        cfg["screenpilot"] = {}
    cfg["screenpilot"]["enabled"] = bool(enabled)
    _save_vela_yaml(cfg)


# 兼容旧 import：启动时快照；运行时请用 is_screenpilot_enabled()
SCREENPILOT_ENABLED = is_screenpilot_enabled()

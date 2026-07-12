import os

SCREENPILOT_ENABLED = os.getenv("SCREENPILOT_ENABLED", "false").lower() in ("1", "true", "yes")
SCREENPILOT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "screenpilot",
)
ARTIFACTS_DIR = os.path.join(SCREENPILOT_DATA_DIR, "artifacts")

os.makedirs(ARTIFACTS_DIR, exist_ok=True)

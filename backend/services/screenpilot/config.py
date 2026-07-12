import os

SCREENPILOT_ENABLED = os.getenv("SCREENPILOT_ENABLED", "false").lower() in ("1", "true", "yes")
SCREENPILOT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "screenpilot",
)
ARTIFACTS_DIR = os.path.join(SCREENPILOT_DATA_DIR, "artifacts")

# P2: Integration Gateway OAuth2.1 客户端
SCREENPILOT_OAUTH_TOKEN_URL = os.getenv("SCREENPILOT_OAUTH_TOKEN_URL", "")
SCREENPILOT_OAUTH_CLIENT_ID = os.getenv("SCREENPILOT_OAUTH_CLIENT_ID", "")
SCREENPILOT_OAUTH_CLIENT_SECRET = os.getenv("SCREENPILOT_OAUTH_CLIENT_SECRET", "")
SCREENPILOT_OAUTH_SCOPE = os.getenv("SCREENPILOT_OAUTH_SCOPE", "")

os.makedirs(ARTIFACTS_DIR, exist_ok=True)

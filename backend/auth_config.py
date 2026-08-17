import os
from pathlib import Path

SECRET_KEY = os.getenv("VELA_SECRET_KEY", "vela-agent-dev-secret-change-me")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("VELA_ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
ADMIN_USERNAME = os.getenv("VELA_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("VELA_ADMIN_PASSWORD", "admin123")

DATA_DIR = Path(__file__).resolve().parent / "data"
AVATAR_DIR = DATA_DIR / "avatars"

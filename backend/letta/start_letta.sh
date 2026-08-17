#!/usr/bin/env bash
# Start self-hosted Letta server (independent venv).
# Requires vela backend already running on :8000 for LLM/embedding gateway.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [[ ! -d .venv ]]; then
  echo "[letta] creating venv..."
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  echo "[letta] installing letta==0.16.8 (this may take a few minutes)..."
  .venv/bin/pip install "letta==0.16.8"
fi

# Optional / soft deps used by Letta 0.16.x (SQLite path + optional Postgres)
for pkg in asyncpg aiosqlite sqlite-vec pg8000; do
  if ! .venv/bin/python -c "import ${pkg//-/_}" >/dev/null 2>&1; then
    echo "[letta] installing missing dependency: $pkg"
    .venv/bin/pip install "$pkg"
  fi
done

# Letta 0.16.x server/db.py is Postgres-only; restore SQLite for local/dev.
PATCH_SRC="$DIR/patches/db_sqlite_compat.py"
if [[ -f "$PATCH_SRC" ]]; then
  PATCH_DST="$(.venv/bin/python - <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.find_spec("letta.server.db")
if not spec or not spec.origin:
    sys.exit(1)
print(spec.origin)
PY
)"
  if [[ -n "$PATCH_DST" && -f "$PATCH_DST" ]]; then
    if [[ ! -f "${PATCH_DST}.bak" ]]; then
      cp "$PATCH_DST" "${PATCH_DST}.bak"
    fi
    cp "$PATCH_SRC" "$PATCH_DST"
    echo "[letta] applied SQLite-compat patch to letta.server.db"
  else
    echo "[letta] warning: could not locate letta.server.db to patch" >&2
  fi
fi

# SQLite-safe timestamp defaults on base mixin and junction tables
BASE_PATCH="$DIR/patches/orm_base_sqlite.py"
if [[ -f "$BASE_PATCH" ]]; then
  BASE_DST="$(.venv/bin/python - <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.find_spec("letta.orm.base")
if not spec or not spec.origin:
    sys.exit(1)
print(spec.origin)
PY
)"
  if [[ -n "$BASE_DST" && -f "$BASE_DST" ]]; then
    [[ -f "${BASE_DST}.bak" ]] || cp "$BASE_DST" "${BASE_DST}.bak"
    cp "$BASE_PATCH" "$BASE_DST"
    echo "[letta] applied SQLite timestamp patch to letta.orm.base"
  fi
fi

for rel in archives_agents blocks_tags files_agents; do
  SRC="$DIR/patches/${rel}.py"
  if [[ -f "$SRC" ]]; then
    DST="$(.venv/bin/python - <<PY 2>/dev/null
import importlib.util, sys
spec = importlib.util.find_spec("letta.orm.${rel}")
if not spec or not spec.origin:
    sys.exit(1)
print(spec.origin)
PY
)"
    if [[ -n "$DST" && -f "$DST" ]]; then
      [[ -f "${DST}.bak" ]] || cp "$DST" "${DST}.bak"
      cp "$SRC" "$DST"
      echo "[letta] applied SQLite patch to letta.orm.${rel}"
    fi
  fi
done

export LETTA_DIR="${LETTA_DIR:-$DIR/.letta}"
mkdir -p "$LETTA_DIR"

export OPENAI_API_KEY="${VELA_LLM_GATEWAY_TOKEN:-vela-local-gateway}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-http://127.0.0.1:8000/llm-gateway/v1}"
export SECURE="${SECURE:-true}"
export LETTA_SERVER_PASSWORD="${LETTA_SERVER_PASSWORD:-vela-letta-dev}"

# Default: SQLite under LETTA_DIR. Set LETTA_PG_URI to use Postgres instead.
# Example: export LETTA_PG_URI='postgresql+pg8000://letta:letta@localhost:5432/letta'

PORT="${LETTA_PORT:-8283}"
echo "[letta] LETTA_DIR=$LETTA_DIR"
echo "[letta] OPENAI_API_BASE=$OPENAI_API_BASE"
if [[ -n "${LETTA_PG_URI:-}" ]]; then
  echo "[letta] DB=postgres ($LETTA_PG_URI)"
else
  echo "[letta] DB=sqlite ($LETTA_DIR/sqlite.db)"
fi
echo "[letta] starting on :$PORT ..."

# Prefer `letta server` CLI; fall back to python -m if needed
if .venv/bin/letta --help >/dev/null 2>&1; then
  exec .venv/bin/letta server --port "$PORT"
elif .venv/bin/python -c "import letta" >/dev/null 2>&1; then
  exec .venv/bin/python -m letta.server.rest_api.app --port "$PORT"
else
  echo "[letta] letta package not found in .venv; run: .venv/bin/pip install letta" >&2
  exit 1
fi

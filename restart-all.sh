#!/bin/bash
# Alias for restart.sh — restarts backend, Letta, and frontend.
exec "$(cd "$(dirname "$0")" && pwd)/restart.sh" "$@"

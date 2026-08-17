#!/bin/bash
# Alias for start.sh — starts backend, Letta, and frontend.
exec "$(cd "$(dirname "$0")" && pwd)/start.sh" "$@"

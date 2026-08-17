#!/bin/bash
# Alias for stop.sh — stops Letta, backend, and frontend.
exec "$(cd "$(dirname "$0")" && pwd)/stop.sh" "$@"

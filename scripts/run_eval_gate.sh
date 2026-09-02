#!/usr/bin/env bash
# CI quality gate: run eval job and fail if pass rate below threshold.
set -euo pipefail
DATASET_ID="${1:-}"
THRESHOLD="${2:-0.8}"
API_BASE="${VELA_API_BASE:-http://127.0.0.1:8000/api/v1}"
TOKEN="${VELA_API_TOKEN:-}"

if [[ -z "$DATASET_ID" ]]; then
  echo "Usage: $0 <dataset_id> [pass_threshold]"
  exit 2
fi

auth_header=()
if [[ -n "$TOKEN" ]]; then
  auth_header=(-H "Authorization: Bearer $TOKEN")
fi

job_id=$(curl -sf "${auth_header[@]}" -X POST "$API_BASE/eval/jobs" \
  -H 'Content-Type: application/json' \
  -d "{\"dataset_id\":\"$DATASET_ID\",\"pass_threshold\":$THRESHOLD}" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

result=$(curl -sf "${auth_header[@]}" -X POST "$API_BASE/eval/jobs/$job_id/run")
pass_rate=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('summary',{}).get('pass_rate',0))")
status=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','FAILED'))")

echo "Eval job $job_id: status=$status pass_rate=$pass_rate threshold=$THRESHOLD"
if [[ "$status" != "SUCCESS" ]]; then
  exit 1
fi

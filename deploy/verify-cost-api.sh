#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=/opt/tokenpool/.env
ADMIN_USER=$(grep -E '^ADMIN_USERNAME=' "$ENV_FILE" | cut -d= -f2)
ADMIN_PASS=$(grep -E '^ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2)

TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
echo "login: ok"

echo "=== /api/admin/stats?days=30 ==="
curl -s "http://127.0.0.1:8000/api/admin/stats?days=30" \
  -H "Authorization: Bearer $TOKEN" | python3 -c '
import sys, json
data = json.load(sys.stdin)
s = data["summary"]
print("summary: requests=%s tokens=%s cost=%.6f" % (s["requests"], s["total_tokens"], s["cost"]))
for row in data["by_model"][:5]:
    print("by_model: %-18s tokens=%-10s cost=%.6f" % (row["model"], row["total_tokens"], row["cost"]))
for row in data["by_user"][:5]:
    print("by_user:  %-18s cost=%.6f" % (row["username"], row["cost"]))
'

echo "=== /api/admin/usage-logs?days=30&limit=3 ==="
curl -s "http://127.0.0.1:8000/api/admin/usage-logs?days=30&limit=3" \
  -H "Authorization: Bearer $TOKEN" | python3 -c '
import sys, json
data = json.load(sys.stdin)
for item in data["items"]:
    print("%s %s in=%s out=%s cached=%s cost=%s source=%s" % (
        item["request_id"][:16], item["model"], item["input_tokens"],
        item["output_tokens"], item["cached_input_tokens"],
        item["cost"], item["cost_source"]))
    print("   detail:", item["price_detail"])
'

echo "=== /api/admin/models pricing sample ==="
curl -s "http://127.0.0.1:8000/api/admin/models" \
  -H "Authorization: Bearer $TOKEN" | python3 -c '
import sys, json
data = json.load(sys.stdin)
priced = [m for m in data if m.get("pricing")]
print("models total=%s priced=%s" % (len(data), len(priced)))
for m in priced[:3]:
    p = m["pricing"]
    print("%-14s in=%s cache=%s out=%s peak_in=%s tier=%s" % (
        m["public_model"], p["input_price"], p["cached_input_price"],
        p["output_price"], p["peak_input_price"], p["tier_threshold_tokens"]))
'

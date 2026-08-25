#!/bin/bash
set -e
cd /opt/tokenpool/backend
while IFS='=' read -r key value; do
  key=$(printf '%s' "$key" | tr -d '\r')
  case "$key" in ''|\#*) continue ;; esac
  export "$key=$value"
done < /opt/tokenpool/.env
export PYTHONPATH=/opt/tokenpool/backend
.venv/bin/python scripts/calibrate_deepseek_export.py \
  --amount-csv /tmp/ds_amount.csv \
  --cost-csv /tmp/ds_cost.csv \
  "$@"

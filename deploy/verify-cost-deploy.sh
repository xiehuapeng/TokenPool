#!/usr/bin/env bash
set -u

echo "=== backup file ==="
ls -la /opt/tokenpool/backup-before-0006-*.tar.gz 2>/dev/null || echo "no backup found"

echo "=== service ==="
systemctl is-active tokenpool

echo "=== alembic ==="
cd /opt/tokenpool/backend && .venv/bin/python -m alembic current

echo "=== health ==="
curl -s -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8000/health

echo "=== database ==="
run_sql() {
  sudo -u postgres psql tokenpool -t -A -c "$1"
}
echo "pricing_rows=$(run_sql 'select count(*) from model_pricings')"
echo "model_rows=$(run_sql 'select count(*) from model_configs')"
echo "new_usage_cols=$(run_sql "select string_agg(column_name, ',' order by column_name) from information_schema.columns where table_name='usage_logs' and column_name in ('cached_input_tokens','reasoning_tokens','cost','cost_source','price_detail','usage_source')")"
echo "--- seed pricing sample ---"
sudo -u postgres psql tokenpool -c "select mc.public_model, mp.input_price as in_p, mp.cached_input_price as cache_p, mp.output_price as out_p, mp.peak_input_price as peak_in, mp.tier_threshold_tokens as tier_thr from model_pricings mp join model_configs mc on mc.id = mp.model_config_id order by mc.public_model"
echo "--- recent usage logs (last 3) ---"
sudo -u postgres psql tokenpool -c "select request_id, model, input_tokens, output_tokens, cached_input_tokens, cost, cost_source from usage_logs order by request_time desc limit 3"

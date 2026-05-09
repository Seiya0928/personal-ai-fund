#!/usr/bin/env bash

set -u

PROJECT_DIR="${HOME}/personal-ai-fund"
LOG_DIR="${PROJECT_DIR}/logs"
DATE_STAMP="$(date +%Y%m%d)"
LOG_FILE="${LOG_DIR}/btc_dip_alert_${DATE_STAMP}.log"

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}" || exit 1

if [[ -f "${PROJECT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env"
  set +a
fi

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] run_daily_btc_alert start"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] fetch_btc_price start"
  ./venv/bin/python scripts/fetch_btc_price.py
  fetch_exit_code=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] fetch_btc_price exit_code=${fetch_exit_code}"
  ./venv/bin/python -c "from src.storage.sqlite_store import SQLiteStore; t=SQLiteStore().load_latest_ticker('BTC_JPY'); print('Latest BTC_JPY ticker timestamp: ' + (str(t.get('timestamp')) if t else 'None'))"
  if [[ "${fetch_exit_code}" -ne 0 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] fetch_btc_price failed; skip run_btc_dip_alert to avoid stale-market judgment"
    echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] run_daily_btc_alert exit_code=${fetch_exit_code}"
    exit "${fetch_exit_code}"
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] run_btc_dip_alert start"
  ./venv/bin/python scripts/run_btc_dip_alert.py --send-email --markdown --send-daily-summary
  exit_code=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] run_daily_btc_alert exit_code=${exit_code}"
  exit "${exit_code}"
} >> "${LOG_FILE}" 2>&1

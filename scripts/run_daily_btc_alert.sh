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
  ./venv/bin/python scripts/run_btc_dip_alert.py --send-email --markdown --send-daily-summary
  exit_code=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] run_daily_btc_alert exit_code=${exit_code}"
  exit "${exit_code}"
} >> "${LOG_FILE}" 2>&1

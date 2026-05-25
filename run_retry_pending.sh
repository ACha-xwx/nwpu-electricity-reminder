#!/usr/bin/env bash
set -euo pipefail
cd /home/ACha_/npu_check_electricity
. .venv/bin/activate
export TZ=Asia/Shanghai
python retry_pending_notifications.py >> cron.log 2>&1

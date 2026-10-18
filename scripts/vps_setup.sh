#!/usr/bin/env bash
# vps_setup.sh — развёртывание bybit-bot на чистый VPS (Ubuntu 24.04, Нидерланды).
# Однократный запуск от root:  sudo bash vps_setup.sh
# Ключи API вводятся интерактивно (ввод не отображается) и пишутся в
# /etc/bybit-bot.env с правами 600. Ключи НИГДЕ больше не сохраняются.
# Перед запуском: создать VPS (Amsterdam, Ubuntu 24.04), привязать к нему
# SSH-ключ, выпустить НОВУЮ demo-пару ключей Bybit с IP-whitelist = IP этого VPS
# (старые ключи Mac-контура НЕ трогать — они продолжают работать параллельно 24 ч).
set -euo pipefail

REPO="https://github.com/martinrosenfield/bybit-bot.git"
APP_DIR="/opt/bybit-bot"
ENV_FILE="/etc/bybit-bot.env"
RUN_USER="bybitbot"

echo "== 1/8 apt: git, python, venv, firewall, автообновления =="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends git python3 python3-venv python3-pip ufw unattended-upgrades

echo "== 2/8 системный пользователь $RUN_USER =="
id -u "$RUN_USER" >/dev/null 2>&1 || \
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$RUN_USER"

echo "== 3/8 клон репозитория в $APP_DIR =="
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO" "$APP_DIR"
fi
git -C "$APP_DIR" log --oneline -3
echo "Сверьте верхний коммит с репозиторием на GitHub перед запуском."

echo "== 4/8 venv + pybit>=5.8 =="
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet "pybit>=5.8"
"$APP_DIR/venv/bin/python" -c "import pybit; print('pybit', pybit.__version__, 'OK')"

echo "== 5/8 runtime_state.json =="
if [ ! -f "$APP_DIR/runtime_state.json" ]; then
  cp "$APP_DIR/runtime_state.example.json" "$APP_DIR/runtime_state.json"
fi

echo "== 6/8 права =="
mkdir -p "$APP_DIR/logs"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"

echo "== 7/8 ключи Bybit (demo) — ввод скрыт =="
if [ -f "$ENV_FILE" ]; then
  echo "$ENV_FILE уже существует — пропускаю (для перевыпуска: rm $ENV_FILE и перезапустите скрипт)."
else
  read -rsp "BYBIT_API_KEY: " KEY; echo
  read -rsp "BYBIT_API_SECRET: " SECRET; echo
  if [ -z "$KEY" ] || [ -z "$SECRET" ]; then
    echo "Пустой ключ — прерываю, env-файл не создан." >&2; exit 1
  fi
  umask 077
  printf 'BYBIT_API_KEY=%s\nBYBIT_API_SECRET=%s\nCONFIRM_LIVE=YES\n' "$KEY" "$SECRET" > "$ENV_FILE"
  chown root:root "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "$ENV_FILE создан (root:root, 600)."
fi

echo "== 8/8 systemd + firewall =="
install -m 0644 "$APP_DIR/deploy/bybit-bot.service" /etc/systemd/system/bybit-bot.service
systemctl daemon-reload
systemctl enable --now bybit-bot

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "== проверка =="
sleep 5
systemctl is-active bybit-bot
echo "--- journalctl -u bybit-bot -n 25 ---"
journalctl -u bybit-bot -n 25 --no-pager
echo
echo "Далее: curl -s https://api-demo.bybit.com/v5/market/time (ожидается retCode 0),"
echo "ждите PREFLIGHT в journalctl -u bybit-bot -f. Mac-контур гасить ТОЛЬКО через 24 ч."

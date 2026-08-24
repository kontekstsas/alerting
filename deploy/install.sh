#!/usr/bin/env bash
#
# Установка мониторинга сайтов на Ubuntu/Debian.
# Запускать от root из каталога с распакованным репозиторием:
#
#     sudo bash deploy/install.sh
#
# Повторный запуск безопасен: обновляет код и юниты, не трогая секреты и state.json.

set -euo pipefail

APP_DIR=/opt/site-monitor
ENV_DIR=/etc/site-monitor
ENV_FILE="$ENV_DIR/env"
APP_USER=sitemonitor

if [[ $EUID -ne 0 ]]; then
    echo "Нужны права root: sudo bash deploy/install.sh" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "$SRC_DIR/monitoring_bot.py" ]]; then
    echo "Не нашёл monitoring_bot.py рядом с deploy/. Запускайте из каталога репозитория." >&2
    exit 1
fi

echo "==> Ставлю системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates

echo "==> Создаю пользователя $APP_USER"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Раскладываю файлы в $APP_DIR"
mkdir -p "$APP_DIR/tests"
install -m 644 "$SRC_DIR/monitoring_bot.py" "$APP_DIR/monitoring_bot.py"
install -m 644 "$SRC_DIR/tests/suspended_hostfly.html" "$APP_DIR/tests/suspended_hostfly.html"

echo "==> Собираю виртуальное окружение"
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet cloudscraper curl_cffi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Готовлю файл с секретами"
mkdir -p "$ENV_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
    cat > "$ENV_FILE" <<'ENVEOF'
# Токен бота и id чата — те же, что были в секретах GitHub
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# 'by' — если сервер в Беларуси, иначе abroad.
# От этого зависит, считать ли недоступность by-only сайтов аварией.
MONITOR_LOCATION=abroad
ENVEOF
    echo "    создан $ENV_FILE — впишите туда токен и chat_id"
else
    echo "    $ENV_FILE уже есть, не трогаю"
fi
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

echo "==> Проверяю детектор на сохранённой заглушке"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" "$APP_DIR/monitoring_bot.py" --selftest

echo "==> Ставлю юниты systemd"
install -m 644 "$SRC_DIR/deploy/site-monitor.service" /etc/systemd/system/site-monitor.service
install -m 644 "$SRC_DIR/deploy/site-monitor.timer" /etc/systemd/system/site-monitor.timer
install -m 644 "$SRC_DIR/deploy/site-monitor-failure.service" /etc/systemd/system/site-monitor-failure.service
systemctl daemon-reload
systemctl enable --now site-monitor.timer

echo
echo "Готово."
echo
if ! grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$ENV_FILE"; then
    echo "ВАЖНО: впишите токен и chat_id в $ENV_FILE, иначе сообщения никуда не уйдут:"
    echo "    sudoedit $ENV_FILE"
    echo "    sudo systemctl start site-monitor.service"
    echo
fi
echo "Полезные команды:"
echo "    systemctl list-timers site-monitor.timer   когда следующий запуск"
echo "    systemctl start site-monitor.service       проверить прямо сейчас"
echo "    journalctl -u site-monitor -n 50           что было в последний раз"
echo "    cat $APP_DIR/state.json                    текущее состояние сайтов"

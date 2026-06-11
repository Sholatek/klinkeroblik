#!/bin/bash
# Скрипт развертывания нового клиента для бота "Бригада"
# Поддерживает --keep для случая, когда директория клиента уже существует.

set -euo pipefail

KEEP_DIR=0
if [ "${1:-}" = "--keep" ]; then
  KEEP_DIR=1
  shift 1
fi

if [ "$EUID" -ne 0 ]; then
 echo "Пожалуйста, запустите скрипт от имени root (sudo)"
 exit 1
fi

if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
 echo "Использование: $0 [--keep] <client_name> <bot_token> [bot_display_name]"
 echo "Пример: $0 --keep dmytro 123456789:ABCdefGHIjklMNOpqrsTUVwxyz \"Dmytro Oblik\""
 exit 1
fi

CLIENT_NAME=$1
BOT_TOKEN=$2
BOT_DISPLAY_NAME=${3:-$CLIENT_NAME}

MASTER_DIR="/home/klinker/klinkeroblik"
CLIENTS_BASE="/home/klinker/clients"
CLIENT_DIR="$CLIENTS_BASE/$CLIENT_NAME"
SERVICE_NAME="klinkeroblik-$CLIENT_NAME"

echo "=== Создание инстанса для клиента: $CLIENT_NAME ==="

if [ -d "$CLIENT_DIR" ]; then
  if [ "$KEEP_DIR" -eq 1 ]; then
    echo "Директория $CLIENT_DIR уже существует — используем (пароль/токен/настройки обновятся, сервис перезапустится)."
  else
    echo "Ошибка: Директория $CLIENT_DIR уже существует."
    echo "Запусти с флагом --keep, если это повторный деплой."
    exit 1
  fi
else
  # 1. Создание структуры папок
  mkdir -p "$CLIENT_DIR/data"
  mkdir -p "$CLIENT_DIR/docs"
fi

# 2. Копирование исходного кода (без venv, data, .git, .env)
echo "Копирование файлов проекта..."
cp "$MASTER_DIR/"*.py "$CLIENT_DIR/"
cp -r "$MASTER_DIR/handlers" "$CLIENT_DIR/"
cp -r "$MASTER_DIR/utils" "$CLIENT_DIR/"
cp -r "$MASTER_DIR/locales" "$CLIENT_DIR/"
mkdir -p "$CLIENT_DIR/docs"
cp -r "$MASTER_DIR/docs"/* "$CLIENT_DIR/docs/" 2>/dev/null || true

# 3. Создание .env для клиента
# (только токен и DATABASE_URL; остальные секреты не трогаем)
echo "Создание конфигурации (.env)..."
cat <<ENV_EOF > "$CLIENT_DIR/.env"
BOT_TOKEN=$BOT_TOKEN
DATABASE_URL=sqlite+aiosqlite:////$CLIENT_DIR/data/klinkeroblik.db
ENV_EOF

# 4. Создание .env.docs (отдельный для каждого клиента, с его названием бота)
cp "$MASTER_DIR/.env.docs" "$CLIENT_DIR/.env.docs"
sed -i "s/NAZWA_BOTA=.*/NAZWA_BOTA=$BOT_DISPLAY_NAME/" "$CLIENT_DIR/.env.docs"

# 5. Права доступа
chown -R klinker:klinker "$CLIENT_DIR"
chmod 600 "$CLIENT_DIR/.env"
chmod 600 "$CLIENT_DIR/.env.docs"

# 6. Создание systemd сервиса (используем общий venv из мастера для экономии памяти)
echo "Настройка systemd сервиса ($SERVICE_NAME.service)..."
cat <<SRV_EOF > "/etc/systemd/system/$SERVICE_NAME.service"
[Unit]
Description=KlinkerOblik Telegram Bot - Client $CLIENT_NAME
After=network.target

[Service]
User=klinker
Group=klinker
WorkingDirectory=$CLIENT_DIR
Environment="PATH=$MASTER_DIR/venv/bin"
ExecStart=$MASTER_DIR/venv/bin/python bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SRV_EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"

# если уже существовал — перезапустим
if [ "$KEEP_DIR" -eq 1 ]; then
  systemctl restart "$SERVICE_NAME.service" || systemctl start "$SERVICE_NAME.service"
else
  systemctl start "$SERVICE_NAME.service"
fi

echo "=== Готово! ==="
echo "Бот для клиента $CLIENT_NAME запущен (отображаемое имя: $BOT_DISPLAY_NAME)."
echo "Просмотр логов: journalctl -u $SERVICE_NAME.service -f"

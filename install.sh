#!/bin/bash
##############################################################
#  KlinkerOblik — автоматичне встановлення
#  Запускай від root на свіжому Ubuntu 22.04 / 24.04
#
#  Використання:
#    bash install.sh
##############################################################

set -e  # Зупинитись при помилці

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   🏗️  KlinkerOblik — Встановлення        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# --- Перевірки ---
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Запустіть від root: sudo bash install.sh${NC}"
    exit 1
fi

# --- Запит токена ---
BOT_TOKEN="${BOT_TOKEN:-}"
if [ -z "$BOT_TOKEN" ]; then
    echo -e "${YELLOW}🔑 Введіть токен Telegram бота (від @BotFather):${NC}"
    read -r BOT_TOKEN
    if [ -z "$BOT_TOKEN" ]; then
        echo -e "${RED}❌ Токен не може бути пустим!${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}📦 1/6 — Оновлення системи та встановлення Python...${NC}"
apt update -qq
apt install -y -qq python3 python3-pip python3-venv curl tar > /dev/null 2>&1
echo -e "${GREEN}   ✅ Python $(python3 --version | cut -d' ' -f2) встановлено${NC}"

echo ""
echo -e "${GREEN}👤 2/6 — Створення користувача klinker...${NC}"
if id "klinker" &>/dev/null; then
    echo -e "${YELLOW}   ⚠️ Користувач klinker вже існує, пропускаю${NC}"
else
    adduser --disabled-password --gecos "KlinkerOblik Bot" klinker > /dev/null 2>&1
    echo -e "${GREEN}   ✅ Користувач створений${NC}"
fi

APP_DIR="/home/klinker/klinkeroblik"
echo ""
echo -e "${GREEN}📁 3/6 — Встановлення файлів бота...${NC}"
mkdir -p "$APP_DIR"

# Розпакувати архів якщо є поруч
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/klinkeroblik.tar.gz" ]; then
    tar xzf "$SCRIPT_DIR/klinkeroblik.tar.gz" -C "$APP_DIR"
    echo -e "${GREEN}   ✅ Файли розпаковані з архіву${NC}"
elif [ -f "$APP_DIR/bot.py" ]; then
    echo -e "${YELLOW}   ⚠️ Файли вже на місці${NC}"
else
    echo -e "${RED}   ❌ Не знайдено klinkeroblik.tar.gz поруч зі скриптом!${NC}"
    echo -e "${RED}   Завантажте обидва файли в одну папку:${NC}"
    echo -e "${RED}   - install.sh${NC}"
    echo -e "${RED}   - klinkeroblik.tar.gz${NC}"
    exit 1
fi

# Створити .env
cat > "$APP_DIR/.env" << EOF
BOT_TOKEN=$BOT_TOKEN
DATABASE_URL=sqlite+aiosqlite:///data/klinkeroblik.db
EOF

# Створити папку для БД
mkdir -p "$APP_DIR/data"

# Права
chown -R klinker:klinker "$APP_DIR"
echo -e "${GREEN}   ✅ .env створено, права встановлені${NC}"

echo ""
echo -e "${GREEN}🐍 4/6 — Встановлення Python-залежностей...${NC}"
sudo -u klinker bash -c "
    cd $APP_DIR
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet -r requirements.txt
"
echo -e "${GREEN}   ✅ Залежності встановлені${NC}"

echo ""
echo -e "${GREEN}⚙️  5/6 — Створення systemd-сервісу...${NC}"
cat > /etc/systemd/system/klinkeroblik.service << EOF
[Unit]
Description=KlinkerOblik Telegram Bot
After=network.target

[Service]
Type=simple
User=klinker
Group=klinker
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin:/usr/bin"
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable klinkeroblik > /dev/null 2>&1
echo -e "${GREEN}   ✅ Сервіс створено та включено${NC}"

echo ""
echo -e "${GREEN}🚀 6/6 — Запуск бота...${NC}"
systemctl start klinkeroblik
sleep 3

if systemctl is-active --quiet klinkeroblik; then
    echo -e "${GREEN}   ✅ Бот запущений і працює!${NC}"
else
    echo -e "${RED}   ❌ Щось пішло не так. Перевірте логи:${NC}"
    echo -e "${RED}   journalctl -u klinkeroblik -n 30${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅  Встановлення завершено!            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  🤖 Бот працює! Відкрийте Telegram і натисніть /start"
echo ""
echo -e "  📋 Корисні команди:"
echo -e "    ${YELLOW}systemctl status klinkeroblik${NC}   — статус бота"
echo -e "    ${YELLOW}systemctl restart klinkeroblik${NC}  — перезапустити"
echo -e "    ${YELLOW}systemctl stop klinkeroblik${NC}     — зупинити"
echo -e "    ${YELLOW}journalctl -u klinkeroblik -f${NC}   — логи в реальному часі"
echo ""
echo -e "  📁 Файли: ${YELLOW}$APP_DIR${NC}"
echo -e "  💾 База:  ${YELLOW}$APP_DIR/data/klinkeroblik.db${NC}"
echo ""

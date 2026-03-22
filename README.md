# KlinkerOblik — Telegram Bot для обліку робіт будівельних бригад

Бот для щоденного обліку робіт: м², мп, додроботи, звіти по бригадах/об'єктах.

---

## 🚀 Швидкий старт

### 1. Створи сервер на Hetzner

1. Зареєструйся на [Hetzner Cloud](https://console.hetzner.cloud/)
2. Створи новий проект
3. **Create Server**:
   - Name: `klinkeroblik`
   - Location: `Nuremberg` або `Falkenstein` (Німеччина)
   - Image: `Ubuntu 24.04`
   - Type: **CX22** (2 vCPU, 4 GB RAM, €3.85/міс)
   - SSH Key: додай свій (або створи новий)
4. Натисни **Create Server**

### 2. Підключись до сервера

```bash
ssh root@<IP-адреса-сервера>
```

### 3. Встанови Python та залежності

```bash
# Онови систему
apt update && apt upgrade -y

# Встанови Python 3.11+, pip, git
apt install -y python3 python3-pip python3-venv git

# Створи користувача для бота
adduser --disabled-password --gecos "" klinker
su - klinker
```

### 4. Завантаж код бота

```bash
# Клонуй репозиторій (або завантаж архів)
git clone <твій-репозиторій> klinkeroblik
cd klinkeroblik

# АБО: створи папку і завантаж файли через SFTP/SCP
mkdir -p ~/klinkeroblik
# Скопіюй сюди всі файли з цього репозиторію
```

### 5. Налаштуй .env

```bash
nano .env
```

Встав:
```env
BOT_TOKEN=8540947079:AAEA7jlmbozLHw-ueQdFNSK0zizAqZk0Voc
DATABASE_URL=sqlite+aiosqlite:///data/klinkeroblik.db
```

Збережи (Ctrl+O, Enter, Ctrl+X).

### 6. Створи віртуальне оточення і встанови залежності

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 7. Запусти бота

```bash
# Тестовий запуск (щоб переконатись що працює)
python3 bot.py
```

Якщо бачиш `Bot started. Polling...` — все працює!

Натисни `Ctrl+C` щоб зупинити.

### 8. Запусти як сервіс (щоб працював 24/7)

Вийди з користувача klinker:
```bash
exit
```

Створи systemd сервіс:
```bash
nano /etc/systemd/system/klinkeroblik.service
```

Встав:
```ini
[Unit]
Description=KlinkerOblik Telegram Bot
After=network.target

[Service]
Type=simple
User=klinker
WorkingDirectory=/home/klinker/klinkeroblik
Environment="PATH=/home/klinker/klinkeroblik/venv/bin"
ExecStart=/home/klinker/klinkeroblik/venv/bin/python3 /home/klinker/klinkeroblik/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Збережи і активуй:
```bash
systemctl daemon-reload
systemctl enable klinkeroblik
systemctl start klinkeroblik
systemctl status klinkeroblik
```

Якщо бачиш `active (running)` — бот працює!

---

## 📱 Як користуватися

1. Відкрий Telegram, знайди свого бота (той що ти створив через @BotFather)
2. Натисни `/start`
3. Обери мову (🇺🇦 / 🇵🇱 / 🇷🇺)
4. Обери **"Я керівник фірми"**
5. Введи своє ім'я
6. Готово!

### Що далі:

1. **Створи бригаду**: Меню → 👷 Бригади → ➕ Створити бригаду
2. **Створи код запрошення**: Меню → 👷 Бригади → [твоя бригада] → 🔑 Створити код
3. **Надішлі код працівникам** — вони введуть його при реєстрації
4. **Створи об'єкт**: Меню → 🏗️ Об'єкти → ➕ Створити об'єкт
5. **Додай доми та елементи** до об'єкта
6. **Працівники можуть записувати роботу**: Меню → 📝 Записати роботу

---

## 📁 Структура файлів

```
klinkeroblik/
├── bot.py              # Головний файл
├── config.py           # Налаштування
├── database.py         # База даних (SQLite)
├── models.py           # Моделі даних
├── requirements.txt    # Залежності
├── .env                # Токен бота (НЕ коміть у git!)
├── data/               # Папка з БД (створиться автоматично)
├── locales/            # Мови
│   ├── uk.json
│   ├── pl.json
│   └── ru.json
├── handlers/           # Обробники команд
│   ├── start.py        # Реєстрація
│   ├── menu.py         # Головне меню
│   ├── work_entry.py   # Запис робіт
│   ├── reports.py      # Звіти
│   ├── brigades.py     # Бригади
│   ├── projects.py     # Об'єкти
│   ├── rates.py        # Розцінки
│   ├── work_types.py   # Типи робіт
│   └── settings.py     # Налаштування
└── utils/              # Допоміжні функції
    ├── i18n.py         # Мови
    ├── keyboards.py    # Клавіатури
    └── permissions.py  # Перевірка прав
```

---

## 🔧 Команди управління

```bash
# Переглянути логи
journalctl -u klinkeroblik -f

# Перезапустити бота
systemctl restart klinkeroblik

# Зупинити бота
systemctl stop klinkeroblik

# Перевірити статус
systemctl status klinkeroblik
```

---

## 💾 Бекапи

База даних знаходиться в `/home/klinker/klinkeroblik/data/klinkeroblik.db`

Для бекапу:
```bash
cp /home/klinker/klinkeroblik/data/klinkeroblik.db /backup/klinkeroblik-$(date +%Y%m%d).db
```

---

## ❓ Питання та проблеми

### Бот не запускається
- Перевір токен у `.env`
- Перевір логи: `journalctl -u klinkeroblik -n 50`

### Помилка "token is invalid"
- Перегенеруй токен через @BotFather: `/revoke` + `/newbot`
- Онови `.env` і перезавантаж бота

### Працівник не може приєднатися
- Переконайся що код запрошення ще дійсний (7 днів)
- Перевір що працівник обрав "У мене є код запрошення"

---

## 📞 Підтримка

Якщо щось не працює — пиши, розберемось!

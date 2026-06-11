# KlinkerOblik — деплой и создание клиентов (multi-бот на одном сервере)

> Этот документ описывает **восстановление и запуск** инстансов клиентов **отталкиваясь от сервера** (systemd + отдельная DB per client). Привязка к Claw — бизнес-слой, но запуск бота делается на уровне файлов/сервиса.

## 1) Структура на сервере
По умолчанию в ваших скриптах используется:

- Master/template код бота: `/home/klinker/klinkeroblik`
- База клиентов (папки): `/home/klinker/clients/<client_name>/`
- БД клиента: `/home/klinker/clients/<client_name>/data/klinkeroblik.db`
- systemd unit: `klinkeroblik-<client_name>.service`

## 2) Что значит “отдельная DB per client”
В каждом клиентском `.env` должно быть:

- `DATABASE_URL=sqlite+aiosqlite:////home/klinker/clients/<client_name>/data/klinkeroblik.db`

Ключевой момент: **DATABASE_URL должен быть абсолютным** (четыре слеша `////` в случае sqlite URL).

## 3) Скрипт развертывания клиента
Ваш деплой-скрипт:

- `./deploy_client.sh`

Запуск:

```bash
sudo ./deploy_client.sh <client_name> <bot_token> "<bot_display_name>"

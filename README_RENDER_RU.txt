FENIX ONLINE BOT — исправление для Render Web Service

Файлы:
- bot.py — Telegram long polling + HTTP health server (/health)
- db.py — SQLite, автоматическое создание каталога и файла
- requirements.txt — зависимости
- .env.example — пример переменных окружения

Render:
1. Runtime / Python: 3.12.11 (если настройка доступна).
2. Build Command: pip install -r requirements.txt
3. Start Command: python bot.py
4. Environment:
   BOT_TOKEN = действующий токен из @BotFather (без кавычек)
   ADMIN_IDS = числовой Telegram ID владельца
   CHANNEL_ID = числовой ID канала вида -100...
   CHANNEL_URL = ссылка приглашения/публичная ссылка канала
   DATABASE_PATH = fenix.sqlite3

Проверка HTTP:
Открой адрес Render-сервиса + /health. Должен вернуться JSON:
{"status":"ok","service":"fenix-online-bot"}

ВАЖНО:
- HTTP endpoint нужен Render Web Service; он не исправляет неверный BOT_TOKEN.
- При TelegramUnauthorizedError проверь/перевыпусти токен в @BotFather и обнови BOT_TOKEN в Render.
- SQLite создаётся автоматически в файловой системе сервиса. На бесплатном Render локальные данные
  не гарантированно сохраняются между перезапусками/деплоями. Для постоянного хранения нужен
  внешний PostgreSQL или постоянный диск.

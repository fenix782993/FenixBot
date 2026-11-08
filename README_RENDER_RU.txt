FENIX ONLINE — ОБНОВЛЁННЫЙ TELEGRAM-БОТ

В составе: bot.py, db.py, requirements.txt, assets/.

ВАЖНО ПРО БАЗУ ДАННЫХ:
SQLite-файл должен находиться на постоянном хранилище. На Render Free файловая система эфемерная: база теряется при перезапуске, spin-down или deploy. Переменная DATABASE_PATH сама по себе НЕ создаёт постоянное хранилище.

Если у сервиса Render платный тариф с Persistent Disk:
1. В Render открой свой Web Service -> Disks -> Add Disk.
2. Mount Path: /var/data.
3. Сохрани диск и дождись Deploy.
4. В Environment установи DATABASE_PATH=/var/data/fenix.sqlite3.
5. Проверь, что в логах указан именно /var/data/fenix.sqlite3.

Если сервис на Render Free: Persistent Disk недоступен. Бесплатный Render Postgres ограничен 30 днями, после чего база истекает. Для постоянного хранения нужна внешняя PostgreSQL с поддержкой в коде либо платный persistent disk. Не переключай DATABASE_PATH на PostgreSQL URL: текущий db.py работает с SQLite.

ФОТО:
Папка assets должна лежать рядом с bot.py, не внутри другой вложенной папки. При запуске бот пишет в логах список найденных файлов. Если папки нет в GitHub, фото не отправятся.

Render Web Service:
Build: pip install -r requirements.txt
Start: python bot.py
Environment: BOT_TOKEN, ADMIN_IDS, CHANNEL_ID, CHANNEL_URL, DATABASE_PATH
Python: 3.12.11

Публикация и рассылка: бот спрашивает Да/Нет для фото и URL-кнопки. Длинный текст с фото отправляется отдельными сообщениями, чтобы не превышать лимит подписи Telegram.

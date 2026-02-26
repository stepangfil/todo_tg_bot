# Запуск бота через systemd

1. Скопировать unit на малинку и включить сервис (путь к проекту — как на Pi):

   ```bash
   sudo cp deploy/todo-tg-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable todo-tg-bot
   sudo systemctl start todo-tg-bot
   ```

2. Проверить статус и логи:

   ```bash
   sudo systemctl status todo-tg-bot
   journalctl -u todo-tg-bot -f
   ```

3. Если проект лежит не в `/home/stronguser/bots/todo_tg_bot` — перед копированием отредактируй пути в `todo-tg-bot.service`: `User`, `Group`, `WorkingDirectory`, `EnvironmentFile`, `ExecStart`.

4. В каталоге проекта должен быть файл `.env` с переменной `BOT_TOKEN=...` (и при необходимости `TZ_NAME`, `DB_PATH`).

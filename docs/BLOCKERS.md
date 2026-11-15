# BLOCKERS — things only the owner can provide

| # | Needed | Why | Exact steps | Currently faked |
|---|---|---|---|---|
| 1 | **Telegram bot token + username** | Real Telegram notifications and account linking | 1) In Telegram open @BotFather → `/newbot` → copy the token. 2) Put `TELEGRAM_BOT_TOKEN=<token>` and `TELEGRAM_BOT_USERNAME=<bot_username_without_@>` in `.env` (prod: server `.env`). 3) Start the `bot` service (`python -m app.telegram_bot`) next to the worker. 4) In the app press «Telegramni ulash». | Transport is behind `Notifier`; without a token `DisabledNotifier` marks notifications `skipped`. Tests use `FakeNotifier`; the aiogram `/start` handler is tested with a stub message. The real network call to Telegram was **not** run. |

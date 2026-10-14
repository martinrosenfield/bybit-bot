# Миграция Bybit-бота на VPS (Нидерланды)

Статус: план, дата составления 14.10.2026. Решение о миграции принято 14.10
(делегировано Kimi): страна — **Нидерланды** (тот же регион, что рабочий VPN;
минимальный риск антибот-лимита Bybit; Швеция уже попадала под 403).

## Зачем

- Три инцидента связи Mac→VPN→Bybit за сутки (13.10 ночь, 13.10 reboot,
  14.10 утро 07:36–08:01 МСК). На VPS свой стабильный канал, без VPN-клиента.
- Mac больше не должен бодрствовать (крышка, зарядка, сон).
- Ключи на VPS живут в защищённом файле с правами 600 — переживают ребут,
  в отличие от RAM на Mac.

## Провайдер

Критерии: локация Нидерланды (Amsterdam), Ubuntu 24.04, минимум 1 GB RAM
(боту хватает ~50 MB), оплата помесячно. Подходят: Hetzner (NB: блокирует
трейдинг-ботов? — проверить ToS), DigitalOcean AMS, Vultr Amsterdam,
Contabo. **Перед оплатой проверить у провайдера, разрешены ли торговые боты.**

## Шаги

1. Создать VPS (Amsterdam, Ubuntu 24.04), включить автоматические бэкапы.
2. Закрепить IP за VPS (floating/reserved IP, чтобы API-ключ привязать к IP).
3. На Bybit перевыпустить demo-ключ с привязкой к IP VPS (минимальные права:
   Read/Write, только деривативы — как сейчас).
4. Залить код: `git clone https://github.com/martinrosenfield/bybit-bot.git`
   в `/opt/bybit-bot` (ветка main, сверить `git log` с репозиторием).
5. `pip3 install "pybit>=5.8"` (системный pip или venv).
6. Создать `/etc/bybit-bot.env` (права 600, владелец root):

   ```
   BYBIT_API_KEY=...
   BYBIT_API_SECRET=...
   CONFIRM_LIVE=YES
   ```

7. Установить systemd-юнит (см. `deploy/bybit-bot.service`):

   ```bash
   sudo cp deploy/bybit-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now bybit-bot
   ```

8. Проверки:
   - `systemctl status bybit-bot` — active (running)
   - `journalctl -u bybit-bot -f` — PREFLIGHT с equity ~185k, leverage x3
   - в логе `planned_risk` на каждом входе ≤ 0,25% equity
   - `curl -s https://api-demo.bybit.com/v5/market/time` с VPS → retCode 0
9. Параллельная работа: Mac-экземпляр гасим ТОЛЬКО после 24 часов чистой
   работы VPS-экземпляра (проверка каждые несколько часов по стандартному
   блоку диагностики). Иначе оба экземпляра могут дублировать входы.
10. Обновить STATUS_SYNC.md: миграция выполнена, Mac-контур остановлен.

## Эксплуатация после миграции

- Диагностика по SSH: `journalctl -u bybit-bot --since today | tail -20`
  и `cat /opt/bybit-bot/logs/events_*.jsonl`.
- Обновление: `git pull` + `systemctl restart bybit-bot` (аналог шага 1
  из LAUNCH.md).
- Автоматические обновления ОС: `unattended-upgrades` (только security).
- Бэкапы: ежедневный `logs/` и `events_*.jsonl` через cron → rsync/object storage.
- Уведомления о падении: простейший cron-страж (раз в 5 минут проверяет
  systemctl is-active, при DOWN шлёт письмо через ssmtp) — до внедрения
  полноценных Telegram-уведомлений.

## Откат

Если VPS-вариант хуже: включить Mac-контур по LAUNCH.md (шаги 2–4),
`systemctl stop bybit-bot && systemctl disable bybit-bot`. Возврат занимает
~10 минут, данные (журналы сделок) не теряются — они на GitHub-независимом
диске брокера + локальные копии.

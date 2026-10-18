# Миграция Bybit-бота на VPS (Нидерланды)

Статус: **готово к созданию VPS** (обновление 18.10.2026, Kimi). Решение о
миграции принято 14.10: страна — **Нидерланды** (тот же регион, что рабочий
VPN; минимальный риск антибот-лимита Bybit; Швеция уже попадала под 403).

## Провайдер — РЕШЕНО: Vultr Amsterdam

- **Vultr**, Cloud Compute Regular, Amsterdam: 1 vCPU / 1 GB RAM / 25 GB SSD,
  $5/мес (бэкапы +20% = $6/мес, опционально). Регион Amsterdam есть в
  списке локаций Vultr. Помесячная оплата, почасовой биллинг с месячным кэпом.
- **Hetzner — ИСКЛЮЧЁН.** Формально запрещён только майнинг, но поддержка
  трактует запрет как «любые crypto-related приложения»; по опыту сообщества
  торговые боты там блокируют. Не рискуем.
- DigitalOcean AMS — запасной вариант ($6/мес за 1 GiB), шаги идентичны.
- Contabo — не рекомендуется: агрессивный оверселлинг CPU, для торгового
  бота, где важен стабильный цикл, лишний риск.

Боту нужно ~50–80 МБ RAM; 1 GB с запасом. Python 3.12 (Ubuntu 24.04) +
venv (PEP 668 не даёт ставить в системный pip — поэтому venv, systemd
юнит уже настроен на `/opt/bybit-bot/venv/bin/python3`).

## Что сделано (Kimi, 18.10)

- `scripts/vps_setup.sh` — one-shot скрипт развёртывания: apt-пакеты,
  системный юзер `bybitbot`, клон в `/opt/bybit-bot`, venv + pybit>=5.8,
  runtime_state.json из example, права, интерактивный ввод ключей
  (скрытый) в `/etc/bybit-bot.env` (600, root), systemd-юнит, UFW
  (только SSH), unattended-upgrades, финальная проверка журнала.
- `deploy/bybit-bot.service` — ExecStart на venv-python,
  ReadWritePaths добавлен `runtime_state.json` (ProtectSystem=strict).

## Чек-лист Дмитрия (порядок важен)

1. **Vultr:** регистрация → Deploy → Cloud Compute → Regular →
   Amsterdam → Ubuntu 24.04 → $5/mo. Добавить свой SSH-ключ при создании.
2. **Записать публичный IP** VPS из панели Vultr.
3. **Bybit demo-кабинет:** создать **НОВУЮ** пару demo-ключей
   (Read/Write, только деривативы) с IP-whitelist = IP VPS из шага 2.
   Старые ключи Mac-контура **не трогать** — они продолжают работать
   параллельно 24 ч.
4. **SSH на VPS** и запуск:
   ```bash
   curl -sSL https://raw.githubusercontent.com/martinrosenfield/bybit-bot/main/scripts/vps_setup.sh -o vps_setup.sh
   less vps_setup.sh   # прочитать, что выполняется
   sudo bash vps_setup.sh
   ```
   Скрипт спросит BYBIT_API_KEY / BYBIT_API_SECRET — вставить новые
   (ввод скрыт; история shell их не сохраняет).
5. **Проверки** (шаг 8 скрипта выводит журнал):
   - `systemctl is-active bybit-bot` → active
   - `journalctl -u bybit-bot -f` → PREFLIGHT с equity ~183k, leverage x3
   - `curl -s https://api-demo.bybit.com/v5/market/time` → retCode 0
   - `planned_risk` на каждом входе ≤ 0,25% equity
6. **Параллельная работа 24 ч.** Mac-экземпляр гасим ТОЛЬКО после 24 часов
   чистой работы VPS (проверка journalctl каждые несколько часов). Иначе
   оба экземпляра могут дублировать входы. При рестарте Mac-контура не
   забыть: после `git pull` конфиг с диска перечитывается (дефект 17.10).
7. Обновить STATUS_SYNC.md: миграция выполнена, Mac-контур остановлен.

## Эксплуатация после миграции

- Диагностика по SSH: `journalctl -u bybit-bot --since today | tail -20`
  и `cat /opt/bybit-bot/logs/events_*.jsonl`.
- Обновление: `cd /opt/bybit-bot && sudo -u bybitbot git pull &&
  sudo systemctl restart bybit-bot` (~30 с простоя, Restart=always
  поднимет процесс при падении сам).
- Автоматические security-обновления ОС: уже включены скриптом.
- Бэкапы: snapshots Vultr (+$1/мес) + `logs/` и `events_*.jsonl`
  при желании через cron → rsync/object storage.
- Уведомления о падении: cron-страж (раз в 5 минут `systemctl is-active`,
  при DOWN — письмо через ssmtp) — до внедрения Telegram-уведомлений.
  Не забыть: day_realized_pnl не видит серверных закрытий (issue №4) —
  на VPS это тот же дефект, что и на Mac.

## Откат

Если VPS-вариант хуже: включить Mac-контур по LAUNCH.md (шаги 2–4),
`sudo systemctl stop bybit-bot && sudo systemctl disable bybit-bot`.
Возврат занимает ~10 минут, данные (журналы сделок) не теряются — они на
стороне брокера + локальные копии. Две пары ключей (Mac + VPS) позволяют
переключаться мгновенно, без перевыпуска.

## Зачем (неизменно)

- Три инцидента связи Mac→VPN→Bybit за сутки (13.10 ночь, 13.10 reboot,
  14.10 утро). На VPS свой стабильный канал, без VPN-клиента.
- Mac больше не должен бодрствовать (крышка, зарядка, сон). Ребут 18.10
  дал 40 мин ручного простоя.
- Ключи на VPS живут в защищённом файле с правами 600 — переживают ребут,
  в отличие от RAM на Mac.

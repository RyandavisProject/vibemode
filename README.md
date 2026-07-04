# Vibemode Overlay 2.6

Компактный desktop-overlay для лимитов Vibemode API. Работает локально на **Windows** и **macOS**, читает данные из кабинета Vibemode через локальную браузерную сессию Chrome/Playwright и показывает остатки, прогресс и время до сброса лимитов.

## Что показывает

- тариф и время до окончания подписки;
- остатки и прогресс по окнам **5 часов** и **7 дней**;
- реальное время до сброса окон лимитов из Vibemode API;
- дневной лимит расхода, если он задан вручную;
- время последнего обновления и меню действий.

## Скриншоты

<table>
  <tr>
    <td><img src="docs/screenshots/overlay-tooltip.png" alt="Windows оверлей Vibemode Overlay 2.6" /></td>
    <td><img src="docs/screenshots/overlay-menu.png" alt="Windows меню Vibemode Overlay 2.6" /></td>
  </tr>
  <tr>
    <td align="center">Windows overlay</td>
    <td align="center">Windows menu</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/macos-menu-bar.png" alt="macOS menu bar" width="320" /></td>
    <td><img src="docs/screenshots/macos-popover.png" alt="macOS popover" width="320" /></td>
  </tr>
  <tr>
    <td align="center">macOS menu bar</td>
    <td align="center">macOS popover</td>
  </tr>
</table>

## Что нового в 2.6

- macOS: установка из Git/ZIP создаёт `Vibemode.command` на рабочем столе.
- Повторный запуск desktop-ярлыка больше не перезапускает overlay и не переоткрывает ЛК.
- Первый login prompt больше не запускает лишний hidden recovery перед входом.
- Проверки: `tests.test_browser_reader`, `tests.test_reader_worker`, `compileall`.

## Установка

### Windows: из Git

```powershell
git clone https://github.com/RyandavisProject/vibemode.git
cd vibemode
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

### Windows: из ZIP-архива

1. Открой [Releases](https://github.com/RyandavisProject/vibemode/releases).
2. Скачай `vibemode-v2.6.zip` из последнего релиза.
3. Распакуй архив, например в `C:\Vibemode`.
4. Запусти:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Запуск:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-overlay.ps1
```

### macOS: из Git

```bash
git clone https://github.com/RyandavisProject/vibemode.git
cd vibemode
bash scripts/install.sh
```

Установка создаёт ярлык `Vibemode.command` на рабочем столе. Если overlay уже запущен, повторный запуск ярлыка не перезапускает ЛК.

### macOS: из ZIP-архива

1. Открой [Releases](https://github.com/RyandavisProject/vibemode/releases).
2. Скачай `vibemode-v2.6.zip` из последнего релиза.
3. Распакуй архив и в папке проекта запусти:

```bash
bash scripts/install.sh
```

После установки на рабочем столе появится `Vibemode.command`.

Запуск:

```bash
bash scripts/run-overlay.sh
```

## Первый вход

1. Overlay открывает локальный профиль Chrome/Playwright.
2. Если Vibemode просит вход, появится отдельное окно браузера.
3. Войди обычным способом на сайте Vibemode.
4. После успешного входа окно браузера скрывается, а overlay продолжает читать данные из той же локальной сессии.

## Приватность

- Overlay работает локально и не отправляет твои лимиты, cookies или данные аккаунта в стороннюю аналитику.
- Пароль Vibemode не вводится в интерфейс overlay.
- Cookies и сессия остаются в локальной папке:

```text
~/.neurogate-usage-overlay/browser-profile
~/.neurogate-usage-overlay/overlay-state.json
~/.neurogate-usage-overlay/usage-daily.json
```

Эту папку нельзя публиковать или передавать другим людям: там может быть твоя браузерная сессия.

## Управление

- Клик по overlay/menu bar открывает меню действий.
- `Обновить` — принудительно перечитать лимиты.
- `Лимит на день` — вручную задать дневной расход.
- `Показывать ЛК` / `Закрывать ЛК` — открыть или скрыть окно кабинета.
- `Сменить аккаунт` — сбросить локальный профиль overlay и открыть чистый вход.
- `Интервал` — переключить частоту обновления.

## Разработка и проверки

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
python -m unittest tests.test_browser_reader tests.test_overlay -v
python -m neurogate_usage_overlay --once
```

Диагностика доступных endpoint'ов Vibemode API:

```powershell
python scripts\check-api-contract.py
```

API-ключ, если используется для диагностики, вводится скрыто или через переменную окружения и не сохраняется проектом.

## История

### 2.6 — 04-07-2026

- macOS installer теперь создаёт `Vibemode.command` на рабочем столе.
- Desktop-ярлык запускает overlay в режиме без перезапуска уже работающей копии.
- Убрано лишнее hidden recovery на первом login prompt, чтобы ЛК не открывался повторно.

### 2.5 — 03-07-2026

- macOS menu bar/popover проверен на рабочем запуске после последних правок.
- Исправлена ширина macOS popover: контент занимает всё окно, отступы слева и справа одинаковые.
- Подтверждено чтение лимитов и времени сброса через Vibemode API.

### 2.4 — 30-06-2026

- Прозрачные округлённые углы Windows overlay.
- Восстановление чтения лимитов после сна без удаления browser profile.
- Реальное время сброса окон из `/client/me`.
- Честная подсказка дневного лимита: без реального reset time значение не предлагается.
- Atomic JSON state/history, hardening popover server, расширенные тесты.

### 2.3 — 27-06-2026

- Windows overlay визуально приближен к macOS-попапу.
- Обновлены меню, tooltip, окно дневного лимита и верхние Windows-скриншоты.
- Добавлена безопасная диагностика API contract.

### 2.2 — 27-06-2026

- Улучшены macOS menu bar/popover, дневной лимит, update scripts и GitHub checks.

Полная история изменений: [CHANGELOG.md](CHANGELOG.md).

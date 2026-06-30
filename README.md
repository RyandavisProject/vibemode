# Vibemode 2.4

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
    <td><img src="docs/screenshots/overlay-tooltip.png" alt="Windows оверлей Vibemode 2.4" /></td>
    <td><img src="docs/screenshots/overlay-menu.png" alt="Windows меню Vibemode 2.4" /></td>
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

## Что нового в 2.4

- Windows: прозрачные округлённые углы overlay на светлом и тёмном фоне.
- Windows: аккуратнее 1x/2x UI, прогресс-бары, меню, tooltip и окно дневного лимита.
- После сна overlay умеет восстановить hidden browser context без удаления профиля и без лишнего heartbeat.
- Время сброса `5ч` и `7д` берётся из настоящих полей `/client/me`: `window5HoursEndsAt` и `window7DaysEndsAt`.
- Автоподсказка дневного лимита больше не придумывает цифру, если нет реального времени сброса 7-дневного окна.
- State/history пишутся атомарнее, popover server усилен token-защитой и лимитом POST body.
- Проверки проекта расширены до `172 tests OK`.

## Установка

### Windows

```powershell
git clone https://github.com/RyandavisProject/vibemode.git
cd vibemode
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Запуск:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-overlay.ps1
```

### macOS

```bash
git clone https://github.com/RyandavisProject/vibemode.git
cd vibemode
bash scripts/install.sh
```

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

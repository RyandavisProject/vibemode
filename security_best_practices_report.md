# Комплексный аудит Vibemode

Дата: 28-06-2026
Режим: senior engineering + QA + UI/UX + security review
Границы: защитный аудит локального desktop-overlay без DDoS, обхода авторизации, кражи данных, доступа к чужой информации, публикации, деплоя или push.

## Короткий статус

Проект в рабочем состоянии. Полный локальный check после исправлений проходит: `scripts/check.ps1` -> 165 tests OK, `git diff --check` -> PASS. Windows overlay визуально проверен на светлом и тёмном фоне: крайние пиксели скруглённых углов совпадают с фоном, прогресс-линии ровные.

Критических проблем уровня "остановить проект" не найдено. Две проблемы выше среднего уже исправлены в рамках аудита:

- Win32 transparent-corner hardening: typed `ctypes` API, region clipping больше не зависит от DWM rounded preference.
- macOS local popover server: корневой HTML теперь требует token, как `/data` и `/action/*`.

Коммит и push не выполнялись.

## 10 проблем и рисков

### 1. Win32 region/color-key API был хрупким на 64-bit Windows

- Серьёзность: High.
- Где находится: `src/neurogate_usage_overlay/overlay.py`, `_apply_rounded_window_region`.
- Почему это проблема: свежий Win32-код вызывал `GetWindowLongPtrW`, `SetWindowLongPtrW`, `SetLayeredWindowAttributes`, `CreateRoundRectRgn`, `SetWindowRgn` без `argtypes/restype`. На 64-bit Windows это может привести к неверной передаче HWND/LONG_PTR. Плюс ошибка в best-effort DWM вызове могла прервать установку реальной window region.
- Как исправлено: добавлены typed Win32 signatures, DWM preference вынесен в отдельный best-effort шаг, region clipping применяется независимо от DWM.
- Как проверить: `tests.test_overlay`, `scripts/check.ps1`, визуальный light/dark screenshot + pixel-check углов.

### 2. Корневой HTML macOS popover server отдавал snapshot/action_token без token-проверки

- Серьёзность: High.
- Где находится: `src/neurogate_usage_overlay/popover_server.py`, `_Handler.do_GET`.
- Почему это проблема: `/data` и `/action/*` были защищены token, но `/` отдавал HTML с embedded data и `action_token` без проверки. Сервер слушает только `127.0.0.1` на случайном порту, поэтому риск ограничен локальной машиной, но это всё равно слабая граница.
- Как исправлено: `/` и `/index.html` теперь требуют token; `get_url()` уже передаёт token в WebView URL.
- Как проверить: `tests.test_popover_server`, запрос `/` без token -> 403, запрос `/?token=...` -> HTML.

### 3. POST body в popover server не ограничен размером

- Серьёзность: Medium.
- Где находится: `src/neurogate_usage_overlay/popover_server.py`, `_read_json_body`.
- Почему это проблема: локальный клиент с правильным token или локальный процесс может прислать чрезмерно большой JSON и занять память/поток. Loopback и token снижают риск, но лимит всё равно нужен.
- Как исправлено: action/resize POST ограничены 16 KB, oversized body отклоняется кодом 413 до вызова callback.
- Как проверить: unit-тест на большой `Content-Length`, `tests.test_popover_server`, `scripts/check.ps1`.

### 4. State/history файлы пишутся неатомарно

- Серьёзность: Medium.
- Где находится: `overlay.py` state helpers, `history.py` `DailyUsageStore._save`.
- Почему это проблема: сон/краш/выключение в момент записи может оставить битый `overlay-state.json` или `usage-daily.json`. Сейчас код переживает это через fallback `{}`, но пользователь может потерять позицию, интервал, тему или дневной лимит.
- Как исправлено: добавлен `json_store.py`; запись идёт во временный файл в той же папке, затем заменяется через `os.replace`.
- Как проверить: `tests.test_json_store`, corrupted state/history tests, `scripts/check.ps1`.

### 5. Нет автоматического visual regression для Windows overlay

- Серьёзность: Medium.
- Где находится: Windows overlay rendering, `overlay.py`, preview workflow.
- Почему это проблема: текущую проблему углов поймали глазами. Unit-тесты проверяют атрибуты Tk, но не итоговые пиксели на светлом/тёмном фоне, 1x/2x и daily-limit высоту.
- Как исправить: добавить локальный screenshot/pixel harness для light/dark, 1x/2x, daily-limit on/off, с понятными tolerance-точками.
- Как проверить: отдельный визуальный check script + сохранённые PNG artifacts.

### 6. macOS AppKit/WebKit UI не проверяется визуально в этом окружении

- Серьёзность: Medium.
- Где находится: `src/neurogate_usage_overlay/macos_popover.py`, `MenuBarOverlay` в `overlay.py`.
- Почему это проблема: серверная часть и macOS-safe tests проходят, но реальный NSStatusItem/NSPopover/WKWebView не запускался на macOS в рамках этого аудита. Возможны проблемы с размером popover, bridge resize, кликами, theme и status item.
- Как исправить: добавить ручной macOS release gate и/или macOS screenshot smoke на GitHub Actions/self-hosted Mac.
- Как проверить: запуск `.app` на macOS, popover screenshot, клики refresh/interval/theme/daily-limit/restart.

### 7. Data layer всё ещё сильно зависит от текущей формы Vibemode cabinet

- Серьёзность: Medium.
- Где находится: `browser_reader.py`, `_read_vibemode_api_snapshot`, text parser fallback.
- Почему это проблема: основной режим читает token из `localStorage` кабинета и вызывает текущие API endpoints. Изменение ключа session storage, URL или payload может тихо вернуть fallback/старые данные.
- Как улучшено сейчас: чистые API/text parsing helpers вынесены в `vibemode_parser.py`; Playwright/session lifecycle оставлен в `browser_reader.py`.
- Как проверить: `tests.test_browser_reader`, существующие parser/API fallback tests, `scripts/check.ps1`.

### 8. Timeout worker не перезапускает зависший reader context

- Серьёзность: Medium.
- Где находится: `reader_worker.py`, `_call`, `WORKER_CALL_TIMEOUT_SECONDS`.
- Почему это проблема: `future.cancel()` не останавливает уже выполняющуюся Playwright-команду в worker thread. UI получает timeout, но worker может оставаться занят, пока underlying browser operation не вернётся.
- Как исправлено: после timeout текущая очередь worker помечается retired, следующий вызов идёт через новый worker; `keep_browser_open` сохраняется при restart.
- Как проверить: `tests.test_reader_worker`, тест с зависшим reader, затем успешный refresh после recovery.

### 9. Release update доверяет ZIP/checksum, но не имеет подписи артефакта

- Серьёзность: Low/Medium.
- Где находится: `scripts/update-and-restart.ps1`, `scripts/update-and-restart.sh`, `update_checker.py`.
- Почему это проблема: SHA256 защищает целостность скачанного ZIP, но если checksum поставляется рядом с release asset, это не равно независимой подписи релиза.
- Как исправить: добавить подписанные release artifacts или cosign/minisign-подпись; документировать release verification.
- Как проверить: тест updater на обязательную подпись/ключ, ручной release dry-run.

### 10. Локальные debug logs всё ещё содержат чувствительные usage metadata

- Серьёзность: Low/Medium.
- Где находится: `browser_reader.py` `_write_debug`, `overlay.py` `_write_ui_log`, `~/.neurogate-usage-overlay/*.log`.
- Почему это проблема: raw page text и секреты не пишутся, но account name, remaining, usage windows и URL остаются локально. Для личного desktop app это допустимо, но для support bundle нужен redaction mode.
- Как исправить: добавить команду "clear diagnostics" и redacted diagnostics export без account/URL/usage numbers по умолчанию.
- Как проверить: тест redacted snapshot/log export, ручная проверка логов.

## Быстрые исправления на 1-2 часа

- Сделано: typed Win32 API + независимый DWM best-effort.
- Сделано: token protection для `/` и `/index.html` popover server.
- Сделано: ограничен POST body popover server.
- Сделано: атомарная запись `overlay-state.json` и `usage-daily.json`.
- Отложено: отдельный script для повторяемого Windows light/dark pixel-check.

## Глубокие архитектурные улучшения

- Вынести Vibemode API чтение в отдельный adapter с contract fixtures.
- Сделать visual regression harness для Windows overlay и macOS popover.
- Добавить recovery-стратегию для зависшего Playwright worker.
- Добавить signed release verification.
- Сделать privacy-safe diagnostics export.

## Что нельзя проверить без доступа

- Реальный вход, смена аккаунта и live Network/console кабинета Vibemode: нужен владелец/его сессия или тестовый аккаунт.
- Реальный macOS NSStatusItem/NSPopover/WebKit UI: нужен запуск на macOS.
- End-to-end update с настоящим GitHub Release ZIP и sidecar/signature: нужен опубликованный release artifact.
- Поведение после сна/пробуждения на реальной машине владельца: нужен long-running ручной сценарий.

## Реально запущенные проверки

- `git status --short --branch`: branch `main`, dirty files перечислены ниже.
- `git diff HEAD -- src/neurogate_usage_overlay/overlay.py tests/test_overlay.py`: проверен свежий Win32/Tk diff после последнего commit.
- `git diff --check`: PASS.
- `powershell -ExecutionPolicy Bypass -File scripts\check.ps1`: PASS, 165 tests OK.
- `python -m unittest tests.test_overlay -v`: PASS, 60 tests OK.
- `python -m unittest tests.test_popover_server -v`: PASS, 6 tests OK.
- `python -m unittest tests.test_browser_reader tests.test_reader_worker tests.test_overlay -v`: PASS, 114 tests OK.
- Security scan по известным secret-паттернам: реальных секретов не найдено; были только code/test false positives.
- Windows visual check: light/dark screenshots saved, edge pixels match background.

## Пропущенные проверки

- Настоящий macOS UI запуск: пропущен, потому что аудит выполнялся на Windows.
- Live Vibemode login/API/Network: пропущен, чтобы не трогать приватную сессию и не печатать токены/cookies.
- Real release update: пропущен, потому что commit/push/release/deploy запрещены без отдельного разрешения.

## GOAL

Устранить найденные проблемы Vibemode audit:

- исправлены все Critical/High;
- Medium либо исправлены, либо явно отложены с причиной;
- `scripts/check.ps1` проходит;
- `git diff --check` чистый;
- Windows overlay визуально проверен на светлом и тёмном фоне;
- нет утечек секретов в логах/README/тестах;
- рабочее дерево понятно: изменения перечислены, ничего лишнего не тронуто.

## План исправления

1. Завершено: исправить Win32 typed API / DWM fallback.
2. Завершено: закрыть unauthenticated root HTML popover server.
3. Завершено: ограничить размер POST body в popover server.
4. Завершено: атомаризировать запись state/history.
5. Отложено: оформить Windows visual pixel-check как script/test artifact.
6. Затем: macOS manual smoke checklist и/или CI screenshot smoke.
7. Частично завершено: parser helpers вынесены, worker recovery добавлен; contract fixtures остаются следующим архитектурным этапом.

## Рабочее дерево после аудита

Изменены локально, без commit/push:

- `src/neurogate_usage_overlay/overlay.py`
- `src/neurogate_usage_overlay/popover_server.py`
- `tests/test_overlay.py`
- `tests/test_popover_server.py`

## Статус после refactor pass 29-06-2026

Рефакторинг выполнен поэтапно, без commit/push и без удаления `browser-profile`, state или history.

Закрыто кодом и тестами:

- High #1 Win32 region/color-key: Win32 API вынесен в `win32_window.py`, добавлены typed signatures, DWM preference стал best-effort, region clipping применяется отдельно. Проверки: `tests.test_win32_window`, `tests.test_overlay`, visual light/dark screenshot/pixel check.
- High #2 popover root token: `/`, `/index.html`, `/data`, `/action/*`, `/resize/*` проходят token-gate; неправильный метод после token-check возвращает 405.
- Medium #3 POST body limit: action/resize POST ограничены 16 KB, oversized body возвращает 413 и callback не вызывается.
- Medium #4 state/history atomic write: `json_store.py` пишет JSON через temporary file + `os.replace`; corrupted/interrupted state покрыт тестами.
- Windows UI 2x header fit: длинный account/plan status больше не налезает на правую кнопку интервала; добавлен regression-test для large scale.
- Medium #7 data parsing maintainability: чистые Vibemode API/text helpers вынесены в `vibemode_parser.py`; Playwright/login lifecycle оставлен в `browser_reader.py`.
- Medium #8 reader recovery: `ThreadedUsageReader` после timeout запускает новый worker для следующих команд и сохраняет `keep_browser_open`; hidden/залипший visible-login browser после ложного login/stale пересобирает Playwright context с тем же профилем до показа входа, а force refresh обходит in-memory recovery cooldown.

Явно отложено с причиной:

- Medium #5 automatic Windows visual regression harness: ручная visual/pixel проверка light/dark уже выполнена, но отдельный воспроизводимый script/test artifact еще не добавлен. Причина отсрочки: это отдельная tooling-задача поверх уже проверенного UI.
- Medium #6 real macOS AppKit/WebKit visual smoke: нужен запуск на macOS. В текущем Windows-окружении проверены только server/macOS-safe tests.
- Low/Medium #9 signed release verification: отложено до отдельного release-signing этапа, потому что требует решения по ключам/signing workflow.
- Low/Medium #10 privacy-safe diagnostics export: raw text/secrets не пишутся, но redacted support export является отдельной продуктовой задачей.

Финальные проверки этого refactor pass:

- `git diff --check`: PASS.
- `powershell -ExecutionPolicy Bypass -File scripts\check.ps1`: PASS, 165 tests OK.
- Targeted checks: `tests.test_browser_reader`, `tests.test_reader_worker`, `tests.test_popover_server`, `tests.test_history`, `tests.test_json_store`, `tests.test_overlay`, `tests.test_win32_window` проходили на соответствующих этапах.
- Секреты не печатались; debug tests подтверждают, что raw portal text не попадает в debug log.

Рабочее дерево после refactor pass:

- `src/neurogate_usage_overlay/browser_reader.py`
- `src/neurogate_usage_overlay/history.py`
- `src/neurogate_usage_overlay/json_store.py`
- `src/neurogate_usage_overlay/overlay.py`
- `src/neurogate_usage_overlay/popover_server.py`
- `src/neurogate_usage_overlay/reader_worker.py`
- `src/neurogate_usage_overlay/vibemode_parser.py`
- `src/neurogate_usage_overlay/win32_window.py`
- `tests/test_history.py`
- `tests/test_json_store.py`
- `tests/test_overlay.py`
- `tests/test_popover_server.py`
- `tests/test_reader_worker.py`
- `tests/test_win32_window.py`
- `security_best_practices_report.md`

# Комплексный аудит NeuroGate API Overlay

Дата: 15-06-2026
Объект: локальный Windows-оверлей `neurogate-overlay`
Режим: defensive senior engineering + QA + security review
Границы: без DDoS, обхода авторизации, кражи данных, доступа к чужой информации или атакующих проверок

## Короткое резюме

Проект в целом построен безопасно для своего класса: это local-first Windows-приложение, которое не забирает пароль, не отправляет cookies владельцу проекта, хранит сессию в локальном Chrome/Playwright profile и ограничивает собственные логи.

Самые важные проблемы были не в прямой утечке данных, а в устойчивости долгой работы: накопление canvas callback-команд, шумное перетаскивание окна, рост browser cache, отсутствие верхней границы у worker queue и мягкая политика checksum для ZIP update. Эти пункты уже исправлены локально в текущем рабочем дереве. Проверка проекта проходит: `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1` -> `106 tests OK`.

## 10 конкретных проблем или рисков

### 1. Накопление Canvas callback-команд при каждом render

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/overlay.py:187`, `src/neurogate_usage_overlay/overlay.py:1269`.
- Почему это проблема: раньше tooltip/daily-limit обработчики навешивались заново при каждом `_render()`. Через час регулярных обновлений Tk мог накопить callback-команды, и события мыши начинали обрабатываться рывками.
- Как исправить: биндинги должны быть одноразовыми при старте, а render должен менять только canvas-элементы и данные tooltip.
- Статус: исправлено. Добавлен стабильный тег `tooltip-target`, словарь tooltip-текстов и тест `test_render_does_not_rebind_canvas_tags`.

### 2. Перетаскивание окна генерировало слишком много UI-событий

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/overlay.py:99`, `src/neurogate_usage_overlay/overlay.py:218`.
- Почему это проблема: частый `geometry()` плюс `<Configure>` создавали шторм событий и сохранений позиции.
- Как исправить: считать позицию по screen coordinates, применять перемещение с частотой кадра и сохранять координаты только после отпускания мыши.
- Статус: исправлено. Drag ограничен через `DRAG_FRAME_MS = 16`, сохранение позиции во время drag отключено.

### 3. Worker queue могла бесконтрольно ждать или копить команды

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/reader_worker.py:13`, `src/neurogate_usage_overlay/reader_worker.py:67`.
- Почему это проблема: при зависании Playwright/Chrome вызовы worker могли ждать слишком долго. Это особенно опасно для команд из UI, например переключения режима браузера.
- Как исправить: ограничить очередь, добавить timeout на worker calls, отменять просроченные future и быстро сообщать ошибку.
- Статус: исправлено. Добавлены `WORKER_QUEUE_MAXSIZE = 4`, `WORKER_CALL_TIMEOUT_SECONDS = 90`, тесты на timeout и queue full.

### 4. Chrome/Playwright profile может расти за счёт cache

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/browser_reader.py:22`, `src/neurogate_usage_overlay/browser_reader.py:134`.
- Почему это проблема: cookies/session нужны, но `Cache`, `Code Cache`, `GPUCache`, shader-cache и service-worker cache могут расти и влиять на запуск/отзывчивость.
- Как исправить: чистить только безопасные cache-директории и ограничить disk/media cache Chrome, не трогая `Cookies`, `Local Storage`, `Session Storage`.
- Статус: исправлено. Текущая runtime-папка около `31.2 MB`; добавлен тест, что cache чистится, а session storage остаётся.

### 5. Update flow зависит от GitHub Release metadata

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/update_checker.py:84`, `src/neurogate_usage_overlay/update_checker.py:97`, `src/neurogate_usage_overlay/overlay.py:810`.
- Почему это проблема: если GitHub API недоступен, release отсутствует или asset не прикреплён, пользователи не увидят корректное обновление.
- Как исправить: держать graceful fallback, явно документировать, что полноценный auto-update требует GitHub Release asset ZIP + checksum.
- Статус: частично закрыто. Код безопасно возвращает `None` при сетевых ошибках; нужен дисциплинированный release-процесс.

### 6. ZIP update без checksum может продолжиться с предупреждением

- Серьёзность: Medium.
- Где: `scripts/update-and-restart.ps1:65`, `scripts/update-and-restart.ps1:206`.
- Почему это проблема: updater умеет SHA256, но если checksum не предоставлен, он продолжает работу. Это удобно для dev, но слабее для публичного канала обновлений.
- Как исправить: для публичных ZIP-релизов требовать checksum обязательно, а режим без checksum оставить только для локальной разработки через явный флаг.
- Статус: исправлено. ZIP update без checksum теперь останавливается; обход возможен только явно через `-AllowUnverifiedZip` или `NEUROGATE_ALLOW_UNVERIFIED_UPDATE=1` для локальной разработки.

### 7. PowerShell update/restart запускается из приложения

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/overlay.py:839`, `scripts/update-and-restart.ps1`.
- Почему это проблема: запуск внешнего скрипта всегда повышает риск regressions и требует аккуратной проверки аргументов/пути.
- Как исправить: держать fixed script path внутри repo, не использовать shell interpolation, валидировать URL/checksum и покрывать update flow тестами.
- Статус: закрыто на текущем уровне. `Popen` использует список аргументов, script path берётся из проекта, а ZIP update теперь требует checksum по умолчанию.

### 8. Парсер зависит от текста и DOM сайта NeuroGate

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/parser.py`, `src/neurogate_usage_overlay/browser_reader.py:441`, `src/neurogate_usage_overlay/browser_reader.py:506`.
- Почему это проблема: любое изменение сайта может сломать лимиты, прогресс-бары или статус входа.
- Как исправить: хранить больше fixture-примеров страниц, добавить contract tests на новые версии страницы, разделить DOM-adapter и domain parser.
- Статус: частично закрыто тестами на текущий и старый формат; нужен расширенный набор fixtures при каждом изменении сайта.

### 9. UI-состояние и runtime diagnostics пока ограничены

- Серьёзность: Low/Medium.
- Где: `src/neurogate_usage_overlay/overlay.py`, `src/neurogate_usage_overlay/log_utils.py:10`.
- Почему это проблема: при жалобах “через час тормозит” сейчас сложно быстро увидеть число renders, длительность refresh, размер profile/cache, очередь worker и активные таймеры.
- Как исправить: добавить лёгкий diagnostic snapshot в bounded log: render count, refresh duration, worker queue size, browser profile/cache size.
- Статус: открыто как полезное улучшение.

### 10. Нет автоматического UI-smoke на реальном окне

- Серьёзность: Low/Medium.
- Где: `tests/test_overlay.py`, ручная проверка UI.
- Почему это проблема: unit tests хорошо ловят логику, но не подтверждают реальную плавность drag, overlay geometry, tooltip и menu после часа работы.
- Как исправить: добавить ручной/полуавтоматический long-run smoke: запустить overlay с fake reader на 60-90 минут, собрать CPU/memory/profile-size и проверить drag.
- Статус: открыто; нужен длительный локальный прогон на Windows.

## Быстрые исправления на 1-2 часа

- Закрепить в README/CHANGELOG новую проверку: `106 tests OK`.
- Добавить короткий раздел “Производительность и локальные файлы”: какие файлы растут, какие ограничены, что чистится.
- Сделать release checklist: ZIP asset + `.sha256` обязательны для публичного обновления.
- Добавить diagnostic log строки для refresh duration и worker queue size.
- Собрать `v1.7.2` ZIP и checksum после финального теста.

## Глубокие архитектурные улучшения

- Поддерживать update integrity policy в строгом режиме: публичный ZIP без checksum не устанавливать.
- Добавить long-run performance harness для fake overlay без реального NeuroGate.
- Разделить browser DOM adapter и parser fixtures, чтобы легче переживать изменения сайта.
- Добавить IPC/named pipe вместо любых fallback-поисков процессов.
- Ввести лёгкую telemetry-only-local diagnostics page/file без приватных данных.

## Что нельзя проверить без доступа

- Реальную консоль браузера и network waterfall страницы NeuroGate: нужен живой логин пользователя в ЛК.
- Реальные API-ответы NeuroGate: приложение читает UI, не имеет официального API token.
- Поведение на других тарифах и аккаунтах: нужны fixtures или тестовый аккаунт с другим тарифом.
- Долгий UX через 1-2 часа: нужен локальный long-run на Windows с открытым overlay.
- GitHub Releases end-to-end: нужен созданный release с ZIP asset и `.sha256`.

## GOAL

Цель: устранить найденные проблемы NeuroGate API Overlay так, чтобы:

- не было накопления UI callback-команд при повторном render;
- drag не блокировал UI и не писал state на каждом движении мыши;
- worker queue не могла бесконтрольно расти или ждать бесконечно;
- Chrome profile cache чистился безопасно без потери сессии;
- логи и daily usage оставались bounded;
- update flow требовал checksum для публичных ZIP-обновлений;
- штатная проверка `scripts/check.ps1` проходила без регрессий.

Критерий завершения текущего аудита: все критичные пункты 1-4 исправлены кодом и тестами, checksum policy усилена, отчёт обновлён, `scripts/check.ps1` проходит.

Критерий принятия перед релизом: владелец перезапускает оверлей и подтверждает live-проверку drag после длительной работы.

## План исправления

1. Закрыть UI callback leak и drag event storm.
2. Закрыть worker queue/timeout риск.
3. Ограничить рост Chrome cache без удаления сессии.
4. Усилить ZIP update checksum policy.
5. Обновить security/performance audit report.
6. Прогнать `scripts/check.ps1`.
7. После live-проверки владельцем обновить версию, README/CHANGELOG, собрать ZIP и сделать commit/push.

## Уже выполнено в текущем рабочем дереве

- Исправлен drag batching и сохранение позиции только после отпускания мыши.
- Убрано повторное создание tooltip/daily-limit canvas bindings в `_render()`.
- Добавлена безопасная очистка browser cache и Chrome cache size limits.
- Добавлены timeout и max queue size для `ThreadedUsageReader`.
- ZIP update без SHA256 теперь запрещён по умолчанию.
- Добавлены regression tests.
- Проверка: `106 tests OK`.

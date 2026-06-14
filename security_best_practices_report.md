# Комплексный аудит NeuroGate Overlay

Дата: 14-06-2026  
Объект: локальный Windows-оверлей `neurogate-overlay`  
Тип проверки: senior engineering + QA + security review, без атакующих действий

## Короткое резюме

Проект стал заметно крепче: быстрый старт вынесен из UI-потока, Playwright работает через отдельный worker, логи больше не пишут сырой текст ЛК, размер логов ограничен, single-instance lock усилен, запуск пишет `overlay.pid`, ZIP-релизы собираются с SHA256, update checker передаёт updater именно release ZIP asset и checksum, а ZIP updater применяет allowlist и временный rollback.

Главные оставшиеся улучшения уже не блокируют релиз, но полезны для следующего уровня качества: заменить fallback-завершение старых процессов по regex на полноценный IPC, вынести парсер сайта в DOM-адаптеры и добавить визуальные regression-тесты.

## 10 конкретных проблем и рисков

### 1. Медленный визуальный старт и поздний вызов окна входа

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/__main__.py:61`, `src/neurogate_usage_overlay/reader_worker.py:13`, `src/neurogate_usage_overlay/reader_worker.py:28`, `src/neurogate_usage_overlay/browser_reader.py:20`.
- Почему это проблема: пользователь видел оверлей раньше, чем реально начиналась загрузка страницы NeuroGate; при медленном сайте это выглядело как подвисание.
- Как исправлено: добавлен `ThreadedUsageReader`, первый `refresh` стартует сразу в worker thread, UI создаётся параллельно с загрузкой браузера, login prompt подтверждается за 3 попытки вместо долгого ожидания.

### 2. UI мог зависать во время чтения сайта

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/overlay.py:1338`, `src/neurogate_usage_overlay/reader_worker.py:13`.
- Почему это проблема: Tkinter нельзя блокировать сетевыми/браузерными операциями; иначе курсор над оверлеем превращается в ожидание, а пользователь ощущает “программа зависла”.
- Как исправлено: refresh выполняется асинхронно, результат возвращается в UI через `root.after(0, ...)`; добавлен тест `test_async_refresh_returns_before_slow_reader_finishes`.

### 3. Sync Playwright небезопасно использовать из разных потоков

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/reader_worker.py:13`.
- Почему это проблема: sync Playwright thread-bound; обращения из разных потоков могут давать greenlet/thread ошибки и нестабильное чтение ЛК.
- Как исправлено: все операции Playwright сериализованы через один dedicated worker thread и queue.

### 4. Debug logs могли хранить приватный текст страницы

- Серьёзность: High.
- Где: `src/neurogate_usage_overlay/browser_reader.py:578`, `src/neurogate_usage_overlay/browser_reader.py:593`, `src/neurogate_usage_overlay/log_utils.py:10`.
- Почему это проблема: локальный debug log мог случайно сохранить почту, тариф, текст ЛК или другие приватные данные.
- Как исправлено: сырой текст страницы не пишется; сохраняется только `text_len`, технические поля и компактная информация по окнам лимитов. Добавлен тест `test_debug_log_does_not_store_raw_portal_text`.

### 5. Логи могли расти бесконечно

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/log_utils.py:10`, `src/neurogate_usage_overlay/overlay.py:1289`, `src/neurogate_usage_overlay/browser_reader.py:593`.
- Почему это проблема: при длительной работе файлы могли разрастаться, занимать диск и увеличивать локальную приватную поверхность.
- Как исправлено: добавлен bounded log writer, который оставляет свежий хвост файла; добавлен тест `test_append_bounded_log_trims_old_content`.

### 6. Single-instance lock был слабым в крайних Windows-сценариях

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/single_instance.py:42`, `tests/test_single_instance.py:23`.
- Почему это проблема: при непустом lock-файле блокировка без явного `seek(0)` могла вести себя неочевидно, что повышало риск двойного запуска и борьбы за один Chrome profile.
- Как исправлено: перед lock/unlock добавлен `seek(0)`, добавлен тест на непустой lock-файл.

### 7. Скрипт запуска раньше завершал процессы только по regex

- Серьёзность: Medium.
- Где: `scripts/run-overlay.ps1`, `src/neurogate_usage_overlay/__main__.py`.
- Почему это проблема: это помогает гасить старые экземпляры, но regex по процессам остаётся менее безопасным, чем управляемая команда остановки.
- Как исправлено: приложение пишет `overlay.pid`, скрипт запуска сначала останавливает конкретный PID и очищает PID-файл. Regex fallback оставлен только для старых сборок без PID-файла.
- Как улучшить глубже: заменить fallback на local IPC/named pipe, чтобы новый запуск отправлял старому процессу команду `stop`.

### 8. ZIP updater раньше не был связан с release asset и checksum end-to-end

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/update_checker.py:58`, `src/neurogate_usage_overlay/update_checker.py:109`, `src/neurogate_usage_overlay/overlay.py:778`, `scripts/update-and-restart.ps1:65`, `scripts/update-and-restart.ps1:147`.
- Почему это проблема: упаковщик уже мог создавать `.sha256`, но updater по умолчанию мог брать GitHub source archive, рядом с которым checksum не публикуется. В таком виде integrity-проверка могла не сработать для обычного пользователя.
- Как исправлено: update checker теперь читает GitHub Release assets, предпочитает `neurogate-overlay-*.zip`, забирает SHA256 из asset digest при наличии и передаёт `-ReleaseZipUrl` / `-ReleaseSha256` в updater. Добавлены тесты на release asset и checksum.

### 9. ZIP update раньше широко заменял дерево проекта

- Серьёзность: Medium.
- Где: `scripts/update-and-restart.ps1`.
- Почему это проблема: широкое копирование дерева может перезаписать нестандартные локальные файлы пользователя внутри папки установки.
- Как исправлено: ZIP updater обновляет только allowlist известных файлов проекта, делает временный бэкап затронутых файлов и откатывает их при ошибке копирования.

### 10. Прогресс-бары зависят от DOM/CSS сайта

- Серьёзность: Medium.
- Где: `src/neurogate_usage_overlay/browser_reader.py:473`.
- Почему это проблема: если NeuroGate поменяет DOM, CSS-классы или цвет полосок, процент может читаться неверно.
- Как исправить: оформить парсер как набор DOM-адаптеров, приоритетно читать `aria-valuenow`/семантические значения, хранить HTML fixtures разных версий страницы и тестировать fallback.

## Быстрые исправления на 1-2 часа

- Добавить короткий startup health log без приватных данных: `startup_ms`, `first_snapshot_ms`, `login_prompt_ms`.
- Добавить тест, что обновление запускается только по явному клику пользователя.
- Добавить отдельный smoke-тест ZIP updater в временной установочной папке без реального перезапуска оверлея.

## Глубокие архитектурные улучшения

- Заменить fallback process-kill regex на полноценный local IPC lifecycle.
- Усилить updater цифровой подписью release manifest.
- Вынести парсер портала в адаптеры версий DOM и покрыть HTML fixtures.
- Добавить визуальные regression-тесты для compact/x2/menu/daily-limit states.
- Расширить sleep/resume проверку на реальные Windows-сборки и разные длительности сна.

## Что нельзя проверить без доступа

- Ошибки в консоли браузера и сетевых запросах реального портала NeuroGate без разрешения открыть живую авторизованную сессию и смотреть DevTools/Playwright network events.
- Все варианты тарифов других пользователей: нужны реальные примеры DOM/текста страницы для разных тарифов.
- Поведение под настоящим sleep/resume на разных Windows-сборках: нужен длительный ручной прогон на машинах пользователей.
- Реальный update flow “v1.6 -> v1.7” через GitHub Releases: нужен опубликованный тестовый release asset ZIP + `.sha256`.

## Измеримый GOAL

Цель: устранить найденные проблемы так, чтобы:

- пункты 1-9 были исправлены кодом и покрыты тестами или smoke-проверками;
- пункт 10 был частично закрыт устойчивыми fallback-тестами, а полноценные DOM fixtures вынесены в следующий архитектурный этап;
- `scripts/check.ps1` проходил полностью;
- `scripts/package-release.ps1` собирал ZIP и `.sha256`;
- живой запуск не блокировал UI и не писал raw portal text в debug log;
- коммит и пуш выполнялись только после отдельного согласования.

## План исправления

1. Закрыть быстрый старт и UI freeze: worker thread + async refresh.
2. Закрыть приватность логов: убрать raw text + ограничить размер логов.
3. Закрыть single-instance edge case.
4. Закрыть ZIP integrity end-to-end: package `.sha256`, release asset URL, checksum в updater.
5. Закрыть ZIP updater allowlist/rollback.
6. Добавить watchdog после sleep/resume.
7. Прогнать `scripts/check.ps1`.
8. Проверить packaging smoke.
9. Подготовить README/CHANGELOG под `1.7.0`.

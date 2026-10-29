Разработка и воспроизведение проверок
===================================

0.3.1 — исправления и подготовка публичной поставки
------------------------------------------------

29 октября 2026 года. Версия обеих частей — 0.3.1, протокол 2.0.
Полная Java-проверка: 785 без ошибок/пропусков; установленные Python 3.11.17
и 3.14.7: по 242 без пропусков. Архивы/MIT/PEP 639/RECORD проверены строгим
Twine и `tools/check_release.py`. VS Code/Pylance проверяет новые helper и ошибку.
Нативная приёмка завершена: 10 групп новой пары и 3 группы настоящей старой
пары 0.3.0, allPassed=true. [Отчёт и измерения](reports/V0_3_1.ru.md).
Исторические прогоны ниже сохраняются отдельно.

Переносимые команды: [CONTRIBUTING](../CONTRIBUTING.md),
[сборка и публикация](PUBLISHING.ru.md). Локальное повторение на закреплённой среде:

```powershell
.\.venv-tools\Scripts\python.exe tools/build_release.py --source-date-epoch 1793232000 --offline
.\.venv-tools\Scripts\python.exe tools/check_release.py --wheel dist/v0.3.1/minebridge-0.3.1-py3-none-any.whl --sdist dist/v0.3.1/minebridge-0.3.1.tar.gz --jar dist/v0.3.1/minebridge-paper-0.3.1.jar --python .venv-v031-311/Scripts/python.exe --python .venv-v031-314/Scripts/python.exe --output .work/v031-package-results.json
powershell -NoProfile -ExecutionPolicy Bypass -File python/tests/ide-v031/launch.ps1
.\.venv-v031-314\Scripts\python.exe -I tools/smoke_v031.py
```

Сборка требует пустого каталога текущей поставки; `--replace` применяется
только при намеренной пересборке кандидата до публикации, с повторной приёмкой.
Для установки и полного набора Python-тестов используйте команды CONTRIBUTING
на двух интерпретаторах; старые venv с 0.3.0 не перезаписывайте, они нужны baseline.
BUILD.json подтверждает только сборку. Итоговый RELEASE.json фиксируется после
проверок установленного пакета, Paper и IDE.

```powershell
.\.venv-tools\Scripts\python.exe tools/finalize_release.py --build dist/v0.3.1/BUILD.json --package .work/v031-package-results.json --python-tests .work/v031-python-results.json --paper .work/v031-paper-results.json --ide .work/ide-v031-results.json
```

Финализатор проверяет SHA всех входов, текущих артефактов, старых поставок,
манифестов и установленного wheel. Он ничего не собирает и не публикует.

История 0.3.0 и более ранних версий сохраняется ниже.

0.3 / I05 — сборка и проверка установленной поставки
--------------------------------------------------

29 октября 2026 года. Версия Python/плагина — `0.3.0`, протокол 2.0.
Итоговые JAR/wheel/sdist собраны в `dist/v0.3`. Пройдены полные Java-тесты,
проверки установленного wheel, упаковки и настоящего VS Code/Pylance.
**Общая Paper-приёмка I05 завершена: `allPassed=true`.**
[Отчёт I05](reports/V0_3_I05.ru.md) содержит результаты и границы локальной проверки.

Текущие подтверждённые результаты:

- Java: 777 тестов, без ошибок и пропусков.
- Python 3.11.17/3.14.7: по 238 тестов **из установленного wheel**, без пропусков.
- Wheel: 50 записей, 46 файлов пакета; RECORD, байты, sdist и исходники сверены,
  зависимостей времени выполнения нет. Проверены генераторы каталогов и изолированные импорты.
- VS Code 1.142.0, Python extension 2026.10.0, Pylance 2026.4.1: 11 каталогов,
  30 сигнатур, 11 выведенных типов, 7 ожидаемых ошибок неверных типов;
  корректный пример без диагностик. Определения из site-packages,
  включая выведенные ChatEvent/BlockBreakEvent/ProjectileHitEvent в lambda.
- Paper: 19 проверок основного сценария, отдельные успешные запуски свежего мира
  с прежним config и baseline со старым плагином и SDK 0.2.1.

Все команды ниже выполняются из корня проекта в PowerShell. Нужны закреплённые
`.tools`, `.venv-tools`, прежний bootstrap cache и принятое EULA стенда. Сборку запускают
**до** приёмки, после фиксации производственных исходников. Не меняйте Python
README/pyproject/src и Java production inputs или файлы кандидата во время
дальнейших проверок: их SHA фиксируются и проверяются повторно.

```powershell
.\.venv-tools\Scripts\python.exe tools/build_v03_release.py
if ($LASTEXITCODE -ne 0) { throw '0.3 candidate build or installed tests failed' }

.\.venv-tools\Scripts\python.exe tools/check_v03_package.py `
    --wheel dist/v0.3/minebridge-0.3.0-py3-none-any.whl `
    --sdist dist/v0.3/minebridge-0.3.0.tar.gz `
    --jar dist/v0.3/minebridge-paper-0.3.0.jar `
    --python .venv-v03-311/Scripts/python.exe `
    --python .venv-v03-314/Scripts/python.exe
if ($LASTEXITCODE -ne 0) { throw 'Final archive audit failed' }

powershell.exe -NoProfile -ExecutionPolicy Bypass -File python/tests/ide-v03/launch.ps1
if ($LASTEXITCODE -ne 0) { throw 'Actual VS Code/Pylance verification failed' }

.\.venv-v03-314\Scripts\python.exe -I tools/smoke_v03_i05.py
if ($LASTEXITCODE -ne 0) { throw 'Installed-release Paper acceptance failed' }
```

`build_v03_release.py` запускает Gradle test/shadowJar/:observer:jar, строит sdist,
затем wheel **из sdist**, устанавливает его без зависимостей в отдельные
`.venv-v03-311`/`.venv-v03-314` и выполняет оба полных набора тестов с `-I` вне исходников.
Импорт должен указывать в соответствующий `Lib/site-packages/minebridge`.
PYTHONPATH и переменная окружения токена не используются. Старые `dist/v0.2` и `dist/v0.2.1`
проверяются по SHA и не заменяются.

SOURCE_DATE_EPOCH закреплён: 1793145600 (28 октября 2026 года; дата сборки сохранена).
Приёмка завершена 29 октября. setuptools 84.2.0, Gradle 9.1.0,
Paper 26.2 build 133/JDK 25.0.4.1+1 — прежняя закреплённая среда. Содержимое sdist
сохраняется, метаданные gzip/tar нормализуются для воспроизводимости.
`check_v03_package.py` только читает/проверяет архивы и установленный пакет,
не строит и не подключается к серверу.

IDE helper использует отдельные `.work/ide-v03-workspace` и `.work/ide-v03-user-data`,
установленные расширения Python/Pylance и выбранный `.venv-v03-314`.
Пользовательские workspace/settings не изменяются. Пакет импортируется с `-I`
без сетевых вызовов, определения должны вести в установленный wheel.
`verify_artifact.py` после IDE сверяет все 46 файлов пакета с точными байтами wheel;
SHA wheel/файлов/helper записываются в `.work/ide-v03-results.json`.
Проверка выполняется в настоящем extension host VS Code.

Отдельный узкий Pylance-прогон также проверил точную копию `examples/v03_lesson.py`
и восемь Python-фрагментов README/QuickStart: ноль диагностик против установленного
wheel. Только фрагментам без импорта добавлен `from minebridge import Minecraft`.
SHA исходных документов и wheel сохранены в `.work/ide-v03-docs-results.json`.
Это статическая проверка примеров; сам пример занятия на сервере этим прогоном не запускался.

`smoke_v03_i05.py` использует итоговые dist JAR/wheel, два игровых TCP-клиента
и два отдельных Python OS-процесса. Проверяет совместный сценарий событий и
инвентарей, независимость обработчиков/курсоров, видимые потери live/history,
обычные RPC, logging, старый клиент и короткий скрипт без close. Отдельные
запуски проверяют новый мир с прежним config и настоящую baseline 0.2.1
(старые SDK **и** plugin). Время 100/1000 отдельных buffered setBlock **включает
подтверждённый flush**; logging выключен, event flood во время замера отсутствует.
Четыре чанка benchmark заранее загружены и удерживаются observer. Каждый свежий
SDK-процесс перед замерами выполняет 1000 нетаймируемых setBlock и flush.
На итоговом плагине свежие процессы идут в порядке SDK 0.3.0 / 0.2.1 / 0.2.1 / 0.3.0;
для каждого SDK получено по шесть замеров на 100 и 1000 блоков. Настоящая baseline
со старым плагином и SDK выполняется отдельно, по три замера на размер.
Три замера на размер в постоянной итоговой сессии после событийного сценария
сохраняются как отдельная нагрузка. Локальная проверка с двумя игровыми клиентами
не подтверждает производительность полного класса, LAN или пользовательского Paper 99.
Пользовательский сервер не используется. Все серверы создаются в `.work`,
после остановки проверяются процессы/потоки/порты и исходные SHA.

Финализация метаданных — **отдельный последний шаг**, без повторной сборки:

```powershell
.\.venv-tools\Scripts\python.exe tools/build_v03_release.py --finalize
if ($LASTEXITCODE -ne 0) { throw 'Release evidence gate failed' }
```

Финализатор требует успешные build/package/IDE/Paper результаты, совпадение входных
хешей и точных проверенных артефактов. Только затем пишется `RELEASE.json`;
одной сборки кандидата для объявления готовой поставки недостаточно.
Никакая команда не публикует пакет в PyPI или другом внешнем сервисе.

Сводки: `.work/v03-i05-build-results.json`, `.work/v03-i05-package-results.json`,
`.work/ide-v03-results.json`, `.work/v03-i05-paper-results.json`. Paper manifests/логи —
`integration/artifacts/v03-i05-<runId>`. Принятые manifests (`allPassed=true`):

- основной сценарий — `bde72a669dff4a90ab089f7240136b64`;
- свежий мир с прежним config — `ffac0ba6f7084e87afae14e39e0d99da`;
- старые плагин и SDK 0.2.1 — `451fc637425c4ea2923563d5b5044156`.

Неуспешные предварительные прогоны сохраняют false. Окончательный результат и
измерения описаны в [отчёте I05](reports/V0_3_I05.ru.md).

Ниже сохранены исторические source-workflows I01–I04; актуальный release-workflow
I05 описан выше. Эти старые source-проверки не заменяют installed-wheel приёмку.

0.3 / I04 — текущие исходники точных слотов
-----------------------------------------

28 октября2026 года: исходники0.3.0.dev4, I01–I04 завершены.
[API](API_V0_3.ru.md), [контракт](contracts/V0_3_I04_CONTRACT.ru.md),
[пример](../examples/v03_inventory_slots.py), [отчёт](reports/V0_3_I04.ru.md).
Установочная поставка остаётся0.2.1; финальные JAR/wheel0.3 и VS Code — I05.

Из корня проекта в PowerShell:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'python/src'
.\.venv-v021-314\Scripts\python.exe -c "import minebridge; print(minebridge.__version__); print(minebridge.__file__)"
.\.venv-v021-311\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 source tests failed' }
.\.venv-v021-314\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.14 source tests failed' }

$v03I04Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $v03I04Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
.\plugin\gradlew.bat -p plugin test shadowJar :observer:jar --offline --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Java tests or temporary JAR build failed' }
.\.venv-v021-314\Scripts\python.exe tools/smoke_v03_i04.py
if ($LASTEXITCODE -ne 0) { throw 'Paper I04 acceptance failed' }
```

Импорт должен показывать dev4 и python/src/minebridge. Принятый результат:
777 Java tests; по238 Python tests с двумя ожидаемыми packaging skips;
shared corpus509 и13 Paper-групп, allPassed=true. Это проверка исходников,
а не установленного wheel0.3. Старые имена venv не меняют источник импорта.

Runner создаёт новый offline Paper133 на свободных localhost-портах с прежним
принятым EULA и кэшем. Он использует dev4 JAR из build/, test-only observer,
два реальных игровых TCP-клиента и два source-Python OS-процесса.
Проверяются exact slots, public/hidden equipment, physical/double/trapped
chests, layout races между страницами, сложные ItemView, unloaded chunk reload
и bulk/offline prevalidation. Test-only page hook меняет layout после получения
первой настоящей страницы; production API не подменяется.
Cold-start readiness deadline300s, отдельный marker не нужен.

Финальный run `47ff3e20c503449d9f69111fdbf6ac73` фиксирует46 Python source-файлов,
скрипты/контракт и входные JAR по SHA; во время run менять их нельзя.
Manifest/серверный лог — integration/artifacts/v03-i04-<runId>, summary —
.work/v03-i04-paper-results.json. Штатная остановка, свободные порты и отсутствие
SDK-потоков проверяются runner. Предыдущие false-прогоны не заменяются успехом.
Пользовательский сервер и dist/v0.2.1 runner не использует.

Ниже сохранены исторические workflows I01–I03. Актуальный runner — I04 выше.

0.3 / I03 — текущие исходники игровых событий
-------------------------------------------

Исходники имеют версию `0.3.0.dev3`. I03 добавляет каталог из 14 типов,
серверные фильтры Region/blocks, typed damage-проекцию и монитор контактов с лавой.
[API](API_V0_3.ru.md), [контракт](contracts/V0_3_I03_CONTRACT.ru.md),
[пример](../examples/v03_game_events.py). Установочная поставка остаётся 0.2.1;
wheel и установочный JAR 0.3 выпускаются в I05.

Команды PowerShell из корня проекта:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'python/src'
.\.venv-v021-314\Scripts\python.exe -c "import minebridge; print(minebridge.__version__); print(minebridge.__file__)"
.\.venv-v021-311\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 source tests failed' }
.\.venv-v021-314\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.14 source tests failed' }
.\.venv-v021-311\Scripts\python.exe tools/export_damage_cause_catalog.py --check
if ($LASTEXITCODE -ne 0) { throw 'Pinned native DamageCause export differs' }
.\.venv-v021-311\Scripts\python.exe tools/generate_damage_cause_catalog.py --check
if ($LASTEXITCODE -ne 0) { throw 'Generated DamageCause catalog differs' }

$v03I03Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $v03I03Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
.\plugin\gradlew.bat -p plugin test shadowJar :observer:jar --offline --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Java tests or temporary JAR build failed' }
.\.venv-v021-314\Scripts\python.exe tools/smoke_v03_i03.py
if ($LASTEXITCODE -ne 0) { throw 'Paper I03 acceptance failed' }
```

Импорт должен показывать dev3 и python/src/minebridge. Это source-тестирование:
старые имена venv не означают, что в них установлен wheel 0.3. Принятые unit
результаты: 693 Java tests и по 223 Python tests (по два ожидаемых пропуска
installed-package проверок). Shared corpus содержит 439 случаев; последние
три проверки грамматики native имён дополнительно прогнаны на обоих Python.
Paper: 13/13 групп, allPassed=true;
[отчёт I03](reports/V0_3_I03.ru.md). Финальный run
`d3444adeb47e40de9bcb93927be07524` проверяет 43 source-файла/скрипты/JAR по SHA.

Runner запускает новый изолированный offline Paper build133 на свободных
localhost-портах с ранее принятым EULA и временным dev3 JAR. Native actions
передают настоящие игровые TCP-клиенты; два отдельных Python OS-процесса
работают с python/src. Test-only observer читает события и состояние Paper
независимо от production capture API. Bootstrap cache/toolchain должны уже
существовать. Для холодного старта readiness deadline300s.
Логи/manifest находятся в integration/artifacts/v03-i03-<runId>, summary —
.work/v03-i03-paper-results.json. Источники и скрипты нельзя менять во время
прогона: manifest проверяет их SHA в конце. Неуспешные прогоны сохраняют false.
Пользовательский сервер и готовая поставка 0.2.1 не используются и не заменяются.

Исторические инструкции I01–I02 ниже описывают соответствующие версии
исходников/артефактов; актуальный runner — I03 выше.

0.3 / I02 — текущие исходники событий чата
----------------------------------------

27 октября 2026 года: исходники `0.3.0.dev2`. Завершены I01 и I02;
[отчёт I02](reports/V0_3_I02.ru.md), [API](API_V0_3.ru.md),
[пример](../examples/v03_chat_events.py). Готовая поставка остаётся 0.2.1.
Wheel и установочный JAR 0.3 выпускаются в I05; тестовый JAR допустим в build/.
Ниже этого раздела сохранён исторический workflow I01, включая разовый экспорт
gamerules. Для I02 не нужен marker/второй терминал или новый экспорт каталога.

Команды выполняются в PowerShell из корня проекта. Python берётся из прежних
venv, но импортируется **из python/src**, а не из установленного wheel:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'python/src'
.\.venv-v021-314\Scripts\python.exe -c "import minebridge; print(minebridge.__version__); print(minebridge.__file__)"
.\.venv-v021-311\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 source tests failed' }
.\.venv-v021-314\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.14 source tests failed' }

$v03I02Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $v03I02Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
.\plugin\gradlew.bat -p plugin test shadowJar :observer:jar --offline --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Java tests or temporary JAR build failed' }

.\.venv-v021-314\Scripts\python.exe tools/smoke_v03_i02.py
if ($LASTEXITCODE -ne 0) { throw 'Paper I02 acceptance failed' }
```

Импорт показывает `0.3.0.dev2` и путь python/src/minebridge. Принятый результат:
618 Java tests; по 209 Python tests (два ожидаемых source-only packaging skips);
9 Paper-сценариев, allPassed=true в `.work/v03-i02-paper-results.json`.
Успех касается исходного SDK, а не установленных wheel 0.3.

Runner сам выбирает свободные localhost-порты, создаёт новый изолированный offline
Paper build133, копирует ранее принятое EULA и временные JAR, запускает двух
настоящих игровых клиентов и два отдельных Python-процесса. Test-only observer
наблюдает реальный AsyncChatEvent и фактический инвентарь. EULA/закреплённые
toolchain/bootstrap cache должны уже существовать; первое скачивание/настройка
среды — прежний T02 workflow. Пользовательский сервер runner не использует.
На холодном запуске Paper readiness может занять несколько минут (deadline300s).

Manifest сохраняет SHA входов/41 source-файла/скриптов; менять их во время прогона
нельзя. После успешного run проверяются чистая остановка сервера, освобождение
портов, отсутствие оставшихся SDK consumer/receiver threads и неизменность хешей.
При ошибке собственный fixture останавливается, allPassed остаётся false.
Переполнения/потери/частичные TCP-кадры покрыты unit/TCP suite; этот Paper-run
не создаёт массовый flood. LAN и пользовательские сборки отдельно не проверяются.

Исторический I01
----------------

0.3 / I01 — исходники управления игрой
------------------------------------

Обновлено 27 октября 2026 года. Исходники имеют версию `0.3.0.dev1`;
готовая установочная поставка по-прежнему 0.2.1. В I01 wheel не собирается,
временный JAR находится только в `plugin/build/libs`. Новые методы:
[API I01](API_V0_3.ru.md), [пример](../examples/v03_controls.py),
[отчёт проверки](reports/V0_3_I01.ru.md).
Ниже сохранены также прежние проверки 0.2.1/0.2.0.

Все команды этого раздела выполняются из корня проекта в PowerShell.
Для Python используется **исходный пакет через PYTHONPATH**, а не установленный
wheel в окружениях с прежними именами `.venv-v021-311/314`. Флаг `-I` для этих
source-прогонов не подходит: он игнорирует PYTHONPATH и может импортировать
старую установленную 0.2.1. Сам Python нужной версии остаётся из указанных venv.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'python/src'
.\.venv-v021-314\Scripts\python.exe -c "import minebridge; print(minebridge.__version__); print(minebridge.__file__)"
.\.venv-v021-311\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 source tests failed' }
.\.venv-v021-314\Scripts\python.exe -m unittest discover -s python/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Python 3.14 source tests failed' }
```

Проверка импорта должна показать `0.3.0.dev1` и путь `python/src/minebridge`.
В принятом I01 — по 181 тесту на каждом Python, два пропуска относятся только
к installed-wheel metadata; проверки упаковки перенесены на итоговую поставку.
Это не проверка установленных пакетов или wheel 0.3.

Для подготовки временного JAR и fixture экспорта gamerules:

```powershell
$v03Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $v03Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
.\plugin\gradlew.bat -p plugin test shadowJar :observer:jar --offline --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Java tests or temporary JAR build failed' }
.\.venv-tools\Scripts\python.exe tools/prepare_gamerule_export.py
if ($LASTEXITCODE -ne 0) { throw 'Game-rule exporter preparation failed' }
```

В принятом I01 Java suite содержит 546 cases без ошибок. Сборки/фикстуры
используют закреплённые Paper133, API/JDK и существующий bootstrap-кэш.
Продуктовый `dist` этими командами не обновляется.

Paper runner требует **двух терминалов и явной передачи готовности каталога**;
один его запуск намеренно остановится в ожидании marker. CLI-параметров/
отдельного `--help` у этого runner нет.

В терминале A запустите:

```powershell
.\.venv-v021-314\Scripts\python.exe tools/smoke_v03_i01.py
```

Дождитесь JSON-фазы `catalog-export-ready`. Runner уже держит отдельный Paper
и записывает путь экспортированного JSON в `.work/v03-i01-catalog-export-path.json`.
Открытые пользовательские серверы/миры не используются. Ранее принятый EULA
копируется из `.work/t02-server/eula.txt`, новое согласие не создаётся.

В терминале B после этой фазы выполните:

```powershell
$v03Export = Get-Content .work/v03-i01-catalog-export-path.json -Raw -Encoding UTF8 | ConvertFrom-Json
Copy-Item -LiteralPath $v03Export.export -Destination catalogs/paper-26.2-build133-gamerules.json
.\.venv-tools\Scripts\python.exe tools/generate_gamerule_catalog.py
if ($LASTEXITCODE -ne 0) { throw 'Game-rule generation failed' }
.\.venv-tools\Scripts\python.exe tools/generate_gamerule_catalog.py --check
if ($LASTEXITCODE -ne 0) { throw 'Generated game-rule catalog differs' }
```

Убедитесь, что runId соответствует текущему терминалу A. Повторите source unit-
команды выше для сгенерированного каталога; подготовьте все изменения Python
и `integration/tests/v03_i01_acceptance.py` **до** передачи готовности.
Только после успешных проверок опубликуйте marker в терминале B:

```powershell
$v03Ready = @{
    runId = $v03Export.runId
    sourceVersion = '0.3.0.dev1'
    sourceReady = $true
    snapshotSha256 = (Get-FileHash -LiteralPath catalogs/paper-26.2-build133-gamerules.json -Algorithm SHA256).Hash.ToLowerInvariant()
}
$v03Ready | ConvertTo-Json | Set-Content -LiteralPath .work/v03-i01-catalog-ready.json -Encoding UTF8
```

Marker должен быть новее текущего export. Runner выводит `source-frozen`,
фиксирует хеши Python/JAR/observer/скриптов и выполняет приёмку.
После marker не меняйте исходники, каталоги, JAR или acceptance-скрипты:
несовпадение хешей завершит прогон ошибкой. В принятом запуске marker дополнительно
сохраняет source hashes и результаты unit-прогонов.

Итог — `.work/v03-i01-paper-results.json` с `allPassed=true`, путь к manifest
находится внутри. В принятом запуске прошли 11 сценариев, два игровых клиента
и два отдельных Python-процесса из исходников. Сервер штатно останавливается,
артефакты остаются в `.work/v03-i01-<runId>` и `integration/artifacts/v03-i01-<runId>`.
Loopback/Paper133 не объявляется проверкой LAN, полного класса или новой версии Paper.

Для запуска примера с временным I01-плагином используйте тот же PYTHONPATH:

```powershell
.\.venv-v021-314\Scripts\python.exe examples/v03_controls.py CurrentNick --host 192.168.0.200 --port 4712
```

По умолчанию пример работает с SELF; общие настройки мира включаются явным
`--configure-world`. Обычная установка 0.2.1 новых I01-методов не содержит.

Исправление 0.2.1 — 26 октября
-----------------------------

Текущая поставка: `dist/v0.2.1/`. Изменены нормальный выход Python и
необязательный журнал действий сессии. Для точечной приёмки используются
чистые `.venv-v021-311`/`.venv-v021-314` с wheel 0.2.1 и прежнее окружение
`.venv-v02-314` с 0.2.0 для воспроизведения дефекта. Старые артефакты не заменяются.

```powershell
.\.venv-v021-311\Scripts\python.exe -I -m unittest discover -s python/tests -q
.\.venv-v021-314\Scripts\python.exe -I -m unittest discover -s python/tests -q
.\.venv-tools\Scripts\python.exe tools/check_v02_package.py --version 0.2.1 --wheel dist/v0.2.1/minebridge-0.2.1-py3-none-any.whl --sdist dist/v0.2.1/minebridge-0.2.1.tar.gz --jar dist/v0.2.1/minebridge-paper-0.2.1.jar --python .venv-v021-311/Scripts/python.exe --python .venv-v021-314/Scripts/python.exe --output .work/v021-package-results.json
.\.venv-v021-314\Scripts\python.exe tools/smoke_v021.py
```

Последняя команда поднимает отдельный локальный Paper из уже подготовленного
стенда, использует существующее согласие EULA и останавливает собственный
сервер. Нужен test-only observer JAR из I05. Итог: `.work/v021-paper-results.json`;
[отчёт исправления](reports/V0_2_1.ru.md). Ниже сохранены команды I05/0.2.0.

I05 — финальная поставка 0.2.0
-----------------------------

Все команды выполняются из корня репозитория в PowerShell. Для воспроизведения
приёмки используются финальные `dist/v0.2/minebridge-paper-0.2.0.jar`,
`dist/v0.2/minebridge-0.2.0-py3-none-any.whl` и `dist/v0.2/minebridge-0.2.0.tar.gz`.
Не пересобирайте и не подменяйте эти файлы во время прогона: стенд сохраняет
их SHA-256. Пользовательский запуск — [QUICKSTART.ru.md](QUICKSTART.ru.md),
фактические результаты и границы приёмки — [отчёт I05](reports/I05.ru.md).

Окружения приёмки — `.venv-v02-311` (Python 3.11.17) и `.venv-v02-314`
(Python 3.14.7). Для первого создания на этом стенде:

```powershell
& .\.tools\python\cpython-3.11.17-windows-x86_64-none\python.exe -m venv .venv-v02-311
py -3.14 -m venv .venv-v02-314
```

Если окружения уже существуют, используйте их без повторного создания.
Установите один и тот же финальный wheel в оба:

```powershell
.\.venv-v02-311\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/v0.2/minebridge-0.2.0-py3-none-any.whl
.\.venv-v02-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/v0.2/minebridge-0.2.0-py3-none-any.whl
.\.venv-v02-311\Scripts\python.exe -I -m unittest discover -s python/tests -q
.\.venv-v02-314\Scripts\python.exe -I -m unittest discover -s python/tests -q
```

`-I` исключает `PYTHONPATH` и пользовательские пути. Эти команды проверяют
установленный пакет из `site-packages`, а не исходники `python/src`.
Утилита ниже дополнительно проверяет wheel/RECORD, наличие `py.typed` и
каталогов, совпадение sdist с wheel, версии Python/JAR, генераторы и офлайн-импорт
из временной папки вне репозитория в обоих интерпретаторах:

```powershell
.\.venv-v02-314\Scripts\python.exe tools/check_v02_package.py `
    --wheel dist/v0.2/minebridge-0.2.0-py3-none-any.whl `
    --sdist dist/v0.2/minebridge-0.2.0.tar.gz `
    --jar dist/v0.2/minebridge-paper-0.2.0.jar `
    --python .venv-v02-311/Scripts/python.exe `
    --python .venv-v02-314/Scripts/python.exe
```

Ожидается код 0 и `passed=true` в `.work/v02-package-results.json`.
Повторяемый `--python` проверяет несколько интерпретаторов, `--output`
позволяет выбрать другой JSON-файл. Утилита ничего не собирает и не устанавливает.
При проверке импорта соединения запрещены; ожидается `networkAttempts=0`.

Общая интеграционная приёмка на Paper использует финальный JAR и установленный
wheel. Нужны `.tools/t02-toolchain.json`, закреплённый Paper, bootstrap-кэши
стенда, ранее принятый EULA и свежий test-only observer. Observer можно собрать
отдельно, не меняя финальный JAR:

```powershell
$v02Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $v02Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
.\plugin\gradlew.bat -p plugin :observer:build --offline --no-daemon
.\.venv-v02-314\Scripts\python.exe tools/smoke_i05.py `
    --plugin dist/v0.2/minebridge-paper-0.2.0.jar `
    --wheel dist/v0.2/minebridge-0.2.0-py3-none-any.whl `
    --python .venv-v02-314/Scripts/python.exe
```

Все три пути совпадают с текущими значениями по умолчанию, поэтому для этого
стенда достаточно `python tools/smoke_i05.py` из выбранного окружения.
Runner ничего не собирает, не устанавливает, не скачивает и не удаляет.
Он поднимает отдельный локальный сервер с двумя игровыми TCP-клиентами и двумя
независимыми Python-процессами, затем новый мир с тем же конфигом и выключенным
test-control. Итог — `.work/i05-paper-results.json` (`allPassed=true`),
подробности — `integration/artifacts/i05-<runId>/manifest.json`.
Процедура и ограничения описаны в [integration/README.md](../integration/README.md).

VS Code/Pylance для установленного wheel
--------------------------------------

Helper `python/tests/ide-v02` использует `.venv-v02-314` с установленным 0.2.0.
Он не добавляет `python/src` в пути Python или Pylance: `extraPaths=[]`,
автопоиск дополнительных путей отключён. Проверяются константы пяти каталогов,
определения в `site-packages`, сигнатуры всех публичных методов, отсутствие
ошибок корректного примера и диагностики трёх подменённых типов ключей.
Paper и игровые клиенты для этой проверки не запускаются.

Используется отдельный portable VS Code из `.tools/vscode-t10/app/Code.exe`
с уже установленными расширениями Python/Pylance. Происхождение и проверка
архива Microsoft сохранены в историческом разделе T10 ниже. Подготовка:

```powershell
$ideV02Repo = (Get-Location).Path
$ideV02Code = Join-Path $ideV02Repo '.tools/vscode-t10/app/Code.exe'
$ideV02Helper = Join-Path $ideV02Repo 'python/tests/ide-v02/run.js'
$ideV02Python = Join-Path $ideV02Repo '.venv-v02-314/Scripts/python.exe'
$env:ELECTRON_RUN_AS_NODE = '1'
$ideV02PrepareArguments = @(
    '"' + $ideV02Helper + '"'
    '--prepare'
    '"' + $ideV02Python + '"'
)
$ideV02Prepare = Start-Process -FilePath $ideV02Code -ArgumentList $ideV02PrepareArguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput .work/ide-v02-prepare-stdout.log -RedirectStandardError .work/ide-v02-prepare-stderr.log
if ($ideV02Prepare.ExitCode -ne 0) { throw 'IDE preparation failed' }
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Remove-Item Env:VSCODE_IPC_HOOK_CLI -ErrorAction SilentlyContinue
$ideV02Arguments = @(
    '--extensionDevelopmentPath="' + (Join-Path $ideV02Repo 'python/tests/ide-v02') + '"'
    '--extensionTestsPath="' + $ideV02Helper + '"'
    '--user-data-dir="' + (Join-Path $ideV02Repo '.work/ide-v02-user-data') + '"'
    '--extensions-dir="' + (Join-Path $env:USERPROFILE '.vscode/extensions') + '"'
    '--disable-workspace-trust'
    '--skip-welcome'
    '--skip-release-notes'
    '--new-window'
    '"' + (Join-Path $ideV02Repo '.work/ide-v02-workspace') + '"'
)
$ideV02Process = Start-Process -FilePath $ideV02Code -ArgumentList $ideV02Arguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput .work/ide-v02-stdout.log -RedirectStandardError .work/ide-v02-stderr.log
if ($ideV02Process.ExitCode -ne 0) { throw 'IDE checks failed' }
$ideV02Result = Get-Content .work/ide-v02-results.json -Raw -Encoding UTF8 | ConvertFrom-Json
if ($ideV02Result.status -ne 'passed') { throw 'IDE checks did not pass' }
```

Профиль и workspace этой проверки отдельные. Сводка сохраняется в
`.work/ide-v02-results.json`; проверяемый пакет должен находиться в выбранном
`site-packages`, определения не должны указывать на исходники репозитория.

Исторические проверки I01–I04 и T01–T10
-------------------------------------

Ниже сохранены команды соответствующих этапов и их артефактов. Они не являются
способом повторить финальную приёмку 0.2.0 на текущих исходниках.

I04 — проверка исходников без промежуточной поставки
--------------------------------------------------

По уточнению пользователя JAR/wheel для установки собираются в конце v0.2,
на I05. В I02–I04 Python запускается напрямую из исходников; используется только
временный JAR из plugin/build для проверки на реальном Paper. dist/v0.2/i01
не обновляется. Примеры — [предметы/эффекты/сущности](../examples/rewards_effects_entities.py),
[игроки](../examples/players_and_chat.py),
[блоки](../examples/block_regions.py).

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'python/src')
.\.venv-i01-314\Scripts\python.exe -m unittest discover -s python/tests -q
.\.venv-i01-314\Scripts\python.exe tools/generate_block_catalog.py --check
.\.venv-i01-314\Scripts\python.exe tools/generate_game_catalog.py --check
.\.venv-i01-314\Scripts\python.exe tools/smoke_i02.py
.\.venv-i01-314\Scripts\python.exe tools/smoke_i03.py
.\.venv-i01-314\Scripts\python.exe tools/smoke_i04.py
```

Перед Paper-run существующим wrapper/JDK25 выполняются test и shadowJar
для временной сборки; wheel не строится и не устанавливается. Runner фиксирует
хеши исходников, принимает флаг --plugin для этого временного JAR и использует
собственные порты, прежнее согласие EULA и независимый observer. Команды ниже
описывают уже выданные исторические поставки I01/v0.1.

smoke_i03.py добавляет два настоящих игровых TCP-подключения на отдельном
offline-стенде и два независимых Python TCP-подключения. Игровые клиенты стенда
не требуют GUI или внешней библиотеки; IDs пакетов экспортирует тестовый
observer именно закреплённого Paper. Для runner требуется свежий временный
observer JAR, собираемый существующей integration/observer-plugin Gradle-сборкой.
Это тестовая инфраструктура, её плагин не нужен обычному серверу.
Итог и границы проверок — [отчёт I03](reports/I03.ru.md).

smoke_i04.py использует тот же стенд для инвентарей/остатков, эффектов,
специальных сущностей и настоящей молнии. Наблюдатель проверяет состояние
через Paper независимо от ответов Minebridge. Для проверки последующих тиков
сущности нужны обычные условия симуляции: стенд удерживает нужные observer-чанки
и размещает игрока рядом с молнией. Production lease заканчивается после создания.

Отдельный helper `python/tests/ide-i04/` проверяет VS Code/Pylance на исходниках:
подготовка — `run.js --prepare <python.exe>` через встроенный Node portable Code;
дальше extensionDevelopmentPath указывает на эту папку, extensionTestsPath —
на run.js, workspace — .work/ide-i04-workspace, отдельный user-data-dir —
.work/ide-i04-user-data. Используется Python из .venv-tools без установленного
minebridge и `python.analysis.extraPaths=python/src`. Подсказки, определения,
сигнатуры и диагностики сохраняются в .work/ide-i04-results.json.
Этот helper не требует wheel и не меняет исторические IDE-проверки ниже.

I01 версии 0.2
-------------

Историческая пара I01: `minebridge-paper-0.2.0-dev1.jar` и Python `0.2.0.dev1`.
На этом этапе полный v0.2 ещё не был реализован. Контракт —
[V0_2_CONTRACT.ru.md](contracts/V0_2_CONTRACT.ru.md); запуск —
[QUICKSTART.ru.md](QUICKSTART.ru.md). Команды ниже из корня проекта:

```powershell
.\.venv-tools\Scripts\python.exe -m build --outdir dist/v0.2/i01 python
.\.venv-i01-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/v0.2/i01/minebridge-0.2.0.dev1-py3-none-any.whl
.\.venv-i01-314\Scripts\python.exe -I -m unittest discover -s python/tests -v
.\.venv-i01-314\Scripts\python.exe tools/smoke_i01.py
```

Для первого создания окружения: `py -3.14 -m venv .venv-i01-314`.
Java собирается существующим wrapper/JDK25 с `test shadowJar --offline`;
активный общий corpus — `protocol/v2/fixtures/corpus.json`. Итоговый JAR из
`plugin/build/libs/` копируется в `dist/v0.2/i01/` до Paper-проверки.
Runner использует уже принятый оператором EULA из проектного тестового стенда,
собственный игровой/TCP-порт, новые миры и установленный wheel, а не source import.
Он не устанавливает JAR на пользовательский рабочий сервер.

Команды T01–T10 ниже относятся к историческому v0.1 и его артефактам.

Команды выполняются из корня репозитория в PowerShell. Python unit-тестам не
нужен внешний сервер; проверки транспорта используют loopback TCP. Baseline — 3.11.
Python-сборка тех этапов записывалась в dist/dev. Артефакты dist/t01–dist/t10 —
сохранённые копии этапов из отчётов; текущими сборками их не перезаписываем.

Сборка Python-пакета:

```powershell
py -3.14 -m venv .venv-tools
.\.venv-tools\Scripts\python.exe -m pip install build==1.6.1
.\.venv-tools\Scripts\python.exe -m build --outdir dist/dev python
```

Build backend setuptools==84.2.0 закреплён в python/pyproject.toml.
Команда строит исходный архив и затем wheel из этого архива.

Проверка установленного wheel:

```powershell
py -3.14 -m venv .venv-t01-314
.\.venv-t01-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t01-314\Scripts\python.exe -I -m unittest discover -s python/tests -v
```

Повторить для Python 3.11 в отдельном venv. В проведённой проверке использован
CPython 3.11.17 из .tools/python, установленный uv 0.13.3 без регистрации в
Windows и без изменения PATH; системный Python не заменялся.

IDE helper лежит в python/tests/ide. Запускается настоящим VS Code через
extensionDevelopmentPath/extensionTestsPath с установленными Python/Pylance,
отдельными .work/ide-workspace и .work/ide-user-data. run.js сначала вызывается
с --prepare и путём Python из venv, где установлен wheel; затем exports.run
вызывается extension host. При прямом запуске Code.exe в режиме IDE переменная
ELECTRON_RUN_AS_NODE должна отсутствовать. Итог .work/ide-results.json должен
содержать status=passed, три константы и определения в site-packages.
С T07 helper дополнительно проверяет Minecraft.create, mc.setBlock/blocks/close,
mc.blocks.setBlock, keyword-only параметры create и data=0 обоих setBlock.
Нужен выбранный установленный wheel; для T10 используется свежий
.venv-t10-314 с wheel dist/t10. Исторические результаты сохранены отдельно:
.work/t01-ide-results.json и .work/t07-ide-results.json; результат T10 —
.work/t10-ide-results.json. 22 октября 2026 года пользователь исключил PyCharm
из приёмки: проверяется VS Code с Python/Pylance.

В T10 обычный установленный VS Code 1.142.0 не запускал новый test extension host из-за
занятого mutex обновления. Вместо остановки пользовательского IDE или updater
использован официальный portable-архив той же версии и commit
6d62b1d5dace93a33b3a6d3eca1317bd5e15bcb1. Его
[метаданные Microsoft](https://update.code.visualstudio.com/api/versions/1.142.0/win32-x64-archive/stable)
содержат SHA-256
ace1da7d1432d43c1ab4b2bbf643f6494f6d25dec07494976755eac522cd50d9.
При отсутствии этой локальной копии подготовка выполняется отдельно:

```powershell
$ideToolRoot = Join-Path (Get-Location) '.tools/vscode-t10'
New-Item -ItemType Directory -Path $ideToolRoot -Force | Out-Null
$ideMetadataUrl = 'https://update.code.visualstudio.com/api/versions/1.142.0/win32-x64-archive/stable'
$ideMetadata = Invoke-RestMethod -Uri $ideMetadataUrl
$ideExpectedSha = 'ace1da7d1432d43c1ab4b2bbf643f6494f6d25dec07494976755eac522cd50d9'
if ($ideMetadata.version -ne '6d62b1d5dace93a33b3a6d3eca1317bd5e15bcb1' -or $ideMetadata.sha256hash -ne $ideExpectedSha) { throw 'Unexpected VS Code archive metadata' }
$ideArchive = Join-Path $ideToolRoot 'VSCode-win32-x64-1.142.0.zip'
Invoke-WebRequest -Uri $ideMetadata.url -OutFile $ideArchive -UseBasicParsing
if ((Get-FileHash -LiteralPath $ideArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ideExpectedSha) { throw 'VS Code archive SHA-256 mismatch' }
Expand-Archive -LiteralPath $ideArchive -DestinationPath (Join-Path $ideToolRoot 'app')
```

Архив загружается из URL в метаданных Microsoft, а не из текущего канала latest.
Фактические метаданные и проверка сохранены в .tools/vscode-t10/archive-metadata.json
и archive-verification.json. Глобальные профиль, расширения и процесс обновления
не изменяются; используются уже установленные Python/Pylance. Запуск после
установки выбранного wheel в .venv-t10-314:

```powershell
$ideRepo = (Get-Location).Path
$ideCode = Join-Path $ideRepo '.tools/vscode-t10/app/Code.exe'
$ideHelper = Join-Path $ideRepo 'python/tests/ide/run.js'
$idePython = Join-Path $ideRepo '.venv-t10-314/Scripts/python.exe'
$env:ELECTRON_RUN_AS_NODE = '1'
$idePrepareArguments = @(
    '"' + $ideHelper + '"'
    '--prepare'
    '"' + $idePython + '"'
)
$idePrepare = Start-Process -FilePath $ideCode -ArgumentList $idePrepareArguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput .work/t10-ide-prepare-stdout.log -RedirectStandardError .work/t10-ide-prepare-stderr.log
if ($idePrepare.ExitCode -ne 0) { throw 'IDE preparation failed' }
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Remove-Item Env:VSCODE_IPC_HOOK_CLI -ErrorAction SilentlyContinue
$ideArguments = @(
    '--extensionDevelopmentPath="' + (Join-Path $ideRepo 'python/tests/ide') + '"'
    '--extensionTestsPath="' + $ideHelper + '"'
    '--user-data-dir="' + (Join-Path $ideRepo '.work/ide-user-data') + '"'
    '--extensions-dir="' + (Join-Path $env:USERPROFILE '.vscode/extensions') + '"'
    '--disable-workspace-trust'
    '--skip-welcome'
    '--skip-release-notes'
    '--new-window'
    '"' + (Join-Path $ideRepo '.work/ide-workspace') + '"'
)
$ideProcess = Start-Process -FilePath $ideCode -ArgumentList $ideArguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput .work/t10-ide-stdout.log -RedirectStandardError .work/t10-ide-stderr.log
if ($ideProcess.ExitCode -ne 0) { throw 'IDE extension-host tests failed' }
$ideResult = Get-Content .work/ide-results.json -Raw -Encoding UTF8 | ConvertFrom-Json
if ($ideResult.status -ne 'passed') { throw 'IDE checks did not pass' }
Copy-Item -LiteralPath .work/ide-results.json -Destination .work/t10-ide-results.json
```

Helper проверяет фактические completion/hover/definition/signature providers,
переходы в site-packages выбранного venv и сохраняет снимок diagnostics. Отдельный
Python import запускается с -I и запретом socket.connect/connect_ex/create_connection;
networkAttempts=0 относится к этому import, а не ко всему сетевому трафику IDE.
Ни Minecraft, ни Paper для IDE-проверки не нужны. Версии и результат конкретного
запуска приведены в [reports/T10.ru.md](reports/T10.ru.md).

Для T02 portable-инструменты загружает tools/bootstrap_t02.py. Он проверяет
зафиксированные SHA-256, распаковывает JDK/Gradle только в .tools, сохраняет
.tools/t02-toolchain.json и не принимает Minecraft EULA. Точные команды сборки
и серверного прогона:

```powershell
.\.venv-tools\Scripts\python.exe tools/bootstrap_t02.py
$t02Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $t02Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
$env:DEBUG = $null
.\plugin\gradlew.bat -p plugin clean build --no-daemon
```

После каждой команды проверять код завершения. Результат —
plugin/build/libs/minebridge-paper-0.1.0-dev.jar; отчёт JUnit —
plugin/build/reports/tests/test/index.html. Повторная сборка при заполненном
cache может выполняться с --offline. Зафиксированные зависимости проверяются
по plugin/gradle.lockfile и plugin/gradle/verification-metadata.xml.
В обычной сборке не применять --write-locks/--write-verification-metadata:
они предназначены для отдельного осознанного обновления зависимостей.

JDK и Gradle используются в текущем процессе PowerShell; системные настройки
не меняются. Точные версии, URL и SHA-256:
[ENVIRONMENT_LOCK.ru.md](ENVIRONMENT_LOCK.ru.md).

Настоящий Paper, исходные проверки жизненного цикла T02:

```powershell
.\.venv-tools\Scripts\python.exe tools/smoke_t02.py --prepare
```

Подготовка копирует собранный плагин в .work/t02-server, выбирает локальный
игровой порт и создаёт eula.txt со значением false, если файла ещё нет.
Скрипт никогда не принимает EULA. После прочтения
[Minecraft EULA](https://www.minecraft.net/en-us/eula) оператор сам записывает
eula=true в .work/t02-server/eula.txt. Для этого проекта согласие оператора
получено в чате 20 октября 2026 года и записано в локальный файл стенда.

```powershell
.\.venv-tools\Scripts\python.exe tools/smoke_t02.py
```

Прогон запускает Paper четыре раза: корректная конфигурация, пустой токен,
отсутствующий мир, некорректный YAML. Каждый сценарий ожидает готовность Paper,
проверяет ожидаемое состояние плагина, посылает stop и ждёт завершения процесса.
Логи сохраняются в .work/t02-*.log, сводка — .work/t02-smoke-results.json;
успех требует allPassed=true и кода завершения 0. Токен генерируется локально,
его отсутствие в логах также проверяется. Положительный сценарий дополнительно
проверяет отсутствие неожиданных ERROR/SEVERE/FATAL при запуске и остановке.

Стенд использует loopback, отдельный мир t02-world, online-mode=true, RCON и
query выключены. Перед прогоном нужен свободный 1 ГиБ heap плюс память JVM/ОС;
первому запуску нужен доступ к загрузкам Minecraft/Paper. Скрипт перезаписывает
конфигурацию только своего стенда и не предназначен для сервера занятий.
На этапе T02 порт 4711 только валидировался. С T04 плагин открывает listener;
транспорт архивного T04 проверяет tools/smoke_t04.py ниже. Полную текущую матрицу
проверяет tools/smoke_t10.py из раздела T10. Старый harness T02
сохраняет проверки жизненного цикла и не подтверждает готовность транспорта.

Проверки codec и транспорта, T03–T04
-----------------------------------

Используются те же инструменты и venv, подготовленные выше. Собрать и установить
новый wheel, затем выполнить тесты в обоих изолированных интерпретаторах:

```powershell
.\.venv-tools\Scripts\python.exe -m build --outdir dist/dev python
.\.venv-t01-311\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t01-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t01-311\Scripts\python.exe -I -m unittest discover -s python/tests -v
.\.venv-t01-314\Scripts\python.exe -I -m unittest discover -s python/tests -v
```

Ожидается 122 теста, один из них проверяет 247 общих сценариев. Корпус берётся
из protocol/v1/fixtures/corpus.json в checkout; в wheel ему поставляться не нужно.
Тесты импортируют установленный пакет, а не src.

При настроенных JAVA_HOME и GRADLE_USER_HOME из команды T02:

```powershell
.\plugin\gradlew.bat -p plugin clean build --no-daemon
& (Join-Path $env:JAVA_HOME 'bin/java.exe') -cp 'plugin/build/classes/java/test;plugin/build/libs/minebridge-paper-0.1.0-dev.jar' dev.minebridge.protocol.ShadedCodecProbe
```

Первая сборка T03 загружает новые зафиксированные зависимости; затем допустим
--offline. В T08 было 381 JUnit cases; текущая T10-сборка ожидает 387.
Отдельный probe должен вывести Shaded codec probe passed.
Gradle задаёт абсолютный путь общего корпуса через minebridge.fixtures
и учитывает содержимое файла как вход задачи test.
Shadow и его зависимости зафиксированы в buildscript-gradle.lockfile;
runtime/compile/test — в gradle.lockfile; SHA — в verification-metadata.xml.

Production JAR содержит изолированный Jackson. Для Paper используется основной
minebridge-paper-0.1.0-dev.jar; -plain не содержит runtime-библиотеку.

Два Python-транспорта против настоящего Java-транспорта в отдельном test harness:

```powershell
.\.venv-t01-314\Scripts\python.exe -I tools/check_t04_loopback.py
```

Нужны результаты Java-сборки (test classes и production JAR) и установленный
wheel. Harness в src/test отвечает METHOD_NOT_FOUND и только в тесте вызывает
markReady; он не включается в поставку и не выполняет игровые операции.
Ожидается .work/t04-loopback-results.json с allPassed=true, requests=24,
sessions=2 и partialThirdSessionDidNotBlock=true. JVM должна завершиться с 0.

Историческая проверка Paper на артефакте T04 и ранее принятой EULA стенда:

```powershell
.\.venv-tools\Scripts\python.exe tools/smoke_t04.py
```

Этот harness рассчитан на промежуточный T04 без handshake; для полной текущей
матрицы используется smoke_t10.py ниже. smoke_t06.py сохранён как raw-регрессия.
Архивный прогон использует .work/t02-server,
отдельный временный TCP-порт и не меняет
согласие EULA. Шесть сценариев: transport, restart на том же порту, occupied-port,
blank-token, missing-world, invalid-yaml. Каждый ожидает и Done Paper, и
результат запуска listener/диагностику; одного Done недостаточно.
Проверяются два соединения, частичный/повреждённый клиент, IDs, переполнение
входной очереди, deadline незавершённого handshake, закрытие при stop.
Ожидается .work/t04-paper-results.json с allPassed=true и шестью exitCode=0;
журналы — .work/t04-paper-*.log. Тестовый токен не должен появляться в stdout.

В listenAddress задаётся числовой IPv4/IPv6, например 127.0.0.1. Имена для bind
не разрешаются, чтобы shutdown не зависел от DNS. Python connect допускает
hostname/localhost; синхронный OS resolver выполняется до общего TCP deadline.
Срок передачи запроса и срок получения полного ответа отдельные; поток байтов
не продлевает их. Повторов при timeout/обрыве нет.

В архивном T04 READY ещё не наступал: корректный hello закрывался через 5 секунд.
Архивный T05 проверялся следующими командами.

Handshake и контекст мира, T05
-----------------------------

После сборки и установки актуального wheel в оба venv выполнить:

```powershell
.\plugin\gradlew.bat -p plugin build worldMetadataProbeJar --offline --no-daemon
.\.venv-tools\Scripts\python.exe tools/smoke_t05.py
```

Этот исторический harness рассчитан на JAR T05: он ожидает ещё не реализованный
blocks.set. Для текущего JAR использовать smoke_t10.py ниже; архивные отчёты
T05 сохраняются как доказательство предыдущего этапа.

Блоки команд исторических T04/T05 приведены для справки: prepare() берёт JAR
из plugin/build/libs и не восстанавливает dist/t04 или dist/t05 автоматически.
Их не запускать с текущей сборкой: ожидания handshake/blocks.set уже изменились.
Историческая публичная проверка — smoke_t07.py; полная текущая — smoke_t10.py.

Нужны JAVA_HOME/GRADLE_USER_HOME из раздела T02 и заранее установленный wheel
в .venv-t01-314: harness запускает два независимых Python-процесса с -I.
Токен создаётся локально и передаётся им через MINEBRIDGE_TOKEN, не через CLI.
tools/check_t05_client.py — приватный тестовый peer, не учебный пример API.

Задача worldMetadataProbeJar отдельно собирает read-only test fixture из
integration/fixtures/world_metadata_probe. Этот плагин только читает на потоке
Paper имена/UUID/высоты миров и сохраняет TSV с Base64-именами. Он не обращается
к bridge, блокам или игрокам, не создаёт миры и не добавляет RPC. В основной JAR
не включён. Harness временно копирует fixture на локальный стенд и убирает JAR
после прогона. Выгрузка/старт мира намеренно не управляются Python-клиентом.

Ожидается .work/t05-paper-results.json с allPassed=true и шестью exitCode=0:
handshake, alternate-default, occupied-port, blank-token, missing-world,
invalid-yaml. В handshake проверяются два установленных Python-клиента,
одинаковый id=1 при разных sessionId, отказ A без нарушения B, реальные метаданные
мира, ошибки auth/версий/параметров, запрет до hello, повторный hello, сроки и stop
с двумя READY-сессиями. alternate-default заново занимает тот же TCP-порт,
выбирает другой фактически загруженный мир и запрещает прежний defaultWorld.
Логи — .work/t05-paper-*.log, включая отдельные журналы успешных/ошибочных запусков.
Токен не должен присутствовать ни в выводе сервера, ни в выводе Python-процессов.

Помимо согласованного system.hello дополнительных RPC нет; зависимости сохранены.
Публичный Minecraft.create
относится к T07; blocks.set до T06 отвечает UNSUPPORTED_FEATURE/not-applied.
Промежуточный hello сохраняет обязательную capabilities=["blocks.set"] из
замороженного контракта, поэтому T05 нельзя считать завершённым v0.1.
Результаты и архивы этапа: [reports/T05.ru.md](reports/T05.ru.md).

Одна серверная запись блока, T06
-------------------------------

С актуальным wheel в venv (команды сборки/установки выше), JAVA_HOME и
GRADLE_USER_HOME из раздела T02:

```powershell
.\plugin\gradlew.bat -p plugin clean build blockSmokeProbeJar --offline --no-daemon
.\.venv-tools\Scripts\python.exe tools/smoke_t06.py
```

blockSmokeProbeJar — отдельная явная задача для test fixture
integration/fixtures/block_smoke_probe. Основной JAR не включает fixture,
не получает новых RPC и не зависит от её классов. Fixture принимает только
локальную консоль: подготавливает/удерживает три тестовых чанка, читает реальные
BlockData, проверяет loaded-состояние и временно задаёт border. При нормальной
остановке восстанавливает затронутые блоки и border, освобождает tickets.

Harness публикует консольные результаты по correlation в отдельных неизменяемых
results/<id>.tsv и удаляет после чтения. Это исключает перезапись файла, чей
дескриптор держит Windows reader. Нельзя предполагать, что соседний с подготовленным
чанк выгружен: загруженность дальнего отрицательного кандидата проверяется до
и после отказа CHUNK_NOT_LOADED. floorDiv/усечение различаются unit-тестами.

Ожидается .work/t06-paper-results.json с allPassed=true, шестью exitCode=0 и
trace-сводками успешных запусков. Проверяются AIR/STONE/COBBLESTONE и современный
ключ oak_planks, no-op, отрицательная позиция, raw-ошибки, высоты, border вплоть
до размера 1 с дробным центром, две одновременно открытые TCP-сессии и FIFO,
stop/restart на том же порту, занятый порт и три ошибки конфигурации.
Успешные блоки читаются независимо через Paper API после ACK. Две TCP-сессии
T06 обслуживаются потоками одного harness; два отдельных Python-процесса
проверялись в T05, полный сценарий пользовательских процессов остаётся T09.

Только для локальной диагностики harness запускает JVM с
-Dminebridge.diagnostics=true. По умолчанию trace выключен; он не управляется
через RPC/config token. Буфер 256 событий фиксирует sequence, фазы setter/ACK,
sessionId/requestId/applySequence и поток, затем выгружается вне lock Session.
Сравниваются значения sequence в точках событий, не время прихода stdout/TCP.
Диагностические записи не являются измерением производительности: вывод
журнала находится вне бюджета операций, а один setter не прерывается по 2 мс.

Это smoke T06; полный observer/gate реализован в T08 ниже. Minecraft.create и
учебный setBlock реализованы в T07. Отчёт и SHA: [reports/T06.ru.md](reports/T06.ru.md).

Публичный Python API, T07
------------------------

Собрать и установить wheel текущими командами dist/dev выше в оба venv,
затем выполнить 122 unit-теста в каждом интерпретаторе с -I. Фасад доступен
как from minebridge.minecraft import Minecraft и from minebridge import Minecraft.
Пример — examples/set_block.py; перед запуском задать MINEBRIDGE_TOKEN и выбрать
позиции загруженного чанка. Фасад не запускает Paper и не генерирует чанки.

Настоящий Paper с установленным wheel в .venv-t01-314 и принятой EULA стенда:

```powershell
.\plugin\gradlew.bat -p plugin clean build blockSmokeProbeJar --offline --no-daemon
.\.venv-tools\Scripts\python.exe tools/smoke_t07.py
```

JAR и fixture T06 сохранены без изменений. Harness запускает два отдельных
Python-процесса с -I и установленным wheel. Один использует явный token, второй
MINEBRIDGE_TOKEN; секрет приходит через окружение тестового процесса, не argv.
tools/check_t07_client.py выполняет только публичные create/setBlock/close;
внутренний context читается лишь для test correlation, не является публичным API.

Ожидается .work/t07-paper-results.json с allPassed=true, шестью exitCode=0,
разными PID/sessionId и 10 successfulPublicSetCalls суммарно. Проверяются root/
namespace, 4/block.COBBLESTONE/современный ключ/BlockSpec, отрицательное округление,
локальные и серверные ошибки, перекрывающиеся вызовы двух процессов, stop
с живыми объектами, отсутствие reconnect и restart на том же TCP-порту.
Каждый успешный результат None сопоставляется с независимым чтением Paper.
Trace фиксирует 10 мутаций/30 событий с APPLY_DONE перед ACK_ENQUEUED.
Дополнительно выполняются занятый порт и три ошибочные конфигурации.

Подсказки IDE проверяются существующим python/tests/ide/run.js с --prepare и
test extension host настоящего VS Code/Pylance. В тестовом профиле используется
интерпретатор с установленным wheel; runtime import проверяется с запретом сетевых
подключений. Подробные сигнатуры и версии записаны в .work/t07-ide-results.json.
Этот IDE-тест не требует Minecraft. Observer/gate реализован в T08 ниже;
V/D описаны в T09 ниже; полная процедура V/D/N/F — в разделе T10.
Отчёт/артефакты: [reports/T07.ru.md](reports/T07.ru.md).

Независимый observer и управляемый gate, T08
-------------------------------------------

Исторический стенд T08 собирается отдельно от ранних fixture:

```powershell
$t08Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $t08Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
$env:DEBUG = $null
.\plugin\gradlew.bat -p plugin clean build :observer:build --offline --no-daemon
.\.venv-tools\Scripts\python.exe -m build --outdir dist/dev python
.\.venv-t01-311\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t01-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t01-311\Scripts\python.exe -I -m unittest discover -s python/tests -v
.\.venv-t01-314\Scripts\python.exe -I -m unittest discover -s python/tests -v
.\.venv-tools\Scripts\python.exe tools/smoke_t08.py --wheel dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
```

С --offline нужен заранее заполненный Gradle cache T02–T08; первая разрешённая
сборка выполняется без этого флага с теми же lock/checksum. Проверять exit code
после каждой команды. На этапе T08 ожидались 381 Java cases и по 122 Python-теста;
для текущей T10-сборки ожидаются 387 Java cases и те же 122 Python-теста.
Observer JAR: integration/observer-plugin/build/libs/minebridge-observer-0.1.0-dev.jar;
production JAR остаётся plugin/build/libs/minebridge-paper-0.1.0-dev.jar.
Его локальный Java test-control включается только JVM-флагом
-Dminebridge.testControl=true; обычный запуск оставляет его выключенным.

smoke_t08 не строит/устанавливает пакеты и не принимает EULA. Он проверяет
совпадение установленного wheel, свободный 127.0.0.1:4711 и существующий
.work/t02-server/eula.txt с ранее принятым согласием. Создаёт новую директорию
и мир, копируя только bootstrap cache и точный файл согласия. Запускает Paper
с одним production JAR в двух режимах: 4 теста с test-control, 1 без него.
Итог .work/t08-paper-results.json должен содержать allPassed=true, оба
exitCode=0 и failures/errors/skipped=0. Observer/ticks/gate/trace служат
барьерами; блоки читаются независимо от production обработчика.

Подробные условия и границы — [integration/README.md](../integration/README.md).
Фактические результаты и SHA — [reports/T08.ru.md](reports/T08.ru.md).
Полные V/D сценарии описаны в T09 ниже; V/D/N/F — в разделе T10.

Полная матрица V/D на настоящем Paper, T09
-----------------------------------------

T09 проверяет артефакты T08 без изменения Python/Java runtime и observer.
Четыре сохранённых файла в dist/t09 побитово совпадают с dist/t08.
Для уже подготовленного стенда и архивного wheel:

```powershell
.\.venv-t01-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/t09/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-tools\Scripts\python.exe tools/smoke_t09.py
```

Это историческое воспроизведение требует согласованных JAR T09: runner берёт
production/observer из build-каталогов и не восстанавливает их из dist/t09.
Архивный wheel и текущие JAR T10 не образуют исходный набор T09. Текущую приёмку
выполняет smoke_t10.py; для отдельного прогона старого runner с пересборкой
dist/dev выбранный wheel предварительно устанавливается в .venv-t01-314.

После текущей пересборки/установки dist/dev из команд выше:

```powershell
.\.venv-tools\Scripts\python.exe tools/smoke_t09.py --wheel dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
```

Runner всегда создаёт два отдельных стенда/мира с новыми runId/UUID. На каждом
последовательно проходят самопроверка observer и все V01–V07/D01–D04: 12 тестов,
0 failures/errors/skipped. Клиенты — отдельные процессы установленного wheel
с -I. Production bridge остаётся 127.0.0.1:4711; дополнительный тестовый relay
слушает ephemeral loopback port и сохраняет реальные полные кадры с удалённым
token. Он не подменяет ответы, но меняет TCP-сегментацию; N/F проверяются в T10.

Pending подтверждается ответом самого worker через упорядоченную control pipe,
а также gate/trace и отсутствием ACK в capture. В конце ожидаются закрытые relay
соединения и пустой список сессий Paper, проверяются droppedEvents=evictedEvents=0.
Успех требует одинаковых SHA артефактов/тестовых исходников обоих прогонов,
неизменных исходников во время испытаний и разных UUID мира. EULA, сборка,
установка и прошлые стенды автоматически не меняются.

Общий итог — .work/t09-paper-results.json, данные каждого прогона —
integration/artifacts/t09-<runId>/. Подробности — [integration/README.md](../integration/README.md),
фактическая приёмка и SHA — [reports/T09.ru.md](reports/T09.ru.md).

Полная техническая матрица V/D/N/F, T10
--------------------------------------

Текущая процедура использует те же закреплённые JDK 25.0.4.1+1, Gradle 9.1.0
и Paper 26.2 build 133. Сборка и установка выполняются до runner; его запуск
не скачивает инструменты, не собирает пакеты и не принимает EULA. Для новой
сборки используются dist/dev и отдельные venv; существующие dist/t01–dist/t10
сохраняются неизменными. В T10 Python runtime не менялся; wheel пересобран
с обновлённым README в метаданных.

При первичной подготовке .venv-t10-311 и .venv-t10-314 должны отсутствовать.
Python 3.11.17 уже установлен локально в .tools/python; Python 3.14.7 доступен
через py -3.14. При заполненном Gradle cache:

```powershell
$t10Tools = Get-Content .tools/t02-toolchain.json -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JAVA_HOME = $t10Tools.javaHome
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.tools/gradle-cache'
$env:DEBUG = $null
.\plugin\gradlew.bat -p plugin clean build :observer:build --offline --no-daemon
.\.venv-tools\Scripts\python.exe -m build --outdir dist/dev python
& .\.tools\python\cpython-3.11.17-windows-x86_64-none\python.exe -m venv .venv-t10-311
py -3.14 -m venv .venv-t10-314
.\.venv-t10-311\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t10-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t10-311\Scripts\python.exe -I -m unittest discover -s python/tests -v
.\.venv-t10-314\Scripts\python.exe -I -m unittest discover -s python/tests -v
.\.venv-tools\Scripts\python.exe tools/smoke_t10.py --wheel dist/dev/minebridge-0.1.0.dev0-py3-none-any.whl
```

После каждой команды проверяется код завершения; ожидаются 387 JUnit cases
и по 122 Python-теста без ошибок и пропусков. Если закреплённых зависимостей
нет в cache, первая сборка выполняется без --offline с прежними lock/checksum.
При воспроизведении сохранённого wheel T10 его устанавливают в оба venv вместо
dist/dev, а runner запускают с его путём по умолчанию:

```powershell
.\.venv-t10-311\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/t10/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-t10-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/t10/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-tools\Scripts\python.exe tools/smoke_t10.py
```

JAR из build-каталогов должны соответствовать выбранному набору; пути и SHA
фиксируются в manifest. Runner сверяет установленный .venv-t10-314 с wheel,
Paper SHA, свободный 127.0.0.1:4711 и точную копию существующего согласия EULA
из .work/t02-server/eula.txt. Согласие не создаётся заново.

Один вызов всегда выполняет основной suite из 32 тестов, затем V/D из 12
тестов на новом мире с другим UUID и один default-off тест на этом втором
мире. Всего четыре старта Paper: primary, restart внутри F04, repeat и
default-off. Основной suite включает oracle + 11 V/D, 6 validation, 8 protocol,
1 kernel slow-reader, 4 fault и 1 shutdown/restart тест. N07 имеет два результата,
N10 — пять; каждый прочий V/D/N/F сценарий — один. Успех требует полного
покрытия, allPassed=true, нулевых failures/errors/skipped, одинаковых хешей
артефактов и исходников между основным запуском и свежим повтором.

WireTap для каждой группы сохраняет реальные полные кадры по пути к production
4711; raw peers для framing идут напрямую. FaultProxy удерживает настоящий ACK
после применения блока; ControlledPeer в F05 подаёт синтетические ответы и
не служит доказательством изменения Paper. Kernel slow-reader не использует
writerPause: реальный нечитающий socket должен создать backpressure при
продолжающейся работе второй сессии. Отдельные управляемые output-тесты проверяют
границу очереди 8 и deadline. Trace использует checkpoints: вытеснение старой
истории допустимо, но текущий проверяемый интервал должен сохраняться полностью,
а droppedEvents — оставаться 0. F04 после restart сравнивает исходные BlockData,
включая заведомо не-AIR позицию, и проверяет новую публичную запись.

Во время приёмки нельзя менять tools/smoke_t10.py, integration/tests, Java
production/observer и конфиг server.properties: runner фиксирует их хеши до
старта и сверяет после. Итог — .work/t10-paper-results.json; доказательства —
integration/artifacts/t10-<runId>/. Подробности процедуры и её границы —
[integration/README.md](../integration/README.md), фактические результаты
конкретного запуска — [reports/T10.ru.md](reports/T10.ru.md).

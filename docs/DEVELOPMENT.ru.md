Разработка и воспроизведение проверок
===================================

Команды выполняются из корня репозитория в PowerShell. Python unit-тестам не
нужен внешний сервер; проверки транспорта используют loopback TCP. Baseline — 3.11.
Текущая Python-сборка записывается в dist/dev. Артефакты dist/t01–dist/t09 —
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
Нужен актуальный установленный wheel T07; исторический результат T01 сохранён
в .work/t01-ide-results.json, актуальный T07 — в .work/t07-ide-results.json.

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
транспорт архивного T04 проверяет tools/smoke_t04.py ниже. Текущую сборку
проверяет tools/smoke_t07.py. Старый harness T02
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
--offline. С T08 ожидаются 381 JUnit cases и сообщение Shaded codec probe passed.
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

Этот harness рассчитан на промежуточный T04 без handshake; с текущим JAR нужно
использовать smoke_t07.py ниже. smoke_t06.py совместим с текущим JAR как raw-регрессия.
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
blocks.set. Для текущего JAR использовать smoke_t07.py ниже; архивные отчёты
T05 сохраняются как доказательство предыдущего этапа.

Блоки команд исторических T04/T05 приведены для справки: prepare() берёт JAR
из plugin/build/libs и не восстанавливает dist/t04 или dist/t05 автоматически.
Их не запускать с текущей сборкой: ожидания handshake/blocks.set уже изменились.
Текущая публичная проверка — smoke_t07.py; совместимая raw — smoke_t06.py.

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
V/D проверены в T09 ниже, N/F остаются T10.
Отчёт/артефакты: [reports/T07.ru.md](reports/T07.ru.md).

Независимый observer и управляемый gate, T08
-------------------------------------------

Текущий полный стенд T08 собирается отдельно от исторических fixture:

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
после каждой команды. Ожидаются 381 Java cases и по 122 Python-теста.
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
Полные V/D сценарии проверены в T09 ниже; N/F остаются T10.

Полная матрица V/D на настоящем Paper, T09
-----------------------------------------

T09 проверяет артефакты T08 без изменения Python/Java runtime и observer.
Четыре сохранённых файла в dist/t09 побитово совпадают с dist/t08.
Для уже подготовленного стенда и архивного wheel:

```powershell
.\.venv-t01-314\Scripts\python.exe -m pip install --no-deps --force-reinstall dist/t09/minebridge-0.1.0.dev0-py3-none-any.whl
.\.venv-tools\Scripts\python.exe tools/smoke_t09.py
```

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

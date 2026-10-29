Зафиксированная среда Minebridge
===============================

0.3.1 — 29 октября 2026 года
----------------------------

Paper 26.2 build 133, Temurin JDK 25.0.4.1+1, Gradle 9.1.0,
Python 3.11.17 / 3.14.7. Версии библиотеки/плагина 0.3.1, протокол 2.0.
Setuptools 84.2.0, build 1.6.1, Twine 7.0.0;
SOURCE_DATE_EPOCH=1793232000. MIT-лицензия; Python runtime-зависимостей нет.

Сборка: 785 Java-проверок без ошибок/пропусков. На двух чистых окружениях
установленного wheel — по 242 Python-проверки без пропусков. Wheel содержит
51 запись / 46 файлов пакета, MIT/PEP 639 и каталоги; JAR — Java class major 69,
лицензии проекта и Jackson, без observer и Paper server. Проверены RECORD,
совпадение sdist/исходников, строгий Twine, изолированные импорты без сети.
Настоящий VS Code 1.142.0 / Python 2026.10.0 / Pylance 2026.4.1 подтвердил
playerByName, PeacefulSpawnError, их типы и определения из site-packages.

Хеши сборки — `dist/v0.3.1/BUILD.json`, проверки —
`.work/v031-python-results.json`, `.work/v031-package-results.json`,
`.work/ide-v031-results.json`. Полная серверная приёмка фиксируется отдельно
в `.work/v031-paper-results.json`: allPassed=true, 10 групп новой пары и 3 группы
старой 0.3.0. [Отчёт](reports/V0_3_1.ru.md). Ниже только история прежних версий.

Приёмка поставки 0.3.0 / I05 — 29 октября 2026 года
------------------------------------------------

Версии SDK/plugin — 0.3.0, протокол 2.0. Сборка и проверки установленного wheel/IDE
прошли; **финальная общая Paper-приёмка завершена, `allPassed=true`**.
Исторические source-прогоны ниже относятся к dev-версиям и сохраняются отдельно.

Paper 26.2 build 133, Temurin JDK 25.0.4.1+1, Gradle 9.1.0, Python 3.11.17/3.14.7;
прежние dependency locks/verification metadata. Python build system:
setuptools 84.2.0, SOURCE_DATE_EPOCH=1793145600 (28 октября 2026 года), wheel из sdist.
Дата сборки сохранена; приёмка завершена 29 октября. Метаданные
gzip/tar sdist нормализованы, байты содержимого сверены. Зависимостей времени выполнения нет.
Итоговые файлы находятся в `dist/v0.3`; `dist/v0.2` и `dist/v0.2.1` сохранены.

Подтверждено: 777 Java-тестов без ошибок/пропусков и по 238 тестов без пропусков
на обоих чистых `.venv-v03-311`/`.venv-v03-314` с установленным wheel. В wheel 50 записей,
46 файлов пакета; RECORD и соответствие sdist/исходникам проверены.

Настоящая IDE: VS Code 1.142.0 / Python extension 2026.10.0 /
Pylance 2026.4.1; отдельный профиль/рабочая папка. 11 каталогов, 30 сигнатур,
11 выведенных типов, 7 ожидаемых диагностик неправильных типов, 0 диагностик
корректного примера. Определения из установленного site-packages, все 46 файлов
совпадают с wheel SHA `9e0e3ac14efcbf419d4877e824bdbec63e756b797e1cc66e31095658b5ae104e`.

[Команды и условия финализации](DEVELOPMENT.ru.md). Результаты:
`.work/v03-i05-build-results.json`, `.work/v03-i05-package-results.json`,
`.work/ide-v03-results.json`, `.work/v03-i05-paper-results.json`.
[Отчёт I05](reports/V0_3_I05.ru.md): 19 проверок основного сценария, свежий мир
с прежним config и настоящая baseline со старым плагином и SDK 0.2.1 прошли.
Принятые manifests находятся в `integration/artifacts/v03-i05-<runId>/manifest.json`:

- основной — `bde72a669dff4a90ab089f7240136b64`;
- свежий мир — `ffac0ba6f7084e87afae14e39e0d99da`;
- baseline 0.2.1 — `451fc637425c4ea2923563d5b5044156`.

Замеры 100/1000 buffered setBlock включают подтверждённый flush, без logging и
event flood, на четырёх заранее загруженных и удерживаемых чанках. Перед замерами
каждый свежий SDK-процесс выполняет 1000 нетаймируемых setBlock и flush;
на итоговом плагине порядок SDK — 0.3.0 / 0.2.1 / 0.2.1 / 0.3.0.
Старая plugin+SDK baseline и постоянная итоговая сессия после событийного сценария
сохранены отдельно. Это локальная проверка с двумя игровыми клиентами;
работа по LAN, полный класс и пользовательский Paper build 99 не проверялись.
`RELEASE.json` финализируется после успешных проверок и повторной сверки входных SHA.

Исходники0.3 / I04 — 28 октября2026 года
--------------------------------------

Текущая source-версия0.3.0.dev4, протокол2.0. Та же закреплённая среда:
Paper26.2 build133 / Temurin JDK25.0.4.1+1 / Gradle9.1.0 /
Python3.11.17 и3.14.7. Итог:777 Java tests, по238 Python tests,509 corpus
cases и13 групп настоящей Paper-приёмки точных слотов с двумя Python-процессами.
[Отчёт и SHA](reports/V0_3_I04.ru.md), [команды](DEVELOPMENT.ru.md).
Временный dev4 JAR используется только из build/; установочные JAR/wheel0.3,
общая приёмка и IDE-проверки остаются на I05. Стабильная поставка0.2.1 сохранена.
Ниже — исторические результаты.

Исходники 0.3 / I03 — 28 октября 2026 года
----------------------------------------

Текущая source-версия 0.3.0.dev3, протокол 2.0. Среда Paper26.2 build133 /
Temurin JDK25.0.4.1+1 / Gradle9.1.0 / Python3.11.17 и3.14.7 сохранена.
Итог: 693 Java tests, по 223 Python tests, 439 shared corpus cases и 13 групп
настоящей Paper-приёмки с двумя Python OS-процессами и игровыми TCP-клиентами.
[Отчёт и SHA](reports/V0_3_I03.ru.md), [команды](DEVELOPMENT.ru.md).
Каталог damageCause экспортирован из native API133 (33 значения).
Установочные JAR/wheel 0.3 и проверка IDE остаются на I05; поставка 0.2.1
не заменена. Ниже — исторические результаты.

Исходники 0.3 / I01–I02 — 27 октября 2026 года
--------------------------------------------

Текущая source-версия 0.3.0.dev2, протокол 2.0. Paper26.2 build133,
Temurin JDK25.0.4.1+1, Gradle9.1.0, Python3.11.17/3.14.7; закреплённые API,
Gradle lock/verification и существующий toolchain cache сохранены.
[Отчёт I01](reports/V0_3_I01.ru.md), [отчёт I02](reports/V0_3_I02.ru.md),
[команды разработки](DEVELOPMENT.ru.md). I02: 618 Java tests, 209 tests на каждом
Python и 9 локальных Paper-сценариев. Временный JAR используется только в build/,
wheel 0.3 ещё не собирался, IDE-проверка установочного пакета остаётся на I05.
Стабильные артефакты 0.2.1 ниже не заменены.

Исправление 0.2.1 — 26 октября 2026 года
--------------------------------------

Тот же Paper 26.2 build 133 / Temurin JDK 25.0.4.1+1 / Gradle 9.1.0.
Установленные wheel проверены на Python 3.11.17 и 3.14.7. Сборка Python:
setuptools 84.2.0, SOURCE_DATE_EPOCH=1792972800. Локальная точечная приёмка
нормального выхода и server logging: [отчёт](reports/V0_2_1.ru.md),
[метаданные](../dist/v0.2.1/RELEASE.json). Ниже сохранена среда 0.2.0/I05.

Итоговая поставка v0.2.0 / I05 — 25 октября 2026 года
--------------------------------------------------

Проверены итоговые JAR/wheel 0.2.0 на Windows x64: Paper 26.2 build 133,
Temurin JDK 25.0.4.1+1, Gradle 9.1.0, Python 3.11.17 и 3.14.7.
Сборка Python: setuptools 84.2.0, wheel из sdist; SOURCE_DATE_EPOCH=1792886400.
Пакет не имеет runtime-зависимостей. Подсказки установленного wheel проверены
в VS Code 1.142.0, Python extension 2026.10.0, Pylance 2026.4.1.
Paper/API и Java-зависимости закреплены прежними lock/verification-файлами,
указанными ниже. Версия плагина и Python-пакета — 0.2.0, протокол — 2.0.

[Контрольные суммы поставки](../dist/v0.2/SHA256SUMS.txt),
[состав и происхождение](../dist/v0.2/RELEASE.json),
[результаты I05](reports/I05.ru.md).
Совместимость с пользовательским Paper build 99 и работа по LAN в I05
не проверялись. Ниже сохранена история предыдущих этапов.

Историческая среда T02–T10
-------------------------

Дата последней проверки: 22 октября 2026 года. Платформа стенда: Windows x64.
Точные версии ниже — проверенная среда этих этапов; совместимость с другими
сборками Paper и JDK пока не заявляется.

| Компонент | Зафиксированное значение |
|---|---|
| Minecraft / Paper | 26.2, build 133, канал STABLE |
| Paper API, compileOnly | io.papermc.paper:paper-api:26.2.build.133-stable |
| Java | Eclipse Temurin JDK 25.0.4.1+1 LTS, Windows x64 HotSpot |
| Gradle / Wrapper | 9.1.0 |
| Java release / toolchain | 25 / 25 |
| JUnit BOM / Jupiter | 5.11.4 |
| JSON parser, T03 | com.fasterxml.jackson.core:jackson-core:2.22.4 |
| Упаковка зависимостей, T03 | com.gradleup.shadow 9.3.0 |
| Плагин | Minebridge 0.1.0-dev, api-version 26.2, POSTWORLD |

Серверная сборка выбрана из исходного кандидата плана: она доступна и фактически
загружена. Переход на другой build не требовался. Метаданные издателя:
[Paper 26.2 build 133](https://fill.papermc.io/v3/projects/paper/versions/26.2/builds/133).
Дата сборки в серверном журнале — 2026-10-09T17:19:44Z, commit 58e6e45.

Загружаемые артефакты и SHA-256
-----------------------------

Значения URL и контрольных сумм также находятся в
[bootstrap_t02.py](../tools/bootstrap_t02.py). Загрузка завершается ошибкой при
несовпадении SHA-256; JDK и Gradle распаковываются только в .tools.

| Артефакт | SHA-256 |
|---|---|
| [Temurin OpenJDK25U-jdk_x64_windows_hotspot_25.0.4.1_1.zip](https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_windows_hotspot_25.0.4.1_1.zip) | 00c847d804f4a78e9f04f2683faf14fed898535b177b7fc704486cb0284e9283 |
| [gradle-9.1.0-bin.zip](https://services.gradle.org/distributions/gradle-9.1.0-bin.zip) | a17ddd85a26b6a7f5ddb71ff8b05fc5104c0202c6e64782429790c933686c806 |
| [paper-26.2-133.jar](https://fill-data.papermc.io/v1/objects/bf1dcf627364f8a631ab15250d240eb5a8e89faaac523b391e1c61367fce9ff1/paper-26.2-133.jar) | bf1dcf627364f8a631ab15250d240eb5a8e89faaac523b391e1c61367fce9ff1 |

Контрольные суммы трёх загрузок сверены с опубликованными метаданными
поставщиков и проверены на скачанных файлах. Wrapper создавался проверенным
Gradle 9.1.0. SHA-256 файла plugin/gradle/wrapper/gradle-wrapper.jar:
76805e32c009c0cf0dd5d206bddc9fb22ea42e84db904b764f3047de095493f3.

Зависимости и воспроизводимость
-----------------------------

Репозитории: Maven Central и
[официальный Paper Maven](https://repo.papermc.io/repository/maven-public/).
Версия API задана полностью, диапазоны и динамические версии не используются.

- [gradle.lockfile](../plugin/gradle.lockfile) фиксирует разрешённые версии,
  включая транзитивные зависимости.
- [buildscript-gradle.lockfile](../plugin/buildscript-gradle.lockfile) фиксирует
  Shadow и его транзитивные зависимости отдельно от runtime/compile classpath.
- [verification-metadata.xml](../plugin/gradle/verification-metadata.xml)
  фиксирует SHA-256 разрешённых артефактов. Это локально зафиксированные суммы
  первой загрузки, а не независимая проверка подписи издателя.
- SHA-256 фактически использованного Paper API JAR:
  e8079e853374d75e571a24379573e96f6dfe1581b97bae5465163c77f00f327a.
- Paper API имеет compileOnly scope и не включается в JAR плагина.
  На T02 runtime-зависимостей не было; в T03 добавлен изолированный Jackson.
- Архивы не содержат временных меток файлов, порядок записей воспроизводим.
  В T02 две последовательные clean-сборки дали одинаковый JAR; повторная
  сборка после правки build script сохранила ту же сумму.
- SHA-256 исторического JAR T02, сохранённого в dist/t02/minebridge-paper-0.1.0-dev.jar:
  421f92a5cf78b6a1be1b443d8e8c0afd235ea22c85e3ccb4c3f0633f2c1ca9ff.

JSON и упаковка T03
-------------------

[Jackson core 2.22.4](https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-core/2.22.4/)
выбран из доступных точных релизов Maven Central. Используется streaming API
без databind и без обращения к JSON-библиотекам сервера. SHA-256 скачанного JAR:
2d30c375cddea9657a1e1ef97547a2694b663b355facb4de53a097782b312d1a.
Это локально проверенная сумма, также включённая в verification metadata.

[Shadow 9.3.0](https://plugins.gradle.org/plugin/com.gradleup.shadow/9.3.0)
переносит com.fasterxml.jackson.core в dev.minebridge.internal.jackson.core.
Он совместим с выбранным Gradle 9.1.0 по
[матрице проекта](https://gradleup.com/shadow/) и фактически проверен сборкой.
Проверены отсутствие исходного пакета Jackson/Paper API в JAR и запуск codec
с classpath только из production JAR и простого тестового main.

Исторический путь сборки T03: plugin/build/libs/minebridge-paper-0.1.0-dev.jar;
сохранённый артефакт T03: dist/t03/minebridge-paper-0.1.0-dev.jar. SHA-256:
bd85a1fb187db1b86f30dfc6812726c08252715abf94b7d329e89626f246546f.
Повторная принудительная shadow-сборка дала тот же файл. Артефакт с суффиксом
-plain предназначен для сборочных проверок; серверу нужен основной JAR
с упакованной библиотекой. Проверки и SHA Python-артефактов — в
[отчёте T03](reports/T03.ru.md).

Это проверка воспроизводимости на данном стенде. Сборка на другой ОС и побитовое
совпадение JAR между разными компьютерами отдельно не проверялись. Первый
запуск Paper загружает собственные библиотеки; офлайн-установка сервера с нуля
не заявляется.

Транспорт T04
-------------

Новых зависимостей не добавлено: Java использует JDK25 NIO, Python — стандартную
библиотеку. Версии Paper/API/JDK/Gradle/Shadow/Jackson выше сохранены, lock-файлы
и verification metadata не обновлялись.

JAR T04: plugin/build/libs/minebridge-paper-0.1.0-dev.jar; сохранённая копия —
dist/t04/minebridge-paper-0.1.0-dev.jar. SHA-256:
a14ab83c6959ea2ab19ee5dd4029204e6888c0454b0fcf765fa025a03cf1f651.
Принудительная повторная shadow-сборка дала ту же сумму. Test harness отсутствует
в production JAR. Python-артефакты и результаты — в [отчёте T04](reports/T04.ru.md).

listenAddress принимает числовой IP через
[InetAddress.ofLiteral, JDK25](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/net/InetAddress.html#ofLiteral(java.lang.String)).
Один reactor использует [NIO Selector](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/nio/channels/Selector.html).
Фактически проверена Windows x64 и loopback IPv4; LAN и другие ОС не проверялись.
В клиенте hostname разрешается до TCP-deadline; это ограничение описано
в [контракте](contracts/V0_1_CONTRACT.ru.md).

Portable-инструменты, Gradle cache и тестовый мир находятся в .tools и .work,
исключённых из Git. Системный PATH и установленная системная Java не менялись.
Команды: [DEVELOPMENT.ru.md](DEVELOPMENT.ru.md). Python/IDE-среда T01 и результаты
её проверок: [отчёт T01](reports/T01.ru.md).

Handshake T05
-------------

Paper 26.2 build 133, API 26.2.build.133-stable, JDK25, Gradle9.1.0,
Shadow9.3.0 и Jackson2.22.4 сохранены без новых зависимостей. Lock-файлы и
verification metadata не изменялись. Python по-прежнему использует стандартную
библиотеку; версии runtime 3.11.17 и 3.14.7.

Архив production JAR — dist/t05/minebridge-paper-0.1.0-dev.jar; SHA-256:
717c1e30a31d323a01167aeed9b8e5b06bc51904e52878d772cd982c6c4364d7.
Повторная принудительная shadow-сборка дала ту же сумму. Отдельный read-only
world metadata probe собран только для тестов; в production JAR его нет.
SHA fixture/wheel/sdist и результаты — в [отчёте T05](reports/T05.ru.md).

Фактически проверены успешный hello и два одновременных Python-процесса на
настоящем Paper, выбор настроенного мира, ошибки авторизации/состояний и stop.
Это промежуточный этап: blocks.set реализуется в T06; Minecraft.create — в T07.

Серверная запись T06
-------------------

Платформа и все версии зависимостей T05 сохранены. Добавлены BlockService,
Paper-адаптер и ограниченная локальная диагностика без новых библиотек.
Сигнатуры и поведение адаптера проверены по зафиксированным API/server JAR.

Архив production JAR — dist/t06/minebridge-paper-0.1.0-dev.jar; SHA-256:
b4c5b390ef4196ec4f979b387f4ba374254b6fa0fa70b10c51e74136fb84e87a.
Принудительная shadow-сборка повторила эту сумму. Console-only BlockSmokeProbe
собирается отдельной задачей и не включён в production JAR.

Raw blocks.set и независимое чтение блоков проверены на настоящем Paper,
включая два TCP-соединения, точные границы и loaded-only. 369 JUnit cases и
по 106 тестов установленного wheel на CPython 3.11.17/3.14.7 прошли.
SHA fixture/wheel/sdist и ограничения проверки — в [отчёте T06](reports/T06.ru.md).
Python runtime-код не менялся; в пересобранном пакете обновлён README.

Публичный Python-фасад T07
-------------------------

Добавлены Minecraft/Blocks и пример без новых runtime-зависимостей.
Минимум Python 3.11, проверки установленного wheel — CPython3.11.17/3.14.7.
JDK/Paper/API/Gradle/Shadow/Jackson и lock-файлы сохранены. Чистая сборка
production JAR дала тот же SHA-256, что T06:
b4c5b390ef4196ec4f979b387f4ba374254b6fa0fa70b10c51e74136fb84e87a.
Архив — dist/t07/minebridge-paper-0.1.0-dev.jar; fixture также не менялась.
SHA wheel/sdist и проверки — в [отчёте T07](reports/T07.ru.md).

IDE-проверка: фактически запущены VS Code1.142.0, Python extension2026.10.0
и Pylance2026.4.1 из существующей установки. Проверялись completion/signature/
definition установленного wheel и отсутствие сетевых вызовов при импорте.
Новая IDE или расширения не устанавливались. Два независимых Python-процесса
с публичным API проверены на Paper; полный observer/gate остаётся T08–T10.

Независимый observer и test-control T08
--------------------------------------

Версии Paper/API/JDK/Gradle/Shadow/Jackson/JUnit сохранены. Новых runtime-
зависимостей bridge/Python нет; Python-код и типы совпадают с T07, обновлено
описание пакета. Установленный wheel проверен на CPython 3.11.17/3.14.7.

Отдельный Gradle subproject :observer использует JDK25, точный прежний Paper API
и compileOnly(project(":")); JSON-снимки сериализуются кодом fixture на JDK.
Его разрешённый compile classpath закреплён в
[observer gradle.lockfile](../integration/observer-plugin/gradle.lockfile).
Новая отдельная фиксация classpath выполнена осознанно; существующие версии
и verification metadata не расширялись новыми библиотеками.

Архив production JAR — dist/t08/minebridge-paper-0.1.0-dev.jar; SHA-256:
dca68d2326b7e252f3fb38f33b1609321968d595dfbe0f4bc8b8b5e07fca09e8.
Он содержит локальный default-off TestControl и ограниченную диагностику;
observer-классов, Paper API и тестового transport harness в нём нет.

Отдельный тестовый JAR — dist/t08/minebridge-observer-0.1.0-dev.jar; SHA-256:
407d0065c696567a4383691236905d4ad547270ce6852f1f5d4e3b270017f914.
Принудительная повторная сборка обоих JAR повторила эти суммы на данном стенде.
Один production SHA проверен на Paper с test-control и без него, два чистых
запуска harness прошли по 4+1 теста. 381 JUnit cases и по 122 Python-теста прошли.
Полная матрица T09–T10 ещё не выполнена. SHA wheel/sdist, evidence и ограничения —
в [отчёте T08](reports/T08.ru.md).

Полная матрица V/D T09
---------------------

Версии среды, Python-пакет, production JAR и observer JAR сохранены без изменений.
Четыре архива dist/t09 скопированы из dist/t08 с теми же SHA-256; это приёмка
существующих артефактов, а не новая версия Python/Java runtime. Lock-файлы и
verification metadata T09 не обновляет. Новые тесты/harness используют только
стандартную библиотеку; пассивный relay проверен локально на Python 3.11/3.14,
реальные Paper-клиенты работают через установленный wheel на CPython 3.14.7 с -I.

В каждом из двух свежих миров выполнены 12 тестов: самопроверка observer и
V01–V07/D01–D04. Manifest фиксирует hash каждого тестового исходника, SHA четырёх
входных артефактов Paper/production/observer/wheel и порты, включая ephemeral
порт capture. Одинаковые seed и артефакты не означают одинаковый UUID мира:
он считывается из Paper и должен отличаться между прогонами.
Команды, результаты и ограничения — в [отчёте T09](reports/T09.ru.md).
N/F сценарии, другие ОС и LAN остаются будущей проверкой.

Негативная матрица и поставка T10
--------------------------------

Paper/API/JDK/Gradle/Shadow/Jackson/JUnit сохранены; новых runtime-библиотек и
изменений lock-файлов T10 не требует. Java добавляет локальные diagnostics и
default-off writer control для наблюдения существующих лимитов. Observer
собирается отдельным JAR. Python runtime-код и типы совпадают с T09; пакет
пересобран с нейтральным описанием прототипа в README.

387 JUnit cases и shaded codec probe прошли на JDK25. Установленный wheel
проверен в новых .venv-t10-311/.venv-t10-314: CPython3.11.17/3.14.7, по 122 теста.
Повторная принудительная сборка обоих JAR сохранила SHA на этом стенде.

| Архив dist/t10 | SHA-256 |
|---|---|
| minebridge-0.1.0.dev0-py3-none-any.whl | e267553a8eb7c4f45bfdd08c958181992ebedbaaa05abc9787ef6430542a4ee1 |
| minebridge-0.1.0.dev0.tar.gz | 38eb3a0069dee7980461bf2c7b0bd8e6538ff56dd0d44a55abb292ab20ec5fd3 |
| minebridge-paper-0.1.0-dev.jar | 4c2038a031977dd7853e1b82fb981d148bee107766ad12438154b39a5126f492 |
| minebridge-observer-0.1.0-dev.jar, только стенд | f04c4dda3fe6b6cbacb1a4263183efc36ce3ecefceac30ef350a0931a1d7515b |

IDE: VS Code1.142.0, Python extension2026.10.0, Pylance2026.4.1 и fresh venv
с установленным wheel. Проверка реально выполнена extension host. Для неё
использован официальный portable архив той же версии/commit: глобальный
установленный редактор был занят обновлением. SHA-256 архива
ace1da7d1432d43c1ab4b2bbf643f6494f6d25dec07494976755eac522cd50d9
сверен с [метаданными Microsoft](https://update.code.visualstudio.com/api/versions/1.142.0/win32-x64-archive/stable).
Копия metadata и проверка находятся в .tools/vscode-t10. Системная установка,
пользовательский профиль и updater не менялись. PyCharm исключён из требований
пользователем 22 октября; установка PyCharm не выполнялась.

Фактический результат V/D/N/F, повтор основного пути и режим без test-control
фиксирует [отчёт T10](reports/T10.ru.md). Другие ОС, LAN и готовность целого
класса по нагрузке этим стендом не подтверждаются.

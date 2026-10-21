Зафиксированная среда T02–T09
============================

Дата последней проверки: 21 октября 2026 года. Платформа стенда: Windows x64.
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

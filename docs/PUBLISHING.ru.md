# Публикация Minebridge в GitHub и PyPI

Исходники и пакет подготовлены для выпуска **0.3.1**, лицензия — MIT.
Этот документ описывает действия владельца проекта после локальной приёмки.
Подготовка не создаёт репозиторий, commit/tag, GitHub Release или проект PyPI.

## 1. Собрать и проверить

Из корня репозитория, Python 3.11+ и JDK 25:

```shell
python -m pip install build twine
python tools/build_release.py --source-date-epoch 1793232000
python tools/check_release.py --wheel dist/v0.3.1/minebridge-0.3.1-py3-none-any.whl --sdist dist/v0.3.1/minebridge-0.3.1.tar.gz --jar dist/v0.3.1/minebridge-paper-0.3.1.jar
```

Скрипт использует `JAVA_HOME`, локально закреплённые `.tools` или Java из PATH.
Gradle wrapper проверяет Java-тесты и создаёт shaded JAR. Python wheel строится
из sdist; MIT, сведения пакета и README проверяются через `twine check --strict`.
Подробные параметры: `python tools/build_release.py --help`.

Результат — `dist/v0.3.1/` с JAR, wheel, sdist, SHA256SUMS и BUILD.json.
BUILD.json описывает сборку, а не заменяет тесты установленного wheel или Paper.
Итоговые результаты текущего выпуска фиксируются в RELEASE.json и отчёте выпуска.
Уже выпущенные версии не перезаписывают: для изменения публикуемых байтов
нужен новый номер версии. Версия должна совпадать в `python/pyproject.toml`,
`python/src/minebridge/__init__.py` и `plugin/build.gradle.kts`.

Для разработки и установленных тестов см. [CONTRIBUTING](../CONTRIBUTING.md).
Генерация серверного мира и EULA нужны только отдельному интеграционному стенду,
не сборке или импорту Python. Бинарные Minecraft/Paper серверы в выпуск не входят.

## 2. Разместить исходники

Настроенный origin: `https://github.com/ilyak163rus/minebridge.git`.
Публичный URL на дату подготовки возвращал 404: репозиторий может быть приватным
или ещё не созданным. Перед push проверьте доступ своей учётной записью.
Если используете другой owner/repository, исправьте origin и URLs в pyproject,
README, plugin.yml и workflow публикации.

Просмотрите `git status` и подготовленные изменения. Исходники, схемы,
каталоги, тесты, документы, LICENSE и `.github` должны попасть в commit;
`.tools`, `.work`, `.venv*`, `build`, `dist`, локальные серверы и журналы
исключены из Git. Не используйте `git archive HEAD` для незакоммиченных изменений:
он упакует только прежнее содержимое HEAD.

После проверки создайте commit и отправьте его в свой репозиторий обычным
порядком. Готовые workflows:

- `ci.yml`: проверка установленного Python-пакета на Windows/Ubuntu,
  Python 3.11/3.14; Java 25, тесты и JAR.
- `publish.yml`: **только ручная** публикация TestPyPI/PyPI.

Локальная проверка YAML/actionlint не означает, что облачный CI уже прошёл.
Нативные тесты Paper остаются отдельной проверкой; GitHub CI не проверяет
работу с учениками по LAN.

## 3. GitHub Release

Для commit принятого выпуска создайте и отправьте тег `v0.3.1`. Он должен
указывать на тот же код, из которого проверены артефакты. Пример прикрепления
готовых файлов через GitHub CLI:

```powershell
gh release create v0.3.1 `
    dist/v0.3.1/minebridge-paper-0.3.1.jar `
    dist/v0.3.1/minebridge-0.3.1-py3-none-any.whl `
    dist/v0.3.1/minebridge-0.3.1.tar.gz `
    dist/v0.3.1/SHA256SUMS.txt `
    dist/v0.3.1/BUILD.json `
    dist/v0.3.1/RELEASE.json `
    --title "Minebridge 0.3.1" --notes-file docs/releases/0.3.1.ru.md
```

Папка dist не хранится в Git; JAR и Python-пакеты распространяются как
Release assets. Кнопка исходников GitHub собирает отправленный commit,
включая monorepo с `python/` и `plugin/`.

## 4. Сначала TestPyPI

Дистрибутив называется `minebridge`, импорт — `minebridge`. Запрос публичного
PyPI JSON API на дату подготовки вернул 404; это не резервирование имени и
не гарантия, что PyPI разрешит его занять. При конфликте имени меняют
имя дистрибутива и соответствующие metadata/workflow URLs, импорты менять
не обязательно. TestPyPI и PyPI имеют отдельные учётные записи и проекты.

В настройках PyPI/TestPyPI добавьте Trusted Publisher (для первого выпуска —
pending publisher):

| Поле | TestPyPI | PyPI |
|---|---|---|
| Project | minebridge | minebridge |
| Owner | ilyak163rus | ilyak163rus |
| Repository | minebridge | minebridge |
| Workflow filename | publish.yml | publish.yml |
| Environment | testpypi | pypi |

Создайте одноимённые environments в GitHub repository settings. Workflow
использует OIDC; сохранять PyPI-токен в исходниках не требуется.
Запуск после отправки тега:

```shell
gh workflow run publish.yml --ref v0.3.1 -f index=TestPyPI
```

Он проверит тег, три версии, сборку, README и тесты установленного wheel,
затем загрузит только wheel/sdist в выбранный индекс. Для проверки установки
используйте отдельное окружение:

```shell
python -m venv .venv-testpypi
```

Windows:

```powershell
.\.venv-testpypi\Scripts\python.exe -m pip install --index-url https://test.pypi.org/simple/ --no-deps minebridge==0.3.1
```

Linux/macOS:

```shell
.venv-testpypi/bin/python -m pip install --index-url https://test.pypi.org/simple/ --no-deps minebridge==0.3.1
```

Проверьте
`minebridge.__version__`, подсказки и подключение к соответствующему плагину.

## 5. PyPI

После проверки TestPyPI вручную запустите тот же тег:

```shell
gh workflow run publish.yml --ref v0.3.1 -f index=PyPI
```

Тогда установка для учеников станет такой:

```shell
python -m pip install --upgrade minebridge
```

Публикация Python-пакета не устанавливает JAR на сервер. Для воспроизводимой
пары указывайте `minebridge==0.3.1` и плагин 0.3.1.

Основания: [PyPA packaging guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/),
[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
[GitHub Python CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/python).

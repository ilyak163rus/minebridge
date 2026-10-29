# Выпуск Minebridge: инструкция для сопровождающего

Пользователь скачивает JAR и Python-пакет из
[GitHub Releases](https://github.com/ilyak163rus/minebridge/releases).
В репозитории хранятся исходники; готовые файлы прикладываются к выпуску.
Публикация на PyPI — отдельный необязательный шаг с правами владельца проекта.

## Подготовка версии

1. Обновите один номер версии в `python/pyproject.toml`,
   `python/src/minebridge/__init__.py` и `plugin/build.gradle.kts`.
2. Обновите CHANGELOG, документацию, примеры и номера в ссылках скачивания.
3. Выполните проверки из [CONTRIBUTING](../CONTRIBUTING.md), затем проверьте
   игровые изменения на [отдельном Paper](../integration/README.md), включая
   две одновременные сессии.
4. Проверьте состав commit: исходники, тесты, схемы, лицензии и документация.
   Локальные `.tools`, `.work`, `.venv*`, серверы, журналы и `dist/` исключены.

Не перезаписывайте уже опубликованные байты под прежним номером версии.

## Сборка файлов

Из корня репозитория, с Python 3.11+ и JDK 25:

```console
python -m pip install --upgrade build twine
python tools/build_release.py --help
```

`build_release.py` собирает согласованные JAR, wheel и sdist, выполняет
Java-тесты и строгую проверку метаданных. Он использует `JAVA_HOME` или Java
из PATH; локальный закреплённый toolchain также поддерживается. Задайте
`--source-date-epoch` равным выбранной UTC-дате сборки в Unix-секундах.
Параметр `--replace` предназначен только для ещё не опубликованного кандидата.

Результат находится в `dist/v<version>/`. Для проверки файлов перед выпуском:

```console
python tools/check_release.py --help
```

Передайте этому скрипту `--wheel`, `--sdist` и `--jar`. Проверка включает
лицензии, метаданные, RECORD, данные/типизацию пакета и содержимое JAR.
Сборка сама по себе не подтверждает работу игровых сценариев на Paper.

## GitHub Release

Отправьте принятый commit в `main` и дождитесь успешного GitHub Actions.
Создайте тег `v<version>` на том же коде, из которого собраны файлы.
В GitHub откройте **Releases → Draft a new release**, выберите тег и приложите:

- `minebridge-paper-<version>.jar`;
- `minebridge-<version>-py3-none-any.whl`;
- `minebridge-<version>.tar.gz`;
- `SHA256SUMS.txt` с хешами этих трёх файлов.

Описание должно содержать требования, краткие изменения и рабочие ссылки
на установку. Не прикладывайте локальные отчёты, абсолютные пути, тестовые
observer JAR, сервер Minecraft/Paper или внутренние журналы.
При использовании GitHub CLI подготовьте описание в UTF-8-файле и передайте
его через `--notes-file`. CLI не нужен для публикации через веб-интерфейс.

После публикации скачайте файлы по публичным ссылкам без авторизации и
проверьте SHA256. Убедитесь, что README ведёт на существующий выпуск.

## Необязательная публикация на PyPI

Имя дистрибутива и Python-импорт — `minebridge`. Наличие репозитория GitHub
не резервирует имя на PyPI. Нужны отдельные учётные записи и права на проекты
в TestPyPI/PyPI. Сначала настройте Trusted Publisher (для первого выпуска —
pending publisher) в выбранном индексе:

| Поле | Значение |
|---|---|
| Project | `minebridge` |
| Owner | `ilyak163rus` |
| Repository | `minebridge` |
| Workflow filename | `publish.yml` |
| Environment | `testpypi` или `pypi` |

Создайте соответствующие GitHub environments в настройках репозитория.
Workflow использует OIDC; PyPI-токен в исходниках не требуется.

Запустите **Actions → Publish Python package manually → Run workflow** на
теге `v<version>`, сначала с индексом **TestPyPI**. Workflow проверит тег,
согласованность версий, сборку, метаданные и тесты установленного wheel, затем
передаст wheel/sdist в выбранный индекс. Push коммита или тега ничего не
публикует на PyPI.

Проверьте установку из TestPyPI в отдельном окружении:

```console
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps minebridge==<version>
```

После проверки запустите тот же workflow на том же теге с индексом **PyPI**.
Только после успешной публикации заменяйте инструкции установки с GitHub
wheel на `python -m pip install minebridge==<version>`.
JAR по-прежнему устанавливается отдельно на сервер.

Официальные инструкции: [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
[PyPA packaging guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/).

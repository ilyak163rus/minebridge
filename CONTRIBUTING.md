# Разработка Minebridge

Нужны Python 3.11+ и JDK 25. Gradle 9.1.0 запускается через wrapper в `plugin`;
Paper API и зависимости закреплены lock-файлами и SHA. Для первого запуска
потребуется сеть. Python-пакет не имеет зависимостей времени выполнения.

## Проверка Python-пакета

Из корня репозитория:

```console
python -m venv .venv-dev
```

Активируйте окружение (`.venv-dev\Scripts\Activate.ps1` в PowerShell или
`source .venv-dev/bin/activate` в bash), затем:

```console
python -m pip install --upgrade build twine
python -m build --outdir dist/python python
```

Проверьте метаданные и установите созданный `.whl`. Проверки должны импортировать
установленную библиотеку, поэтому не задавайте `PYTHONPATH=python/src`.
Следующий переносимый скрипт запускается из корня репозитория выбранным Python
(в интерактивном режиме или из временного `.py`-файла):

```python
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path.cwd()
distributions = sorted((root / "dist/python").glob("*"))
subprocess.run([sys.executable, "-m", "twine", "check", "--strict",
                *map(str, distributions)], check=True)
wheel, = (root / "dist/python").glob("*.whl")
subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps",
                "--force-reinstall", str(wheel)], check=True)
with tempfile.TemporaryDirectory() as work:
    subprocess.run([sys.executable, "-I", "-m", "unittest", "discover",
                    "-s", str(root / "python/tests"), "-q"], cwd=work, check=True)
```

## Проверка плагина

Linux/macOS, из корня:

```console
bash plugin/gradlew -p plugin test shadowJar --no-daemon --console=plain
```

PowerShell:

```powershell
.\plugin\gradlew.bat -p plugin test shadowJar --no-daemon --console=plain
```

Итоговый серверный JAR: `plugin/build/libs/minebridge-paper-<version>.jar`.
JAR с суффиксом `-plain` не предназначен для установки на Paper.

## Изменения и серверная приёмка

Сохраняйте совместимость публичного API и точный порядок аргументов.
Изменения wire-формата сопровождайте контрактом, corpus и проверками обеих
сторон. Для исправлений добавляйте проверку наблюдаемого поведения, а не
проверку значения новой константы. Не добавляйте тестовые плагины в основной JAR.

Серверные операции выполняются в разрешённом потоке Paper. Ответ об успехе
должен следовать за фактическим выполнением; повторять мутацию автоматически
при неизвестном результате нельзя. Оптимизация заполнения не должна менять
состояния блоков, физику или порядок подтверждения команд.

Реальный Paper-стенд запускается вручную на отдельном тестовом сервере:
[описание стенда](integration/README.md), [команды](docs/DEVELOPMENT.ru.md),
[зафиксированная среда](docs/ENVIRONMENT_LOCK.ru.md). Для загрузки Minecraft
и первого запуска требуется принятие его EULA владельцем стенда. Облачный CI
не заменяет проверку игровых событий, загрузки чанков и двух одновременных сессий.

## CI и публикация

`ci.yml` собирает wheel/sdist, проверяет метаданные и установленный wheel на
Python 3.11/3.14 в Ubuntu/Windows; отдельно выполняет Java-тесты и собирает JAR
с JDK 25. Файлы сохраняются как артефакты запуска. Результат GitHub Actions
можно считать подтверждённым только после реального успешного запуска workflow.

`publish.yml` запускается **только вручную**, с выбором TestPyPI или PyPI и
ссылкой на тег `v<version>`. Версия тега, pyproject, Python runtime и плагина
должна совпадать. Сначала выполняются сборка, `twine check --strict` и тесты
установленного wheel; отдельная задача затем публикует проверенные файлы через
Trusted Publishing. Push коммита или тега сам по себе ничего не публикует.

Перед первым запуском владелец настраивает Trusted Publisher для репозитория
`ilyak163rus/minebridge`, файла `publish.yml` и окружений `testpypi`/`pypi`.
Сам workflow не создаёт аккаунты, окружения или права на имя проекта.
В настройках GitHub environment можно включить ручное одобрение публикации.
Настройка проекта и выпуск описаны в [инструкции публикации](docs/PUBLISHING.ru.md).

Использованные механизмы: [синтаксис GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[руководство PyPA по Trusted Publishing](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
Версии внешних actions закреплены SHA; обновляйте их вместе с проверкой
официальных release notes и повторным прогоном CI.

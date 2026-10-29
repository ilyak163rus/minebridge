# Быстрый старт

Minebridge состоит из плагина для сервера и Python-библиотеки. Клиент Minecraft не требует модов. Нужны **Python 3.11+**, **Paper 26.2** и **Java 25**. Проверенная сборка — Paper 26.2 build 133.

## 1. Плагин

Скачайте [minebridge-paper-0.3.1.jar](https://github.com/ilyak163rus/minebridge/releases/download/v0.3.1/minebridge-paper-0.3.1.jar). Остановите сервер, положите файл в `plugins/`, заменив прежний JAR Minebridge, и запустите сервер.

В консоли появится `TCP listener ready on port 4711`. Созданный `plugins/Minebridge/config.yml` по умолчанию содержит:

```yaml
listenAddress: '127.0.0.1'
port: 4711
authEnabled: false
token: ''
```

Такая настройка подходит для Python на том же компьютере. Имя мира не требуется: выбирается основной Overworld, даже если вы пересоздаёте мир с другим названием папки.

### Python на другом компьютере

Остановите сервер и замените `listenAddress` на IP **серверного** компьютера в локальной сети, например:

```yaml
listenAddress: '192.168.0.200'
port: 4712
authEnabled: false
token: ''
```

Перезапустите сервер и разрешите входящие соединения на выбранный TCP-порт в брандмауэре. В Python используйте тот же адрес и порт: `Minecraft.create("192.168.0.200", 4712)`.

Если RaspberryJuice уже занимает 4711, укажите Minebridge другой порт, например 4712. У плагинов разные протоколы; библиотеке нужен именно порт Minebridge, а не игровой порт Minecraft 25565.

Без авторизации любой, кто может подключиться к этому порту, получает доступ к изменениям мира. Используйте доверенную сеть. Необязательная авторизация: `authEnabled: true` и непустой `token` в конфиге, затем `Minecraft.create(ip, port, token="ваш-токен")`. TCP-соединение не шифруется.

## 2. Python-библиотека

В своём Python-окружении выполните:

```shell
python -m pip install "https://github.com/ilyak163rus/minebridge/releases/download/v0.3.1/minebridge-0.3.1-py3-none-any.whl"
```

Можно также скачать wheel из [выпуска 0.3.1](https://github.com/ilyak163rus/minebridge/releases/tag/v0.3.1) и установить локальный файл:

```shell
python -m pip install ./minebridge-0.3.1-py3-none-any.whl
```

У пакета нет зависимостей времени выполнения. Версии библиотеки и плагина должны совпадать. В PyPI пакет пока не опубликован.

Проверьте установку:

```shell
python -c "import minebridge; print(minebridge.__version__)"
```

Ожидается `0.3.1`. В VS Code выберите то же окружение через **Python: Select Interpreter**. Расширения Python и Pylance дадут подсказки для методов и каталогов `block.`, `items.`, `entity.`, `events.` и остальных — даже без подключения к серверу.

## 3. Первая программа

Сохраните как `build.py` и запустите `python build.py`. Координаты абсолютные; выберите свободное место, которое можно застроить.

```python
from minebridge import Minecraft, block

with Minecraft.create("localhost", 4711) as mc:
    mc.setBlocks(0, 80, 0, 9, 80, 9, block.COBBLESTONE)
    mc.setBlock(0, 81, 0, block.OAK_LOG.withStates(axis="x"))
    mc.flush()
    print(mc.getBlock(0, 80, 0))        # Старый числовой ID: 4
    print(mc.blocks.getBlock(0, 81, 0)) # BlockSpec: ключ и состояния
    mc.postToChat("Построено из Python!")
```

Замените адрес и порт, если сервер работает на другом компьютере. Войдите на сервер в Minecraft и посетите координаты постройки. Необходимые чанки загрузятся автоматически.

Записи блоков и чат по умолчанию буферизируются. `flush()` ждёт выполнения и показывает ошибки; чтение и методы с результатом тоже ждут предыдущие записи. Выход из `with` завершает ожидающие записи и закрывает соединение. Для ожидания каждой команды укажите `writeMode="sync"` в `create`.

## 4. Игроки и эффекты

```python
from minebridge import Minecraft, effects, items, selector

with Minecraft.create("localhost", 4711) as mc:
    player = selector.playerByName("YourNick")
    print(mc.players.giveItem(player, items.EMERALD, 3))
    mc.effects.add(player, effects.SPEED, 30, 2)  # 30 секунд, уровень 2
    mc.setPos(player, 10, 80, 10)
```

Укажите текущий онлайн-ник с точным регистром. Для всех игроков есть `selector.ALL_PLAYERS`. Для `selector.SELF` явно задайте `player="YourNick"` при создании подключения. Компьютер и IP ученика не назначают SELF.

`giveItem` добавляет предметы и возвращает остаток, если они не поместились. В отличие от него, `mc.inventories.ofPlayer(player).setItem(0, items.EMERALD, 3)` **заменяет** точный слот.

## 5. События и примеры

Рабочий обработчик чата есть в [README](../README.ru.md#награда-за-сообщение-в-чате). Подписка сама по себе не запускает обработчик: после `subscribe` нужен `mc.events.run()`. Команды внутри функции разрешены.

Смотрите [примеры программ](../examples/README.md), [базовый API](API_V0_2.ru.md) и [события, инвентари и управление миром](API_V0_3.ru.md). Полный актуальный [справочник на английском](API.md) собран на одной странице.

## Если что-то не работает

| Симптом | Что проверить |
|---|---|
| `ModuleNotFoundError` | Установите wheel тем же Python, которым запускаете программу. |
| Отказ подключения или таймаут | Сообщение готовности Minebridge, IP сервера, порт, `listenAddress` и брандмауэр. |
| Ошибка RaspberryJuice в логе | Python подключился к порту другого плагина. |
| `Cannot start TCP listener` | IP должен принадлежать серверному компьютеру, а порт должен быть свободен. |
| `MissingContextError` | Для SELF и селекторов с исходной позицией нужен `player="YourNick"`. |
| `PlayerNotFoundError` | Игрок с указанным текущим ником должен быть онлайн. |
| Награда не видна | Проверьте `given/leftovers` в результате выдачи: инвентарь может быть полон. |
| `PeacefulSpawnError` | Этот тип сущности запрещён мирной сложностью мира назначения. |
| Ошибка при `flush()` или закрытии | Так сообщаются отложенные ошибки буферизированных записей. |

Для серверного журнала действий конкретной программы укажите `logging=True` в `create`. По умолчанию журнал выключен.

Если связь оборвалась и ошибка содержит `outcome="unknown"`, команда могла выполниться. Автоматического повторения нет. Подтверждение означает выполнение на сервере, а не сохранение мира на диск.

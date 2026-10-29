# Minebridge 0.3.1

Типизированный Python API для Minecraft Java Edition на Paper: строительство,
игроки и селекторы, предметы, эффекты, сущности, настройки мира, события
с обработчиками и историей, слоты сундуков и игроков.

Нужны **Python 3.11+**, сервер **Paper 26.2 / Java 25** и плагин Minebridge
соответствующей версии. Закреплённая сборка для проверок — Paper 26.2 build 133.
У Python-пакета нет внешних runtime-зависимостей. Лицензия — MIT.

## Установка

Установка переданного wheel:

```shell
python -m pip install --upgrade minebridge-0.3.1-py3-none-any.whl
```

После публикации проекта в PyPI:

```shell
python -m pip install --upgrade minebridge
```

JAR плагина устанавливается отдельно в `plugins` сервера. Плагин и библиотеку
обновляйте вместе. Инструкция и файлы плагина находятся в
[репозитории](https://github.com/ilyak163rus/minebridge).

## Первые блоки

```python
from minebridge import Minecraft, block

with Minecraft.create("192.168.0.200", 4712) as mc:
    mc.setBlock(0, 80, 0, block.COBBLESTONE)
    mc.setBlocks(0, 81, 0, 29, 110, 29, block.STONE)  # 30 × 30 × 30
    mc.flush()
    print(mc.getBlock(0, 80, 0))  # 4
    print(mc.blocks.getBlock(0, 81, 0))  # современный BlockSpec
```

`Minecraft.create(ip, port)` сохраняет два позиционных параметра. Token и имя
мира не обязательны. Основной Overworld выбирается независимо от имени папки.
Настройте `listenAddress` и `port` в `plugins/Minebridge/config.yml`;
по умолчанию слушается `127.0.0.1:4711`. В примерах используется отдельный порт 4712.

По умолчанию `writeMode="buffered"`: записи блоков и чат отправляются без
ожидания каждого ACK. `flush`, чтение, методы с результатом, `close` и обычный
выход Python дожидаются предыдущих записей. `writeMode="sync"` ждёт каждую запись.
`logging=True` включает серверный журнал действий одного соединения.

В 0.3.1 заполнение области до 32 768 блоков при готовых чанках выполняется
за один серверный проход. Большие области обрабатываются порциями. Время
генерации чанков и физика блоков остаются частью работы сервера.

## Игрок по нику

```python
from minebridge import Minecraft, selector, items, effects

with Minecraft.create("192.168.0.200", 4712) as mc:
    player = selector.playerByName("YourNick")
    print(mc.players.giveItem(player, items.EMERALD, 3))
    mc.effects.add(player, effects.SPEED, 100, 200)  # секунды, затем уровень
    mc.setPos(player, 10, 80, 10)
```

Ник должен точно совпадать по регистру и состоять из 1–16 ASCII-букв, цифр
или `_`. Селектор ищет онлайн-игрока при выполнении каждой команды.
`selector.SELF` требует явного `player="CurrentNick"` в create/withContext;
компьютер и IP ученика его не назначают.

## Обработчик чата

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("192.168.0.200", 4712) as mc:
    def on_chat(event: ChatEvent) -> None:
        if event.message == "!reward":
            print(mc.players.giveItem(event.player, items.EMERALD, 3))
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

Обработчики выполняются в потоке `events.run`; синхронные команды внутри них
разрешены. Python наблюдает событие и не отменяет его синхронно на сервере.
`pollEvents`, `pollChatPosts` и `getRecent` читают отдельную ограниченную
RAM-историю. Переполнение live-очереди и потеря истории сообщаются исключениями.

## Слоты и ошибки

`mc.inventories.ofPlayer(target).setItem(0, items.DIAMOND, 3)` заменяет точный
слот; `giveItem` распределяет предметы и возвращает `given/leftovers/dropped`.
При полном инвентаре по умолчанию остаток возвращается в результате выдачи.
`mc.inventories.ofBlock(x, y, z)` адресует половину сундука на 27 слотов;
`combined=True` — общий сундук на 27/54 слота. `getContents()` возвращает слоты,
`getItem(slot)` — предмет или None, `clear(slot)` очищает выбранный слот.

`minebridge.errors.PeacefulSpawnError` сообщает о попытке создать сущность,
запрещённую мирной сложностью. Такой отказ происходит до создания сущности.
ItemView предназначен для чтения; произвольные компоненты предмета не
поддерживаются для обратного копирования через setter.

Статические каталоги `block`, `items`, `entity`, `effects`, `selector`, `events`,
`slots`, `gamemode`, `weather`, `gamerule`, `damageCause` и аннотации доступны
в VS Code/Pylance без подключения к серверу.

- [Установка и запуск](https://github.com/ilyak163rus/minebridge/blob/main/docs/QUICKSTART.ru.md)
- [API](https://github.com/ilyak163rus/minebridge/blob/main/docs/API_V0_3.ru.md)
- [Документация](https://github.com/ilyak163rus/minebridge/tree/main/docs)
- [Примеры](https://github.com/ilyak163rus/minebridge/tree/main/examples)
- [Изменения](https://github.com/ilyak163rus/minebridge/blob/main/CHANGELOG.md)

Minebridge — независимый проект, не официальный продукт Mojang или Microsoft.

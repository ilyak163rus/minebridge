Minebridge — блоки, игроки, предметы и сущности
=============================================

Это справочник базовых возможностей текущей версии 0.3.1. Установка описана
в [быстром запуске](QUICKSTART.ru.md); полный пример —
[`examples/blocks_and_rewards.py`](../examples/blocks_and_rewards.py).
Закреплённая версия каталогов и серверных проверок — Paper 26.2 build 133.

Подключение и завершение
-----------------------

```python
from minebridge.minecraft import Minecraft
from minebridge import block, items, effects, entity, selector
from minebridge.models import ItemStack

mc = Minecraft.create("192.168.0.200", 4711)
try:
    mc.setBlock(0, 80, 0, block.COBBLESTONE)
    mc.flush()
finally:
    mc.close()
```

Также доступен `from minebridge import Minecraft`. Базовому подключению
достаточно двух параметров; токен и имя мира по умолчанию не нужны.

```text
Minecraft.create(
    ip="localhost", port=4711, *,
    writeMode="buffered", token=None, world=None,
    timeout=5.0, coordinates=None, player=None, logging=False,
)
```

Звёздочка в сигнатуре означает: следующие параметры передаются по имени.

| Параметр | Назначение |
|---|---|
| `ip`, `port` | Адрес и TCP-порт плагина Minebridge |
| `writeMode` | `"buffered"` по умолчанию или `"sync"` |
| `world` | `None` выбирает основной Overworld; строка выбирает загруженный мир по имени или ключу |
| `player` | Текущий ник онлайн-игрока для SELF и пространственных селекторов; по умолчанию привязки нет |
| `token` | Необязательная авторизация; `None` также учитывает `MINEBRIDGE_TOKEN`, если он задан |
| `timeout` | Положительный конечный таймаут отдельных сетевых стадий, по умолчанию 5 секунд |
| `coordinates` | `None` или `"absolute"`; относительные координаты не поддерживаются |
| `logging` | Только `bool`, по умолчанию `False`; `True` включает серверный журнал действий этой сессии (JAR/wheel 0.2.1+) |

`create` возвращает подключённый `Minecraft` после успешного согласования с
плагином. При `player=...` игрок ищется сразу; неуспешная привязка закрывает
новое соединение.

| Метод | Результат |
|---|---|
| `mc.flush()` | `None`; ждёт все предыдущие записи и сообщает их ошибки |
| `mc.close()` | `None`; ждёт записи, закрывает соединение даже при ошибке; повторное закрытие безопасно |
| `mc.withContext(player=...)` | Новый `Minecraft` с отдельной привязкой игрока поверх того же соединения |

В buffered-режиме `setBlock`, `setBlocks` и `postToChat` не ждут каждый ответ.
Окно отправки ограничено; при его заполнении очередная запись ждёт свободного
места. Чтение, получение игроков, телепортация, выдача, эффекты и создание
сущностей ждут результата и предыдущих записей. В sync-режиме каждая запись
тоже ждёт своего результата.

При обычном завершении Python оставшиеся записи также ожидаются автоматически.
Это исправляет короткие скрипты без явного `close()`. Ошибка при таком ожидании
выводится в stderr; обработчик выхода не меняет код завершения процесса.
Для получения исключения в своей программе используйте `flush()`/`close()`.
Аварийное/принудительное завершение не гарантирует выполнения команд.

При `logging=True` консоль сервера и `logs/latest.log` получают строки `ACTION`
с session/request ID, методом, параметрами и фазой received/completed/error.
Параметр относится ко всему соединению, включая фасады `withContext`.
`completed` отражает выполнение, `ackQueued` — постановку ответа в очередь,
а не подтверждение получения Python. Длинные значения и коллекции сокращаются;
при переполнении буфера есть строка с числом пропущенных записей. Токен не пишется.

Блоки: запись и чтение
---------------------

| Метод | Возвращает |
|---|---|
| `mc.setBlock(x, y, z, block, data=0)` | `None` |
| `mc.setBlocks(x1, y1, z1, x2, y2, z2, block, data=0)` | `None` |
| `mc.getBlock(x, y, z)` | Старый числовой ID: `int` |
| `mc.getBlocks(x1, y1, z1, x2, y2, z2)` | `dict[tuple[int, int, int], int]` |
| `mc.blocks.setBlock(...)`, `mc.blocks.setBlocks(...)` | Та же запись с теми же аргументами |
| `mc.blocks.getBlock(x, y, z)` | Современный `BlockSpec` с `.key` и `.states` |
| `mc.blocks.getBlocks(x1, y1, z1, x2, y2, z2)` | `dict[tuple[int, int, int], BlockSpec]` |

Обе границы области включены, углы разрешается переставлять. Координаты
принимают `int` или конечный `float`; дробная координата блока округляется
вниз: `-0.2` становится `-1`. Сервер проверяет высоту мира и WorldBorder.
Лимиты: запись области до 1 000 000 позиций, чтение до 262 144 позиций.

```python
mc.setBlock(0, 80, 0, 4)
mc.setBlocks(0, 80, 0, 5, 80, 5, block.COBBLESTONE)
mc.setBlock(0, 81, 0, block.OAK_LOG.withStates(axis="x"))
mc.setBlock(1, 81, 0, block.OAK_STAIRS.withStates(facing="east", half="bottom"))
mc.setBlock(2, 81, 0, "minecraft:oak_stairs[facing=west,half=top]")

old_ids = mc.getBlocks(0, 80, 0, 1, 80, 1)
for coordinates, block_id in old_ids.items():
    print(coordinates, block_id)

stairs = mc.blocks.getBlock(1, 81, 0)
print(stairs.key)       # minecraft:oak_stairs
print(stairs.states)    # Все фактические свойства блока.
```

Параметр блока принимает старый ID с `data`, константу `block`, `LegacyBlock`,
`BlockSpec` или строку `namespace:path` со свойствами. Названия и допустимые
значения свойств проверяет Paper. `withStates` создаёт новое описание,
не изменяя исходную константу. Прямое создание описаний:

```python
from minebridge.models import BlockSpec, LegacyBlock

stone = LegacyBlock(1)
log = BlockSpec("minecraft:oak_log", {"axis": "z"})
```

Каталог содержит все 1196 блоков закреплённой сборки и совместимые старые
имена. Для старого числового API проверена 361 пара ID/data для 110 ID.
Это не весь исторический каталог mcpi. Старое чтение требует однозначного
соответствия: новые типы и неоднозначные старые псевдонимы дают
`UnsupportedLegacyBlockError`. Например, современные вода и лава не позволяют
однозначно выбрать между старыми парными ID. Для таких случаев читайте
`mc.blocks.getBlock/getBlocks`.

Исторические имена `PUMPKIN`, `STONE_SLAB`, `TORCH` сохраняют старое значение.
Современные одноимённые ключи доступны как `MINECRAFT_PUMPKIN`,
`MINECRAFT_STONE_SLAB`, `MINECRAFT_TORCH` или полные строки `minecraft:...`.

Чанки для операций автоматически загружаются и при необходимости генерируются.
Большая стройка выполняется частями. Пересекающиеся изменения двух операций
Minebridge могут дать `RegionBusyError`. Чтение области не является единым
снимком при одновременных изменениях другими участниками. Ошибка или разрыв
связи не откатывает уже выполненную часть стройки. Установка вызывает обычную
физику блоков; составные конструкции автоматически не достраиваются.

Игроки, позиции и телепортация
-----------------------------

| Метод | Возвращает |
|---|---|
| `mc.getPlayerEntityId(name)` | Временный числовой ID онлайн-игрока |
| `mc.players.get(target)` | `PlayerRef(uuid, entityId, name)` |
| `mc.players.list(targets=selector.ALL_PLAYERS)` | `list[PlayerRef]` |
| `mc.players.getPos(target)` | `Location(world, x, y, z, yaw, pitch)` для ровно одного игрока |
| `mc.players.teleport(targets, x, y, z, *, world=None)` | `TargetResult` |

`players.get` принимает имя, UUID-строку, объект `uuid.UUID` или `PlayerRef`.
`getPlayerEntityId` принимает текущий ник. `entityId` может измениться после
повторного входа, UUID используется для сохранённых ссылок.

```python
player = mc.players.get("CurrentNick")
print(player.name, player.uuid, player.entityId)
print(mc.players.list())
position = mc.players.getPos(player)
result = mc.players.teleport(player, position.x + 2, position.y, position.z,
                             world=position.world)
print(result.matched, result.applied, result.targets)
```

Телепортация сохраняет дробные координаты и текущую ориентацию игрока.
`world=None` означает мир соединения; явный `world` — загруженный мир по
имени/ключу. Чанк назначения автоматически загружается. Другие подключения
продолжают работу во время ожидания.

Селекторы и SELF
----------------

| Константа | Vanilla-селектор | Выбор |
|---|---|---|
| `selector.ALL_PLAYERS` | `@a` | Все онлайн-игроки |
| `selector.RANDOM_PLAYER` | `@r` | Случайный игрок |
| `selector.NEAREST_PLAYER` | `@p` | Ближайший игрок к исполнителю |
| `selector.SELF` | `@s` | Явно связанный исполнитель |
| `selector.ALL_ENTITIES` | `@e` | Сущности по правилам vanilla-селектора |

Цели методов `list`, `getPos`, `teleport`, `giveItem`, `effects.add` принимают
имя, UUID, ссылку `EntityRef`/`PlayerRef`, константу `Selector`, строку
vanilla-селектора или список ссылок на сущности. Явный список может содержать
до 1024 ссылок; дубликаты UUID не означают повторное действие. Синтаксис
фильтров разбирает сам Paper. Для операций игроков весь набор должен состоять
из игроков, для эффектов — из живых сущностей. Неподходящий участник делает
весь набор ошибочным до первого изменения.

```python
mc = Minecraft.create("192.168.0.200", 4711, player="CurrentNick")
try:
    print(mc.players.getPos(selector.SELF))
    nearby = mc.players.list("@a[distance=..10]")
    print(nearby)
    mc.players.giveItem(selector.RANDOM_PLAYER, items.DIAMOND, 2)
finally:
    mc.close()
```

`player` задаётся заново по текущему нику, когда это нужно для занятия.
Привязка хранит UUID, не определяется компьютером или IP. Поиск ID сам не
назначает SELF. Без привязки SELF даёт `MissingContextError`.
Простой SELF продолжает ссылаться на игрока при его переходе в другой мир.
Ближайший выбор и пространственные фильтры используют текущую позицию
связанного игрока в мире соединения; переход в другой мир для такого запроса
даёт `ContextWorldMismatchError`. Мир соединения автоматически не меняется.
Выход связанного игрока даёт `PlayerNotFoundError`, если операция требует его.

```python
other = mc.withContext(player="OtherNick")  # Также принимает UUID или PlayerRef.
unbound = mc.withContext()                 # Новый фасад без SELF.
```

Исходный `mc` не меняется. Все фасады используют одно соединение, общий порядок
записей и барьеры. Закрытие любого закрывает соединение для всех. Это контекст
исполнения; при выключенной авторизации он не удостоверяет личность ученика.

Пустой корректный групповой выбор возвращает `[]` или результат с
`matched=0`. Конкретный отсутствующий игрок даёт `PlayerNotFoundError`.
`getPos` требует ровно одну цель, иначе возникает `InvalidTargetError`.

Чат
---

```python
mc.postToChat("Привет из Python!")
mc.flush()
```

`postToChat(message) -> None` рассылает текст всем онлайн-игрокам и в консоль.
Длина — 1..4096 символов. Текст буквальный: `<red>` или `@a` внутри сообщения
не становятся разметкой или селектором. В buffered-режиме отправка ожидается
через барьер, в sync — сразу. Подтверждается серверная отправка сообщения.

Предметы
--------

```text
mc.players.giveItem(targets, item, amount=None, *, overflow="return")
```

Метод всегда ждёт `InventoryResult`. Предмет — константа `items`, строка
`namespace:path` или `ItemStack`. Количество на получателя — 1..2304.
Для ключа/строки по умолчанию 1; для ItemStack — его `.amount`.
Явный аргумент `amount` заменяет количество описания. Выдача и эффекты
поддерживают до 1024 выбранных целей; слишком объёмный ответ также может
дать `LimitExceededError` до начала изменений.

```python
prize = ItemStack(items.IRON_SWORD, name="Меч строителя", lore=["Награда из Python"])
result = mc.players.giveItem(selector.SELF, prize)
mc.players.giveItem(selector.ALL_PLAYERS, items.COBBLESTONE, 64)
mc.players.giveItem("CurrentNick", items.EMERALD, 3, overflow="drop")

for outcome in result.targets:
    print(outcome.uuid, outcome.given, outcome.leftovers, outcome.dropped)
```

`ItemStack(material, amount=1, name=None, lore=None)` неизменяем.
Имя — до 256 символов; lore — до 16 строк по 256 символов. Это буквальный
текст. Зачарования, произвольные компоненты и NBT в 0.2 не входят.
Количество автоматически делится на допустимые стеки предмета.

`InventoryResult` содержит `matched`, `applied`, `targets`.
Каждый `InventoryOutcome` содержит `uuid`, `applied`, `code`, `requested`,
`given`, `leftovers` (tuple ItemStack), `dropped`. Для каждой цели:

```python
outcome.requested == outcome.given + sum(item.amount for item in outcome.leftovers) + outcome.dropped
```

`applied=True` означает обработанную выдачу; полный инвентарь тоже может дать
`applied=True` и весь запрос в остатке. Проверяйте количества.
`overflow="return"` возвращает остаток в результате. `overflow="drop"`
выбрасывает его рядом с игроком; если другой плагин отменил выбрасывание,
невыброшенное остаётся в `leftovers`. AIR есть в каталоге, но выдать его нельзя.

Эффекты
-------

```text
mc.effects.add(targets, effect, *, duration, level=1, particles=True)
```

Возвращает `TargetResult`. Эффект — константа `effects` или полный ключ.
Цели должны быть живыми сущностями: игроками, мобами, их UUID/ссылками либо
подходящим селектором.

```python
mc.effects.add(selector.SELF, effects.SPEED, duration=30, level=2)
mc.effects.add("@e[type=minecraft:cow,distance=..10]", effects.GLOWING,
               duration=15, particles=False)
```

`duration` — положительные конечные игровые секунды; число тиков равно
`ceil(duration * 20)`, максимум 2 147 483 647. `level` — 1..256,
серверный усилитель `amplifier=level-1`. `particles` — `bool`.
Отказ игрового API отражается по цели, например `code="EFFECT_REJECTED"`.
Уже действующие эффекты и игровая механика могут влиять на результат.

Создание сущностей
-----------------

```text
mc.spawnEntity(x, y, z, entityType, *, world=None, item=None, block=None, face=None, owner=None)
mc.entities.spawn(entityType, x, y, z, *, world=None, item=None, block=None, face=None, owner=None)
```

Это один механизм с разным порядком аргументов. Координаты дробные,
без округления вниз. `world=None` означает мир соединения; строка выбирает
загруженный мир по имени/ключу. Чанк создания загружается автоматически.
Метод всегда ждёт ссылку `EntityRef(uuid, entityId, key=...)`; для живого типа
возвращается `LivingEntityRef`. Ссылку на живого моба можно передать эффектам.

```python
cow = mc.spawnEntity(10.5, 81, 10.5, entity.COW)
mc.effects.add(cow, effects.GLOWING, duration=15)
mc.entities.spawn(entity.ITEM, 12.5, 82, 10.5,
                   item=ItemStack(items.EMERALD, amount=3))
mc.spawnEntity(14.5, 84, 10.5, entity.FALLING_BLOCK,
               block=block.OAK_LOG.withStates(axis="x"))
mc.spawnEntity(20, 81, 10, entity.LIGHTNING_BOLT)
```

Каталог содержит 158 реальных типов: 150 обычных, 7 специальных и PLAYER.

| Тип | Необходимые параметры и особенности |
|---|---|
| 150 обычных типов | Создаются без дополнительных параметров |
| `entity.ITEM` | `item=...`; количество не больше одного допустимого стека этого предмета |
| `entity.FALLING_BLOCK` | `block=...`; AIR не допускается |
| `entity.LIGHTNING_BOLT` | Настоящая молния, может наносить урон и изменять мир |
| `entity.PAINTING` | `face="north"/"south"/"east"/"west"`, свободное место и твёрдая опора; картина 1×1 |
| `entity.ITEM_FRAME`, `entity.GLOW_ITEM_FRAME` | `face`, свободное место и твёрдая опора; допустимы также `"up"` и `"down"` |
| `entity.FISHING_BOBBER` | `owner` — имя/UUID/PlayerRef онлайн-игрока в мире назначения |
| `entity.PLAYER` | Есть в каталоге, создание даёт `UnsupportedEntityTypeError` |

Для висящих сущностей опора находится в соседнем блоке со стороны,
противоположной `face`. Например, для `face="east"` опора западнее места рамки.
Недостающие и неподходящие параметры не заменяются значениями другого типа.
Поплавок подчиняется обычным условиям удочки, расстояния и состояния владельца;
создание ссылки не обещает бессрочного существования поплавка.

Автозагрузка чанка обеспечивает создание. Дальнейшие тики AI, физики и молнии
зависят от обычной симуляции Minecraft; присутствие игрока рядом может иметь
значение. Создание не оставляет чанк постоянно активным. Сущность может быть
перемещена или удалена игровым движком сразу после создания.

Каталоги, модели и результаты
----------------------------

| Модуль | Содержание закреплённой сборки |
|---|---|
| `block` | 1196 современных типов и совместимые старые имена |
| `items` | 1537 `ItemKey` |
| `effects` | 40 `EffectKey` |
| `entity` | 158 `EntityTypeKey` |
| `selector` | 5 констант `Selector` и конструктор `Selector("@a[tag=builders]")` |

Все каталоги статические и доступны без сервера. IDE подсказывает имена после
точки. Типы ключей различаются: передача эффекта вместо предмета является
ошибкой. Полные строковые ключи доступны для тех же параметров; наличие ключа
и соответствие параметров проверяет сервер.

`TargetResult(matched, applied, targets)` содержит `TargetOutcome(uuid,
applied, code)` по каждой выбранной цели. Успех: `applied=True`, `code=None`.
`matched` — число выбранных UUID, `applied` — число успешных исходов.
Общего отката при выходе игрока или отказе после проверки нет.
У `InventoryResult` отдельные количественные поля, описанные выше.
Ссылки и модели неизменяемы; чтение их полей не делает сетевых запросов.

Из `minebridge.models` также доступны `normalize_block`, `normalize_item`,
`normalize_coordinate`, `normalize_position`, `normalize_real_coordinate`
для проверки описаний и координат без подключения.

Ошибки и границы версии
-----------------------

Ошибки импортируются из `minebridge.errors`; общий базовый класс —
`MinecraftError`. Некорректный локальный тип/значение также может дать
стандартные `TypeError` или `ValueError` до отправки.

| Ошибка | Значение |
|---|---|
| `ConnectionError`, `OperationTimeoutError` | Соединение или сетевое ожидание |
| `AuthenticationError`, `ProtocolVersionError`, `ProtocolError` | Авторизация, несовместимый или повреждённый обмен |
| `WorldNotFoundError`, `CoordinateOutOfBoundsError`, `ChunkLoadError` | Мир, координаты или неудачная загрузка чанка |
| `InvalidBlockError`, `UnsupportedLegacyBlockError`, `RegionBusyError` | Описание блока, старое соответствие или занятая область |
| `PlayerNotFoundError`, `EntityNotFoundError` | Указанная цель отсутствует |
| `InvalidSelectorError`, `InvalidTargetError` | Синтаксис выбора или неподходящий набор |
| `MissingContextError`, `ContextWorldMismatchError` | Не задан нужный исполнитель или его пространственный мир не совпадает |
| `InvalidItemError`, `InvalidEffectError`, `InvalidEntityTypeError`, `UnsupportedEntityTypeError` | Неподходящий предмет, эффект или способ создания сущности |
| `LimitExceededError` | Превышен предел области, целей или допустимого ответа |
| `InvalidArgumentError`, `PermissionDeniedError`, `ServerOperationError`, `UnsupportedFeatureError` | Некорректные аргументы, отказ или серверная/неподдержанная операция |

В buffered-режиме ошибка записи может появиться при следующей записи, чтении,
`flush` или `close`. Поля исключения: `.code`, `.method`, `.request_id`,
`.outcome`. У первой ошибки барьера `.failures` содержит собранные ошибки
этого барьера. `not-applied` означает отказ до применения; `unknown` означает,
что при разрыве или сбое отправленная мутация могла выполниться. Повторов и
автоматического восстановления соединения нет. Полученное подтверждение
не означает сохранения мира на диск или возможность отката.

В 0.2 нет scoreboard, событий, title/actionbar, зачарований, произвольного NBT
и компонентов предметов. `spawnEntity` пишется именно так; вариант с опечаткой
`spawnEnitiy` не является методом. Полная совместимость mcpi не заявляется.
Внутренние модули `_...` и транспорт не относятся к пользовательскому API.
Точный контракт — [V0_2_CONTRACT.ru.md](contracts/V0_2_CONTRACT.ru.md).

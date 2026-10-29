Minebridge 0.3.1 — справочник API
===================================

Документ от 29 октября 2026 года описывает API 0.3 с совместимым дополнением
[0.3.1](releases/0.3.1.ru.md). Локальный комплект — `dist/v0.3.1/`,
после публикации — [GitHub Releases](https://github.com/ilyak163rus/minebridge/releases).
I01 добавляет управление игрой,
I02 — чат и его историю, I03 — остальные игровые события и фильтры,
I04 — точные слоты сундуков и игроков. I05 объединяет приёмку и поставку
по [плану](IMPLEMENTATION_PLAN_V0_3.ru.md).
[Контракт I01](contracts/V0_3_CONTRACT.ru.md),
[отчёт I02](reports/V0_3_I02.ru.md),
[отчёт I03](reports/V0_3_I03.ru.md),
[отчёт I04](reports/V0_3_I04.ru.md),
[приёмка поставки I05](reports/V0_3_I05.ru.md),
[существующий API 0.2](API_V0_2.ru.md),
[пример управления](../examples/v03_controls.py).

В 0.3.1 добавлены `selector.playerByName(name: str) -> Selector`,
`errors.PeacefulSpawnError` и быстрый проход setBlocks до 32 768 блоков.
Сигнатуры, обработка отсутствующего игрока, точный регистр и пределы скорости
описаны в [дополнении 0.3.1](releases/0.3.1.ru.md).

Подключение и завершение
-----------------------

Два позиционных параметра `Minecraft.create(ip, port)` сохранены. По умолчанию
используется buffered, токен/имя мира не требуются, logging выключен.
Варианты `from minebridge import Minecraft` и
`from minebridge.minecraft import Minecraft` остаются эквивалентными.

```python
from minebridge import Minecraft, selector

with Minecraft.create("192.168.0.200", 4712, player="CurrentNick") as mc:
    print(mc.server.getInfo())
    print(mc.players.getPos(selector.SELF))
```

`with` возвращает подключённый фасад и вызывает `close()` с ожиданием записей
при выходе. Если тело уже выбросило исключение, ошибка закрытия добавляет note,
не скрывая исходную причину. При обычном выходе короткого Python-скрипта
автоматическое ожидание команд 0.2.1 тоже сохраняется.

Публичная информация о подключении
---------------------------------

| Метод | Результат |
|---|---|
| `mc.server.getInfo()` | Неизменяемый `ConnectionInfo` из hello |
| `mc.server.getCapabilities()` | `tuple[str, ...]` доступных RPC-возможностей |

ConnectionInfo содержит sessionId (UUID), pluginVersion/serverVersion,
protocolMajor/protocolMinor, writeMode, logging, capabilities и WorldInfo.
WorldInfo содержит name, key, uuid (UUID), minY, maxYExclusive.
Это локальные метаданные согласования, без нового RPC; они не обещают текущие
TPS, онлайн-состояние игрока или бессрочную актуальность мира. Чтение сведений
возможно и после закрытия. `withContext` сохраняет эти данные и общий транспорт.

Селекторы и позиция
------------------

```text
mc.setPos(targets,x,y,z,*,world=None) -> TargetResult
mc.players.setPos(targets,x,y,z,*,world=None) -> TargetResult
```

Оба метода делегируют прежний `mc.players.teleport`. Селектор идёт перед
координатами. Дробные координаты сохраняются, нужные чанки загружаются сервером.
Старый teleport остаётся; неявного выбора SELF по IP/компьютеру/последнему
полученному ID не возникает. Для SELF задайте текущий ник через player либо
создайте `mc.withContext(player=...)`.

```python
mc.setPos(selector.SELF, 10.5, 80, 20.5)
mc.players.setPos(selector.ALL_PLAYERS, 0.5, 90, 0.5)
```

Эффекты
-------

```text
mc.effects.add(targets,effect,duration,level=1,*,particles=True) -> TargetResult
mc.effects.remove(targets,effect) -> TargetResult
mc.effects.clear(targets) -> TargetResult
```

```python
from minebridge import effects, selector

mc.effects.add(selector.SELF, effects.SPEED, 100, 200)
mc.effects.add(selector.SELF, effects.SPEED, duration=100, level=200)
mc.effects.remove(selector.SELF, effects.SPEED)
mc.effects.clear(selector.SELF)
```

Первые два вызова эквивалентны: 100 игровых секунд, уровень 200. Level=1 —
первый уровень; диапазон 1..256. Duration положительная и конечная, округляется
вверх до целого тика и должна помещаться в int32 тиков. Particles остаётся
именованным параметром. Снятие отсутствующего эффекта/очистка уже пустого набора
считается обработанным запросом; отмена другим плагином отражается в результате.
Targets должны быть живыми сущностями.

Игровой режим, здоровье и сытость
--------------------------------

| Метод | Результат/единицы |
|---|---|
| `mc.players.getGameMode(target)` | `GameMode` одного онлайн-игрока |
| `mc.players.setGameMode(targets,mode)` | `TargetResult` |
| `mc.players.getHealth(target)` | `float`, очки здоровья |
| `mc.players.setHealth(targets,value)` | `TargetResult`; 0 может привести к смерти |
| `mc.players.getFoodLevel(target)` | `int` одного игрока |
| `mc.players.setFoodLevel(targets,value)` | `TargetResult`; целое 0..20 |

```python
from minebridge import gamemode, selector

mc.players.setGameMode(selector.ALL_PLAYERS, gamemode.ADVENTURE)
print(mc.players.getGameMode(selector.SELF))
mc.players.setHealth(selector.SELF, 10)
mc.players.setFoodLevel(selector.SELF, 20)
```

GameMode-константы: SURVIVAL, CREATIVE, ADVENTURE, SPECTATOR. Допускаются также
их lowercase строки. Getter требует ровно одного игрока. Setter разрешает
группу один раз, предварительно проверяет все цели и возвращает исход по UUID.
После начала исполнения возможен частичный результат, без общего rollback.

HP измеряется очками здоровья: обычные 20 очков — 10 сердец. Фактический
максимум может отличаться; сервер проверяет его для каждого игрока до мутации.
Minecraft хранит HP с float32-точностью, поэтому readback может отличаться от
десятичной записи Python в пределах этого представления. Положительное число,
которое нормализуется в ноль, отклоняется. Bool вместо числа не принимается.

Настройки миров
---------------

```text
mc.worlds.getTime(*,world=None) -> int
mc.worlds.setTime(time,*,world=None) -> None
mc.worlds.getWeather(*,world=None) -> Weather
mc.worlds.setWeather(weather,*,world=None) -> None
mc.worlds.getGameRule(rule,*,world=None) -> bool | int
mc.worlds.setGameRule(rule,value,*,world=None) -> None
```

```python
from minebridge import gamerule, weather

mc.worlds.setGameRule(gamerule.KEEP_INVENTORY, True)
mc.worlds.setGameRule(gamerule.DO_DAYLIGHT_CYCLE, False)
mc.worlds.setTime(6000)
mc.worlds.setWeather(weather.CLEAR)
print(mc.worlds.getGameRule(gamerule.KEEP_INVENTORY))
```

World=None означает выбранный при подключении мир, без имени в config.yml.
Явное world принимает имя/ключ другого загруженного мира. UUID мира сессии
остаётся закреплённым, поэтому пересозданный мир с тем же именем не подменяет
контекст незаметно.

Время — целое 0..23999 тиков суток, не секунды. Установка более раннего времени
следует семантике Paper и может продвинуть абсолютный день. Отдельный setFullTime
не входит. Weather: CLEAR/RAIN/THUNDER или lowercase строки. Обычный игровой
цикл может изменить время/погоду позднее; никакого скрытого scheduler нет.

GameRuleKey[T] содержит canonical namespaced key, valueType и defaultValue.
Каталог gamerule генерируется из фактически экспортированного Registry.GAME_RULE
закреплённого Paper133. Константы типизированы bool/int и доступны IDE офлайн.
Совместимые legacy-имена добавляются только при тождестве canonical-объекту;
преобразующие/инвертирующие старые wrappers не маскируются под современное правило.

Getter сохраняет тип bool/int. Setter не принимает 1 вместо True или True
вместо целого значения известного правила. Int ограничен int32; остальные
ограничения конкретного правила проверяются сервером. Допускается строка ключа;
для известной строки применяется та же локальная проверка типа.

Результаты и совместимость
-------------------------

Все новые remote-методы синхронны при обоих writeMode и ждут предыдущие
buffered-записи. Они заранее проверяют capability; клиент со старым плагином получает
UnsupportedFeatureError без отправки неизвестной команды. Позиционные эффекты
и setPos используют прежние RPC и не требуют новой capability.

TargetResult содержит matched, applied и tuple targets. Каждая цель имеет
uuid, applied и code. Например, отменённый другим плагином режим —
GAME_MODE_REJECTED; неправильное фактическое значение — PLAYER_VALUE_REJECTED.
При неизвестном результате мутация не повторяется автоматически.

Новые исключения: InvalidGameModeError, InvalidGameRuleError,
InvalidRuleValueError, InvalidPlayerValueError, InvalidWeatherError и
WorldChangeRejectedError. При неудаче сервер не выдаёт неподтверждённое значение
за успешное применение.

События чата (I02)
-----------------

[Контракт доставки и истории](contracts/V0_3_I02_CONTRACT.ru.md),
[полный пример](../examples/v03_chat_events.py).
Каталог I02 содержит `events.CHAT_MESSAGE`. Его обработчик получает
неизменяемый `ChatEvent`: eventId, serverEpoch, sequence, serverTick, eventType,
world, player, message, cancelled, truncated. В живом событии дополнительно
есть subscriptionId/deliverySequence. PlayerRef содержит UUID, name и entityId;
world — UUID, name и key. Снимок не меняется вслед за состоянием сервера.

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("192.168.0.200", 4712) as mc:
    def on_chat(event: ChatEvent) -> None:
        if event.message == "!diamond":
            mc.players.giveItem(event.player, items.DIAMOND, 1)
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

`run()` блокирует вызвавший поток и выполняет функции последовательно в нём.
Внутри обработчика доступны обычные синхронные методы Minebridge. Исключение
функции выходит из run; `Ctrl+C` обрабатывается обычным try/finally.
`stop()` завершает цикл после текущей функции и будит ожидающий poll, сохраняя
подписки и соединение. Повторный run разрешён. close освобождает подписки и будит
ожидание. Произвольную зависшую функцию Python принудительно остановить нельзя.

```text
subscribe(eventType, handler=None, *, players=selector.ALL_PLAYERS,
          world=None, region=None, blocks=None) -> Subscription
poll(timeout=0.0) -> ChatEvent | None
run() -> None
stop() -> None
```

Subscription содержит id, eventType, world (UUID); unsubscribe идемпотентен.
Для ручного получения укажите handler=None и вызывайте poll. timeout измеряется
в секундах, None означает неограниченное ожидание. Одновременно на TCP-соединении
работает один потребитель run/poll; второй получает RuntimeError. История ниже
не считается таким потребителем. Для run у каждой активной подписки нужен handler.

players принимает ALL_PLAYERS, SELF, имя, UUID, PlayerRef или список явных игроков.
ALL_PLAYERS динамически выбирает игроков мира подписки; имя закрепляется как UUID
при регистрации. SELF требует player= при create/withContext и не меняется
на автора события. Чтобы обратиться к автору, передавайте event.player.
Случайный/ближайший/сложный селектор в подписке не поддерживается. World=None
означает мир подключения; явное имя/ключ выбирает другой загруженный мир.
region/blocks для чата запрещены. Новая подписка получает только сообщения после
её регистрации, а не накопленный до неё чат.

postToChat отправляет текст игрокам и не создаёт CHAT_MESSAGE, поэтому ответ
обработчика не запускает его снова. Отменённый другим плагином чат пропускается.
Python наблюдает уже произошедшее событие и не может отменить его синхронно.
serverTick/world фиксируются при нормализации в основном потоке сервера.
serverTick — счётчик тиков Minebridge с начала serverEpoch, а не время суток
и не Minecraft fullTime. Перезапуск плагина создаёт новый epoch.

Новые сообщения и история (I02)
------------------------------

```python
for event in mc.events.pollChatPosts(limit=100):
    print(event.player.name, event.message)

recent = mc.events.getRecent(events.CHAT_MESSAGE, limit=20)
for event in recent:
    print(event.message)

mc.events.clearPending(events.CHAT_MESSAGE)
mc.events.clearAll()  # то же, что clearPending() для всех типов
```

```text
pollEvents(eventType, *, limit=100) -> EventBatch
pollChatPosts(*, limit=100) -> EventBatch[ChatEvent]
getRecent(eventType, limit=20) -> RecentEvents
clearPending(eventType=None) -> None
clearAll() -> None
```

Эти методы работают без subscribe/run. Первое чтение включает сообщения после
успешного подключения, даже если прошло некоторое время до первого poll.
Каждая TCP-сессия имеет собственные курсоры. pollChatPosts и pollEvents(CHAT_MESSAGE)
двигают один общий курсор; withContext разделяет его и живой dispatcher исходного
соединения. Курсор меняется только после полностью проверенного ответа.

EventBatch — последовательность: for, len, индекс и срез; поля events (tuple),
fromCursor, nextCursor, upperBound, availableFrom, hasMore описывают прочитанный
интервал. Сервер фиксирует upperBound на начало запроса. При hasMore вызовите
poll повторно. Страница может быть меньше limit из-за ограничения байт.
limit — целое 1..1000. EventCursor содержит epoch, world и sequence.

getRecent возвращает последние limit событий в порядке возрастания sequence,
при необходимости собирая несколько страниц одного фиксированного окна.
RecentEvents содержит events, nextCursor, upperBound, availableFrom, sessionStart,
windowLimited; чтение не меняет pull-курсор и живую очередь. До подключения история
недоступна. При первоначально истёкшей старой истории windowLimited=True обозначает
доступное окно. Потеря требуемых данных между страницами прерывает весь getRecent.

clearPending перемещает только курсор своей сессии к текущему хвосту журнала,
включая ещё не прочитанные типы. Он не удаляет общий журнал, чужую историю,
подписки или живые callbacks. Чтение истории не потребляет живую очередь и наоборот.

Границы событий и ошибок
-----------------------

Журнал хранится в RAM: до 4096 записей / 4 MiB закодированных данных / 2400 тиков на мир (первый
достигнутый предел), до восьми удерживаемых миров. Это окно истории, не постоянный
лог. Каждая сессия допускает до 32 подписок и очередь до 512 живых событий.
Переполнение сервера или Python вызывает EventOverflowError с source
server/capture/python, lostCount и subscriptionIds. Затронутая подписка BROKEN:
run/poll повторяют ошибку до её удаления; восстановление — unsubscribe и новая
подписка. Обычные RPC и другие сессии продолжают работать, автоматического replay нет.

При утрате непрочитанного интервала EventHistoryLostError оставляет курсор на месте.
Для продолжения явно вызовите clearPending; живые подписки от этой ошибки не ломаются.
Также есть InvalidEventTypeError и SubscriptionNotFoundError. Старый сервер без
event capabilities даёт UnsupportedFeatureError до отправки запроса. logging=True
добавляет серверные записи подписки/отписки и постановки/потери live-кадров; это
подтверждение отправки, а не выполнения Python-функции.

Игровые события и фильтры (I03)
------------------------------

[Контракт I03](contracts/V0_3_I03_CONTRACT.ru.md),
[пример трёх обработчиков](../examples/v03_game_events.py).
Правила run/poll/stop, поток обработчика, очереди и история остаются теми же.
В I03 live `poll()` возвращает `Event | None`; конкретная модель определяется
типом подписки. Типизированный handler по-прежнему выводится из EventType.
Новому типу нужна отдельная capability `events.type.<type>`; на I02-сервере
чат продолжает работать, новые типы дают UnsupportedFeatureError до запроса.

| Константа events | Модель и основные поля |
|---|---|
| CHAT_MESSAGE | ChatEvent: player, message |
| BLOCK_BREAK | BlockBreakEvent: player, position, block, cancelled |
| BLOCK_PLACE | BlockPlaceEvent: player, position, block, replacedBlock, cancelled |
| BLOCK_INTERACT / BLOCK_HIT | BlockInteractEvent: player, position, block, face, action, hand, item, useInteractedBlock, useItemInHand, cancelled |
| ENTITY_ATTACK | EntityAttackEvent: player, target, willAttack, cancelled |
| ENTITY_DAMAGE | EntityDamageEvent: victim, directSource, causingEntity, cause, rawDamage, finalDamage, cancelled |
| PLAYER_DAMAGE | PlayerDamageEvent: те же поля, player — ссылка на victim-игрока |
| PLAYER_ENTER_LAVA | LavaEnterEvent: player, position |
| PLAYER_JOIN / PLAYER_QUIT | PlayerJoinEvent / PlayerQuitEvent: player |
| PLAYER_DEATH | PlayerDeathEvent: player, position |
| PLAYER_RESPAWN | PlayerRespawnEvent: player, reason, respawnLocation |
| PROJECTILE_SHOT | ProjectileShotEvent: projectile, shooter, sourceBlock, position, velocity, weapon, hand, force, cancelled |
| PROJECTILE_HIT | ProjectileHitEvent: projectile, shooter, sourceBlock, position, hitEntity, hitBlock, hitFace, cancelled |

Все модели экспортируются из minebridge.models. EventPosition содержит x/y/z,
поддерживает распаковку `x,y,z = event.position`. EventBlock содержит position
и BlockSpec в block. EventLocation содержит world, position, yaw, pitch.
Миры — EventWorld (uuid/name/key). Ссылки — PlayerRef, LivingEntityRef или
EntityRef; координаты не запрашиваются скрыто при обращении к свойству.
Снимки блоков содержат состояния, item/weapon — только ItemKey либо None.

BLOCK_HIT — та же константа/тип, что BLOCK_INTERACT, не второй источник.
PLAYER_DAMAGE — представление canonical ENTITY_DAMAGE для жертвы-игрока:
одинаковые eventId, sequence и данные, отдельные подписки/курсоры двух типов.
Подписка на оба типа ожидаемо даёт две доставки одного факта.
cause — damageCause.DamageCause либо неизвестная строка будущего native значения.
Каталог damageCause содержит 33 значения из Paper API133, например
`damageCause.LAVA`, `damageCause.FALL`, `damageCause.PROJECTILE`.

```python
from minebridge import events, block, damageCause
from minebridge.models import Region

world = mc.server.getInfo().world
arena = Region(world.uuid, (0, -64, 0), (100, 319, 100))

subscription = mc.events.subscribe(
    events.BLOCK_BREAK, on_break,
    region=arena, blocks=[block.COBBLESTONE, block.STONE],
)

for damage in mc.events.pollDamageEvents():
    if damage.cause == damageCause.LAVA:
        print(damage.victim, damage.finalDamage)
```

Region принимает UUID мира и два угла; порядок углов нормализуется. Целые границы
включены, для дробных позиций сравнение с min/max численное. region допустим
у block/attack/damage/lava/death/respawn/projectile, запрещён у chat/join/quit.
Точка фильтра — блок, цель атаки, жертва урона, игрок, respawnLocation или снаряд
соответственно. Мир Region должен совпадать с миром подписки.
blocks принимает один BlockInput или последовательность; сравниваются ключи
поставленного/разрушаемого/кликнутого блока, без состояний. Этот фильтр доступен
только block-событиям. Пустой список не выбирает ни одного блока.
Фильтры пересекаются на сервере до отправки, неправильная опция не игнорируется.

players=None отключает player-фильтр. ALL_PLAYERS динамически выбирает игрока-
актора: урон — по жертве, снаряды — по стрелку, остальные типы — по player.
Поэтому для мобов и раздатчика используйте players=None. Неизвестный стрелок
остаётся None; sourceBlock доступен для раздатчика. SELF остаётся UUID контекста.

```text
pollBlockHits(*, limit=100) -> EventBatch[BlockInteractEvent]
pollEntityAttacks(*, limit=100) -> EventBatch[EntityAttackEvent]
pollDamageEvents(*, limit=100) -> EventBatch[EntityDamageEvent]
pollProjectileShots(*, limit=100) -> EventBatch[ProjectileShotEvent]
pollProjectileHits(*, limit=100) -> EventBatch[ProjectileHitEvent]
```

Эти методы делегируют pollEvents соответствующего типа; BLOCK_HIT и
pollBlockHits делят курсор BLOCK_INTERACT. pollDamageEvents читает ENTITY_DAMAGE;
PLAYER_DAMAGE читается отдельно через pollEvents. Чтение одного типа не забирает
другой; потеря истории учитывается по типу, включая damage-проекцию.

Попытки, результат и контакт
--------------------------

Клики сохраняют LEFT_CLICK_BLOCK/RIGHT_CLICK_BLOCK, HAND/OFF_HAND и результаты
использования DEFAULT/ALLOW/DENY. События обеих рук не склеиваются по тику.
ENTITY_ATTACK — попытка; willAttack не гарантирует нанесённый урон.
PROJECTILE_HIT — контакт, hitEntity/hitBlock/hitFace могут быть None;
position — положение снаряда при наблюдении. Пронизывающая стрела может дать
несколько попаданий с одним UUID. SHOT — один принятый запуск UUID, multishot
даёт несколько UUID; дополнительные native bow-сведения не создают второй запуск.
weapon/hand/force допускают None там, где native источник их не сообщил.

Попытки block.interact/entity.attack/projectile.hit сохраняют cancelled.
Отменённые chat/break/place/damage/launch не доставляются. Снимок отражает фазу
MONITOR; finalDamage — вычисленное в ней значение, не гарантированная разница HP.
Python setBlock/setBlocks не порождают BLOCK_BREAK или BLOCK_PLACE.

Контакт с лавой наблюдается отдельно от урона раз в игровой тик. Первый sample
при активации мира — baseline без искусственного входа. false→true создаёт
один PLAYER_ENTER_LAVA, пребывание внутри не создаёт событие каждый тик.
Выход/возврат, teleport/смена мира и respawn могут начать новый контакт.
Creative и fire resistance не отключают обнаружение. Новая подписка учитывает
текущий контакт без сброса состояния старых подписок. Короткий контакт целиком
между двумя samples может быть не обнаружен. PLAYER_RESPAWN содержит причину
DEATH/END_PORTAL/PLUGIN и наблюдаемую respawnLocation; это не подтверждение уже
завершённого перемещения игрока.

Точные слоты инвентарей (I04)
----------------------------

[Контракт](contracts/V0_3_I04_CONTRACT.ru.md),
[пример](../examples/v03_inventory_slots.py).

```python
from minebridge import items, selector, slots
from minebridge.models import ItemStack

chest = mc.inventories.ofBlock(10, 80, 10)
result = chest.setItem(0, items.DIAMOND, 16)
print(result.previous, result.current)
print(chest.getItem(0))
print(chest.getContents())
chest.clear(0)

inventory = mc.inventories.ofPlayer(selector.SELF)
inventory.setItem(slots.HEAD, items.DIAMOND_HELMET, 1)
inventory.setItem(slots.OFF_HAND, items.SHIELD, 1)
inventory.setItem(0, ItemStack(items.DIAMOND, 4, name="Reward", lore=("Round 1",)))
mc.players.setItem(selector.ALL_PLAYERS, 8, items.COMPASS, 1)
```

```text
mc.inventories.ofBlock(x,y,z,*,world=None,combined=False) -> InventoryRef
mc.inventories.ofPlayer(target) -> InventoryRef
inventory.getItem(slot) -> ItemView | None
inventory.getContents() -> dict[Slot,ItemView | None]
inventory.setItem(slot,item,amount=None) -> SlotWriteResult
inventory.clear(slot=None) -> InventoryUpdateResult
mc.players.setItem(targets,slot,item,amount=None) -> TargetResult
```

Все эти методы синхронны при обоих writeMode и ждут предыдущие buffered записи.
Ссылка не требует открытого игрового окна. ofPlayer разрешает ровно одного
онлайн-игрока; SELF требует player при create/withContext. Для группы есть
players.setItem. Ссылка закреплена за UUID и сохраняется при перемещении игрока
между мирами; выход игрока даёт PlayerNotFoundError.

Нумерация и замена
-----------------

У игрока публичные слоты: 0..35 (хотбар0..8), затем slots.HEAD, CHEST, LEGS,
FEET, OFF_HAND. Это EquipmentSlot StrEnum с wire-значениями head/chest/legs/feet/
off_hand. Числовые36..40, BODY/SADDLE и window IDs не входят в этот API.
Одежные слоты допускают один предмет; offhand использует обычный native предел.
Категория материала не ограничивается дополнительно: это прямой доступ к слоту.

setItem **заменяет весь прежний стек**, не складывает его с новым и не ищет
свободное место. Amount должен быть положительным и не больше native максимума
предмета, инвентаря и слота. Например, 64 меча в одном слоте дают ошибку до
изменения. giveItem продолжает распределять предметы и учитывать остатки,
его правила не меняются. Amount0 не очищает слот — используйте clear(slot).

SlotWriteResult — frozen applied, slot, previous/current. После успешной записи
current содержит проверенный ItemView; previous — прежнее содержимое или None.
clear(slot) очищает один слот, clear() — все публичные слоты. У игрока BODY/SADDLE
сохраняются. InventoryUpdateResult содержит applied и tuple slots подтверждённой
области очистки, включая уже пустые слоты. Это не количество отличий.

Bulk players.setItem разрешает селектор один раз и проверяет все выбранные цели
до первого изменения. Если позже кто-то вышел или запись не подтверждена,
возвращается компактный TargetResult с исходами по UUID. Автоматического rollback
или повторной попытки нет. clear/setItem проверяют фактическое состояние после
native setter, а не считают void-возврат доказательством успеха.

Сундуки и метаданные ссылки
--------------------------

Поддерживаются обычный и trapped chest. По умолчанию ofBlock адресует физическую
половину27, даже рядом со второй половиной. combined=True даёт общий54 или27,
если сундук одиночный. Общие0..26 соответствуют Paper left side,27..53 — right
side; порядок не зависит от направления взгляда или выбранной половины.

InventoryRef содержит локальные read-only свойства kind, size, slots, player,
world, position, combined, layout. Не относящиеся к виду ссылки значения — None
или пустой tuple. Player — UUID; world/position у block ref — UUID и tuple трёх
целых. Каждый InventoryPart в layout содержит position, offset, size и key.
Свойства доступны и после close, не выполняя скрытых RPC.

World=None означает UUID мира подключения, явный world — имя/ключ другого
загруженного мира. Править config.yml не требуется. Нужные чанки загружаются
через общий ChunkService при каждом RPC. UUID мира не подменяется новым миром
с прежним именем. При split/merge/reorder старый combined ref получает
InventoryChangedError; создайте новую ссылку. Physical half продолжает адресовать
свою половину при изменении соседства. Удалённый и повторно поставленный такой же
контейнер на том же месте не имеет обещанной вечной идентичности.

Чтение предметов и страниц
-------------------------

Пустой слот — None. getContents возвращает все публичные ключи, включая пустые
слоты, в порядке inventory.slots. При большом ответе SDK читает несколько
ограниченных страниц; при смене layout частичный dict не возвращается.
Это не атомарный снимок против игрока, воронки или другого плагина между страницами.
Изменение полученного словаря не изменяет сервер.

ItemView — отдельная frozen модель: key (ItemKey), amount, name, lore (tuple
или None), hasAdditionalData, truncated. Поддержанный plain name ограничен256
codepoints, lore —16 строками по256. При сокращении truncated=True; непредставимые
setter данные, зачарования, rich text, shulker contents и другие компоненты
отмечаются hasAdditionalData. Чтение не изменяет исходный предмет.

ItemView не принимается setItem: get→set не обещает lossless копирование.
Для создания используется прежний ItemStack/ItemKey/string с явными amount/name/
lore. Чтобы получить строку ключа представления, можно читать view.key.key;
сам view.key сравнивается с константой items.DIAMOND.

Ошибки инвентарей
----------------

InventoryNotFoundError — первый ofBlock без поддержанного сундука;
InventoryChangedError — существующая ссылка больше не соответствует layout;
InvalidSlotError — недоступный слот; InvalidItemAmountError — недопустимый стек;
InventoryWriteRejectedError — фактическая запись/очистка не подтверждена.
Также сохраняются PlayerNotFoundError, InvalidTargetError, InvalidItemError,
ошибки мира/координат/чанков и локальные TypeError/ValueError.
При отсутствии capability старый сервер даёт UnsupportedFeatureError до RPC.
После начала изменения неизвестный результат имеет outcome=unknown;
скрытого исправления, rollback или retry нет. logging=True включает новые RPC
в прежний ограниченный серверный журнал действий.

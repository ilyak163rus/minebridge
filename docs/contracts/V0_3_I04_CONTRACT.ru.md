# 0.3 / I04 — точные слоты

Контракт реализации от 28 октября 2026 года, по разделу3 плана0.3. Протокол2.0,
старые API/create/буферизация/события сохранены. Установочная поставка — I05.

## Публичный Python

```
mc.inventories.ofBlock(x,y,z,*,world=None,combined=False) -> InventoryRef
mc.inventories.ofPlayer(target) -> InventoryRef
ref.getItem(slot) -> ItemView | None
ref.getContents() -> dict[Slot,ItemView | None]
ref.setItem(slot,item,amount=None) -> SlotWriteResult
ref.clear(slot=None) -> InventoryUpdateResult
mc.players.setItem(targets,slot,item,amount=None) -> TargetResult
```

Все RPC синхронны и являются барьером buffered writes в обоих writeMode.
Slot — int0..35 у игрока, int0..size−1 у сундука или slots.EquipmentSlot:
HEAD="head", CHEST="chest", LEGS="legs", FEET="feet", OFF_HAND="off_hand".
Bool, float, числовые36..40 и window IDs у игрока запрещены. Константы
экспортируются из `minebridge.slots`, доступны IDE офлайн. Порядок player slots:
0..35, head,chest,legs,feet,off_hand (size41). BODY/SADDLE не доступны и clear()
их не затрагивает. Одежные слоты ограничены одним предметом, offhand — обычным
пределом стека. Категория материала в armor не ограничивается дополнительно.

ItemInput прежний ItemKey/ItemStack/string, ItemView не принимается setter.
setItem заменяет слот целиком, не складывает/не выбрасывает. Amount положительное,
не больше min(native ItemStack maxStackSize,inventory maxStackSize,slot limit).
Неправильный amount/slot до изменения — ошибка. Для очистки есть clear, amount0
не принимается. giveItem не меняется. После setter/clear проверяется фактическое
состояние; неподтверждённый результат не считается applied, retry/rollback нет.

ItemView — frozen `{key,amount,name,lore,hasAdditionalData,truncated}`; key:ItemKey,
name nullable plain string<=256 Unicode codepoints, lore nullable tuple<=16 строк,
каждая<=256codepoints; amount1..int32max. Truncation явно отмечается. Rich styled/
translatable name/lore и другие компоненты считаются additionalData. Для обычного
предмета только с поддержанными plain name/lore hasAdditionalData=False. Чтение
не изменяет исходный предмет и не обещает lossless копирование.

SlotWriteResult frozen: applied=True, slot, previous/current:ItemView|None.
InventoryUpdateResult frozen: applied=True, slots:tuple[Slot,...] — подтверждённая
область очистки, включая уже пустые слоты; не счётчик отличий.
InventoryRef содержит read-only local metadata: kind,size,slots,player,world,
position,combined,layout; не относящиеся к kind свойства None/пустой tuple.
InventoryPart: position,offset,size,key. Свойства не выполняют RPC.

## Идентичность и сундуки

ofPlayer разрешает ровно одного online игрока с прежними правилами selection/SELF.
Ссылка закрепляет UUID, не имя/runtimeID; перемещение игрока между мирами не
подменяет inventory. Чтение/запись офлайн игрока — PLAYER_NOT_FOUND.

Обычный/trapped chest: physical half по умолчанию27. combined=True использует
порядок публичных Paper DoubleChestInventory.getLeftSide()/getRightSide():
левые0..26, правые27..53; это серверный порядок, не направление взгляда.
Одиночный combined=True остаётся27. Каждый RPC заново проверяет тип/layout;
split/merge/reorder/material change несовместимого descriptor → INVENTORY_CHANGED.
Physical half не меняет layout при присоединении/отделении соседней половины.
Удалённый и повторно поставленный такой же сундук на том же месте не имеет
обещанной вечной идентичности. Первый ofBlock без сундука → INVENTORY_NOT_FOUND.

World=None — закреплённый UUID мира подключения. Явное имя/ключ — другой loaded
мир, без изменения config. Ссылка хранит UUID. Каждый RPC через общий ChunkService
асинхронно загружает/удерживает нужные чанки и проверяет границы. Для определения
double layout можно удержать anchor и возможные четыре горизонтальных соседа
(уникальные chunks, ограниченный набор), без скрытой синхронной загрузки.

## Stateless wire refs

PlayerRef descriptor (не путать с entity PlayerRef):
`{kind:"player",player:UUID,size:41,slots:[0..35,"head","chest","legs","feet","off_hand"]}`.
Chest descriptor:
`{kind:"chest",world:UUID,position:[int,int,int],combined:bool,size:27|54,
slots:[0..size−1],layout:[{position:[int,int,int],offset:0|27,size:27,key:namespaced}]}`.
layout length1/2, key только minecraft:chest/trapped_chest; одинаковый материал,
два блока горизонтально соседние, anchor принадлежит layout, offsets по порядку.
Refs не требуют бесконечного server handle registry. Каждое обращение валидирует
descriptor и реальный layout до операций; transport/auth не меняются.

Capabilities равны именам RPC ниже. Новые клиенты проверяют capability перед RPC.

| RPC | params | result |
|---|---|---|
| inventories.ofBlock | world:sessionName,destinationWorld:string|null,position:[int,int,int],combined:bool | {inventory:descriptor} |
| inventories.ofPlayer | world:sessionName,executor:UUID|null,targets:TargetSpec | {inventory:descriptor} |
| inventories.getItem | inventory:descriptor,slot:Slot | {slot,item:ItemView|null} |
| inventories.getContents | inventory:descriptor,offset:int,limit:int1..54 | {items:[{slot,item}],nextOffset:int|null,total:int} |
| inventories.setItem | inventory:descriptor,slot:Slot,item:old ItemStack wire | {applied:true,slot,previous,current} |
| inventories.clear | inventory:descriptor,slot:Slot|null | {applied:true,slots:[Slot...]} |
| players.setItem | world:sessionName,executor:UUID|null,targets:TargetSpec,slot:Slot,item:old ItemStack wire | прежний TargetResult |

ItemView wire: `{key:namespaced,amount:int,name:string|null,lore:list[string]|null,
hasAdditionalData:bool,truncated:bool}`. Все ключи обязательны, неизвестные ключи
запросов/descriptor/result отвергаются. Базовый ItemStack wire не меняется.

getContents SDK собирает страницы по offset индекса в ref.slots; key каждого
возвращённого элемента должен точно совпадать с соответствующим слотом. Total
совпадает с size, nextOffset прогрессирует без пропусков/дубликатов. Страница
ограничена32768байтами ItemView, общийframe<=65536. При layout error между
страницами частичный dict не возвращается. Это не атомарный snapshot против
игрока/воронки/другого плагина. Границы ItemView гарантируют previous+current
в одном bounded SlotWriteResult. Empty slot всегда None, ключи не сдвигаются.

players.setItem разрешает selector один раз, предвалидирует все цели/slot/item
перед первым изменением; выполняет ограниченными порциями с обычными FIFO,
activeOperation и progress/ChunkService lifecycle. После начала частичный
TargetResult допустим (например, player вышел), без rollback. Нет копий всех
инвентарей в bulk ответе. Ошибка всей prevalidation не меняет ни одного слота.

## Ошибки

| JSON-RPC | code | Python |
|---|---|---|
| -32048 | INVENTORY_NOT_FOUND | InventoryNotFoundError |
| -32049 | INVENTORY_CHANGED | InventoryChangedError |
| -32050 | INVALID_SLOT | InvalidSlotError |
| -32051 | INVALID_ITEM_AMOUNT | InvalidItemAmountError |
| -32052 | INVENTORY_WRITE_REJECTED | InventoryWriteRejectedError |

Также прежние PLAYER_NOT_FOUND/INVALID_TARGET/INVALID_ITEM/WORLD_NOT_FOUND,
CHUNK_LOAD_FAILED/COORDINATE_OUT_OF_BOUNDS и UnsupportedFeatureError.
До setter outcome=not-applied, после начала неизвестного результата — unknown.
Локальные type/value проверки допускаются раньше сети; ошибки не перехватываются
молчаливо. logging=True добавляет новые RPC в прежний bounded SessionActivityLog.

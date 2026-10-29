# 0.3 / I03 — игровые события и фильтры

Контракт реализации от 27 октября 2026 года. Расширяет I02 без смены protocol2.0,
очередей, lifecycle, подписок и правил history. Установочные пакеты — в I05.
Основание: IMPLEMENTATION_PLAN_V0_3.ru.md и EVENTS_V0_3.ru.md.

## Каталог и совместимость

Canonical types: chat.message, block.interact, block.break, block.place,
entity.attack, entity.damage, player.damage, player.enter_lava, player.join,
player.quit, player.death, player.respawn, projectile.shot, projectile.hit.
BLOCK_HIT — alias BLOCK_INTERACT (block.interact). PLAYER_DAMAGE — проекция
entity.damage для жертвы-игрока: одинаковые eventId/sequence/data, eventType
проекции player.damage; второго физического record в журнале нет.

Hello получает capabilities `events.type.<type>` для каждого типа. Форма
eventHistory I02 не меняется. Новые SDK проверяют type capability; chat.message
остаётся совместим с I02 без этого дополнительного маркера. Старый I02 клиент
продолжает получать только заказанный чат. Известный, но не объявленный тип
даёт локальный UnsupportedFeatureError; неизвестный — InvalidEventTypeError.

## Поля записей

Envelope I02 сохраняется: eventId/serverEpoch/sequence/serverTick/eventType/world/data.
Позиция/скорость — массив из трёх конечных чисел; блоковые позиции — int32.
Мир compact `{uuid,name,key}`. Entity snapshot: `{uuid,entityId,key,living,name}`;
name — имя игрока или null; key=minecraft:player с name даёт PlayerRef. Существующий
chat.data.player сохраняет прежнюю форму `{uuid,entityId,name}`. Ссылки не делают RPC.
Block snapshot — прежний BlockSpec `{key,states}`. sourceBlock/hitBlock — nullable
`{position:[int,int,int],block:BlockSpec}`. face — native enum name или null.

| Тип | Точные поля data |
|---|---|
| chat.message | прежние player,message,cancelled,truncated |
| block.break | player,position,block,cancelled=false |
| block.place | player,position,block,replacedBlock,cancelled=false |
| block.interact | player,position,block,face,action,hand,item,useInteractedBlock,useItemInHand,cancelled |
| entity.attack | player,target,willAttack,cancelled |
| entity.damage / player.damage | victim,directSource,causingEntity,cause,rawDamage,finalDamage,cancelled=false |
| player.enter_lava | player,position |
| player.join / player.quit | player |
| player.death | player,position |
| player.respawn | player,reason,respawnLocation |
| projectile.shot | projectile,shooter,sourceBlock,position,velocity,weapon,hand,force,cancelled=false |
| projectile.hit | projectile,shooter,sourceBlock,position,hitEntity,hitBlock,hitFace,cancelled |

player для всех не-chat типов — entity snapshot игрока. directSource,
causingEntity,shooter,hitEntity nullable. projectile/target/victim обязательны.
item/weapon — nullable namespaced key (не полноценный ItemStack).
hand — HAND/OFF_HAND или null; block.interact требует руку.
action — LEFT_CLICK_BLOCK/RIGHT_CLICK_BLOCK; use-results — DEFAULT/ALLOW/DENY.
rawDamage/finalDamage — конечные неотрицательные числа; force — nullable конечное
число. reason respawn — DEATH/END_PORTAL/PLUGIN (строка для будущих native значений).
Имена cause/face/reason соответствуют `[A-Z][A-Z0-9_]{0,63}`.
respawnLocation: `{world:compactWorld,position:[x,y,z],yaw:number,pitch:number}`.
cause — имя native DamageCause; статический каталог damageCause генерируется
из закреплённого Paper API133, не из сетевого справочника другой сборки.

Python получает неизменяемые typed snapshots с одноимёнными полями. Координаты
и скорость представлены immutable EventPosition (x,y,z, iterable). У
PlayerDamageEvent поле player — свойство той же victim-ссылки, без копии факта.
BLOCK_HIT/pollBlockHits разделяют cursor block.interact. Короткие методы:
pollEntityAttacks, pollDamageEvents, pollProjectileShots, pollProjectileHits;
остальные — pollEvents. pollDamageEvents читает canonical ENTITY_DAMAGE.

## Native фаза

Все игровые snapshots формируются на основном потоке, MONITOR. Cancelled
chat/break/place/damage/launch пропускаются. block.interact/entity.attack/
projectile.hit фиксируют попытку/контакт со статусом отмены. Не вычислять
отсутствующий урон по факту атаки/контакта; finalDamage — наблюдённое вычисление,
не гарантия окончательного HP. Python setBlock не создаёт BLOCK_BREAK/PLACE.
Block interaction сохраняет реальные уведомления двух рук без эвристик dedup.

Один принятый ProjectileLaunchEvent — один SHOT для UUID. EntityShootBowEvent
даёт только дополнительный контекст weapon/hand/force; не создаёт второй факт.
Native порядок проверяется на pinned runtime; контекст ограничен по размеру/времени,
очищается при отмене/удалении/disable. Multishot — несколько UUID. HIT может
повторяться для UUID (piercing); hit.position — позиция снаряда при наблюдении.
Unknown shooter=None; block source не превращается в игрока/SELF.

## Фильтры и история

subscribe сохраняет прежние обязательные поля I02. Необязательные wire params:
region `{world:UUID,min:[int,int,int],max:[int,int,int]}` (границы включены,
min<=max), blocks `list[namespacedKey]` до256 разных ключей. SDK отправляет эти
поля только при выбранном фильтре. Region Python принимает UUID мира и две
трёхмерные целочисленные границы, нормализует порядок углов.
region допустим у событий с точкой: block.*, attack (позиция цели), damage
(жертва), lava, death, respawn (respawnLocation), projectile.* (снаряд).
region для chat/join/quit запрещён. blocks допустим только block.* и сравнивает
key снимка block (не replacedBlock); состояния не участвуют. Неприменимый
фильтр — INVALID_PARAMS, UUID region должен совпадать с миром подписки.

players=None отключает player-фильтр. ALL_PLAYERS выбирает динамический
player-актор: block/chat/attack/lifecycle/lava — player; damage — player victim;
projectile — player shooter. Непользовательские акторы доступны с players=None.
SELF/явные UUID/имена сохраняют I02 семантику. Все фильтры пересекаются на сервере
до формирования live frame. Прямое history чтение фильтрует только тип/мир.

EventJournal хранит canonical facts один раз; poll/getRecent сканируют фиксированный
upperBound, продвигаются через другие типы, не пропускают невыданную подходящую
запись при byte-budget. Retention watermark ведётся для каждого поддержанного
типа и PLAYER_DAMAGE membership: вытеснение других типов не считается потерей
запрошенного типа. Capture-loss chat не ломает другие типы/подписки.
availableFrom в ответе — нижняя доступная граница запрошенного типа, включая
проекцию; сохраняет ограничения I02. Структура RPC результата не меняется.

## Контакт с лавой

Общий sampling Entity.isInLava раз в tick для игроков заинтересованных миров
(ready-сессии/история также включают monitor). Первый sample — baseline без
искусственного входа. false→true создаёт один fact, true→true не создаёт.
Отсутствие LAVA damage, creative и fire resistance не отключают контакт.
Смена мира/teleport/respawn сбрасывают контакт: новый подтверждённый true даёт
новый вход; join — baseline; death/quit исключают sampling до respawn/join.
Первичная активация мониторинга для уже стоящего игрока — baseline, новая
подписка не сбрасывает общий monitor. Её capture fence исключает старые факты.
Полностью краткий контакт между двумя samples не обещается обнаружить.
State очищается при уходе, unload/отсутствии интереса и disable.

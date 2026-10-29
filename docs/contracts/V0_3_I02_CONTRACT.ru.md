# Контракт 0.3 / I02: чат и доставка событий

Статус: зафиксирован для реализации I02. Основа — `EVENTS_V0_3.ru.md`;
I02 реализует только `events.CHAT_MESSAGE` (`chat.message`). Остальные игровые
события относятся к I03. Протокол остаётся 2.0. Установочные пакеты — в I05.

## Python

`mc.events.subscribe(events.CHAT_MESSAGE, handler=None, *, players=selector.ALL_PLAYERS,
world=None, region=None, blocks=None)` возвращает Subscription (`id`, `eventType`,
`world`, `unsubscribe()`). Для чата region/blocks запрещены. players допускает @a,
@s, имя, UUID, PlayerRef, последовательность явных игроков или None; @p/@r и
сложные селекторы не поддерживаются в подписке. Имена разрешаются при регистрации,
затем сравниваются UUID. SELF требует явно связанного исполнителя сессии.

`run()` выполняет обработчики в вызвавшем его потоке; `poll(timeout=0.0)` получает
одно живое событие без вызова обработчика. Одновременно разрешён один потребитель
run/poll на TCP-соединение, общий для withContext. stop() будит его, не закрывает
соединение и не удаляет подписки. Исключение обработчика выходит из run(). Чтение
сокета никогда не вызывает пользовательский код. close() будит потребителя.

`pollEvents(eventType, *, limit=100)` и `pollChatPosts(*, limit=100)` читают
отдельный курсор данного типа, общий для фасадов одного TCP-соединения.
`getRecent(eventType, limit=20)` читает последние события после подключения и не
двигает курсор. `clearPending(eventType=None)` / `clearAll()` перемещают только
курсоры чтения к текущему хвосту, включая ещё не читавшиеся типы. Живая очередь,
чужие сессии и серверный журнал не очищаются. EventBatch/RecentEvents — неизменяемые
последовательности с метаданными интервала; EventBatch имеет hasMore/nextCursor.
История доступна и без подписок. История и live не потребляют друг друга.

## Форматы

Все UUID — канонические строки; целые неотрицательны и не больше 2^53−1.
Курсор: `{epoch: UUID, world: UUID, sequence: int}`. sequence — граница уже
прочитанного интервала, а не индекс в клиентском списке.

Запись:

```json
{"eventId":"UUID", "serverEpoch":"UUID", "sequence":1, "serverTick":1,
 "eventType":"chat.message", "world":{"uuid":"UUID","name":"world","key":"minecraft:overworld"},
 "data":{"player":{"uuid":"UUID","name":"Alice","entityId":1},
         "message":"hello","cancelled":false,"truncated":false}}
```

Живая доставка (без id):

```json
{"jsonrpc":"2.0","method":"events.event","params":
 {"subscriptionId":"UUID","deliverySequence":1,"event":{}}}
```

deliverySequence начинается с 1 и увеличивается ровно на 1 для подписки. sequence
журнала может иметь пропуски из-за фильтра. Переполнение — отдельное уведомление:

```json
{"jsonrpc":"2.0","method":"events.overflow","params":
 {"subscriptionIds":["UUID"],"source":"server","lostCount":1}}
```

source сервера: server или capture; локальное переполнение Python: python.
Подписка становится BROKEN, её очередь удаляется; run/poll повторно сообщают
EventOverflowError до unsubscribe. Переполнение не закрывает RPC и другие сессии.

## Handshake и RPC

Запрос hello не меняется. Необязательное поле результата eventHistory:

```json
{"epoch":"UUID","world":"UUID","startSequence":0,
 "retention":{"maxRecords":4096,"maxBytes":4194304,"maxAgeTicks":2400},
 "maxSubscriptions":32,"maxLiveEvents":512}
```

Сервер начинает захват и фиксирует startSequence до публикации hello ACK. Поэтому
первое чтение включает чат после подключения, даже если poll вызван позже.
Клиенту без событий не посылаются незапрошенные уведомления. Новые capabilities:
events.subscribe, events.unsubscribe, events.pollEvents, events.getRecent,
events.clearPending. Старый сервер без них даёт локальный UnsupportedFeatureError.

* events.subscribe params: `{subscriptionId:UUID,eventType,world:string,
  executor:UUID|null,players:string|list[UUID]|null}`; result:
  `{subscriptionId,eventType,world:UUID}`. ACK должен предшествовать первому событию.
  Клиент создаёт PENDING до отправки; активирует только после принятого ACK.
* events.unsubscribe params `{subscriptionId}`; result
  `{subscriptionId,unsubscribed:true}`. Сервер удаляет ещё не выбранные reactor
  кадры подписки до ACK. Уже выбранный кадр заканчивается до ACK. После ACK новых кадров этой
  подписки нет. Python отбрасывает ранее поставленные в очередь уведомления.
* events.pollEvents params `{eventType,world:string,cursor:Cursor|null,limit:int}`.
  null разрешён при первом обращении к контексту мира: сервер берёт его базу
  сессии, а nextCursor сообщает UUID. Для основного мира клиент знает базу из hello.
  limit: 1..1000. result: `{events:[record],nextCursor:Cursor,upperBound:int,
  availableFrom:int,hasMore:bool}`. upperBound фиксируется в начале запроса.
  Курсор двигается через просмотренный интервал, но не перескакивает через
  не поместившуюся запись. Клиент меняет курсор только после полной валидации.
  Чтения одного типа сериализуются вместе с commit курсора.
* events.getRecent params `{eventType,world:string,limit:int,cursor:Cursor|null,
  upperBound:int|null}`. В первом запросе cursor/upperBound=null: сервер выбирает
  последние limit записей после начала сессии, возвращает первую страницу по
  возрастанию sequence. Продолжения передают nextCursor и неизменный upperBound;
  limit — оставшееся количество. Result как у pollEvents плюс sessionStart:int,
  windowLimited:bool. Потеря необходимого интервала между страницами — ошибка,
  частичный успешный RecentEvents запрещён. Первоначально уже истёкшая история
  допустима как доступное окно с windowLimited=true.
* events.clearPending params `{eventType:string|null,world:string}`; result
  `{cursor:Cursor}`. Сервер не хранит изменяемые курсоры чтения клиента.

Курсоры проверяются по epoch, UUID мира и началу сессии; будущие курсоры запрещены.
Для явно выбранного другого мира база фиксируется при первом обращении к нему.
Смена мира в withContext не меняет уже созданные подписки. Курсоры ведутся по
паре (тип, UUID мира), фасады одного мира разделяют их.

## Ошибки и границы

* -32044 INVALID_EVENT_TYPE → InvalidEventTypeError.
* -32045 SUBSCRIPTION_NOT_FOUND → SubscriptionNotFoundError.
* -32046 EVENT_HISTORY_LOST → EventHistoryLostError.
* -32047 EVENT_QUEUE_OVERFLOW → EventOverflowError.

Ошибка истории outcome=not-applied; data дополнительно может содержать reason
(retention/capture-overflow), availableFrom, tail, eventType. Неизвестные поля и
произвольный текст сервера не попадают в диагностические сообщения Python.
Потеря истории не ломает live и не меняет курсор. Нужен явный clearPending для
продолжения после потерянного интервала.

Журнал: максимум 4096 записей, 4 MiB и 2400 серверных тиков на мир; максимум
8 одновременно удерживаемых миров. Неиспользуемые журналы освобождаются.
Асинхронный вход: 1024 записи, обработка до 128 за тик и бюджет 2 ms.
Текст ограничен 4096 Unicode code points с truncated=true при обрезке.
Потеря до назначения sequence отмечается отдельной capture-loss границей;
непрерывность sequence сама по себе не доказывает отсутствие потерь.
Не более 32 подписок на сессию и 512 живых кадров в каждой очереди сервер/Python.
Страница ограничена 32768 байтами записей; общий кадр не больше 65536 байт.
Очередь обычных RPC отделена от live. Уведомление потери имеет отдельное
ограниченное место и не теряется в переполненной очереди live. Частично
записанный кадр всегда заканчивается до начала любого следующего кадра.
Reactor закрепляет кадр в момент выбора output head; даже если его первый байт
ещё не записан в сокет, переключения на другой кадр уже нет. Поэтому новый RPC
может подождать один уже выбранный live-кадр, затем получает приоритет над live.

AsyncChatEvent наблюдается MONITOR, отменённые события пропускаются. Async
listener копирует сообщение и неизменяемую идентичность; Bukkit-операции и
нормализация выполняются в основном потоке. world/serverTick обозначают точку
нормализации, не точное время прихода сетевого пакета. postToChat не создаёт
chat.message. Обработчики Python не могут синхронно отменить серверное событие.

Запуск Minebridge 0.3.1
======================

Нужны Paper 26.2 с Java 25 и Python 3.11+ на компьютерах учеников. Проверяемая
сборка сервера — Paper 26.2 build 133. Поддержка других сборок отдельно не
подтверждена. Локальные файлы — `dist/v0.3.1/`. После публикации загрузите
JAR и wheel из [GitHub Releases](https://github.com/ilyak163rus/minebridge/releases).

1. Установите плагин
-------------------

Остановите сервер. Уберите старые JAR Minebridge из папки `plugins` и скопируйте
туда `minebridge-paper-0.3.1.jar`.
В `plugins` должен остаться один JAR Minebridge. Перезапустите сервер, чтобы
создался `plugins/Minebridge/config.yml`, затем остановите его для изменения
конфига. Если файл уже есть, обновите его без удаления папки плагина.
Тестовый observer для занятий не нужен.

Для сервера с адресом `192.168.0.200`:

```yaml
listenAddress: '192.168.0.200'
port: 4712
authEnabled: false
token: ''
```

`listenAddress` — числовой IP интерфейса **серверного** компьютера. Для всех
его IPv4-интерфейсов допустим `0.0.0.0`; в Python при этом указывайте
`192.168.0.200`, а не `0.0.0.0`. Значение `127.0.0.1` по умолчанию подходит,
когда Python работает на самом серверном компьютере. Разрешите входящие
подключения на выбранный TCP-порт в брандмауэре.

В этом примере Minebridge использует 4712, чтобы оставить RaspberryJuice его
прежний 4711. Порт должен совпадать в config и Python. Minebridge не подключается к RaspberryJuice:
это разные плагины с разными протоколами.

Имя мира не нужно: выбирается основной Overworld независимо от названия папки.
После пересоздания мира достаточно обычного перезапуска сервера; менять имя
в конфиге не требуется. Старое поле `defaultWorld` принимается, но игнорируется.
Токен не нужен при `authEnabled: false`; старое значение `token` само по себе
не включает авторизацию.

Запустите сервер. В логе должно появиться сообщение Minebridge с текстом
`TCP listener ready on port 4712` (или вашим портом). Если его нет, проверьте
предшествующие сообщения Minebridge до запуска Python.

2. Установите Python-пакет
-------------------------

Из корня этого проекта в PowerShell:

```powershell
python -m venv .venv-lesson
.\.venv-lesson\Scripts\python.exe -m pip install --upgrade --force-reinstall --no-deps .\dist\v0.3.1\minebridge-0.3.1-py3-none-any.whl
```

Если окружение уже создано, используйте его `python.exe`. На компьютере ученика
достаточно скопировать wheel и заменить путь в команде его фактическим путём.
Пакет не публиковался в PyPI, поэтому устанавливайте переданный файл.
Плагин и wheel обновляйте вместе. Учебному серверу нужны только итоговый
Minebridge JAR и config; observer и другие test-fixture плагины не нужны.

В VS Code выполните **Python: Select Interpreter** и выберите тот же
`python.exe`, которым установили wheel. Расширения Python и Pylance обеспечивают
подсказки для методов, моделей, `block.`, `items.`, `effects.`, `entity.` и
`selector.`, `events.`, `slots.`, `gamemode.`, `weather.`, `gamerule.` и
`damageCause.`. Импорт и подсказки доступны без работающего сервера.

Проверка установленной версии:

```powershell
.\.venv-lesson\Scripts\python.exe -c "import minebridge; print(minebridge.__version__); print(minebridge.__file__)"
```

Ожидается `0.3.1` и путь к `site-packages` выбранного окружения.

Для просмотра действий конкретной программы задайте `logging=True`:

```python
mc = Minecraft.create("192.168.0.200", 4712, logging=True)
```

Действия этого подключения появятся в консоли сервера и `logs/latest.log`:
сессия, номер запроса, метод, параметры, получение и завершение/ошибка.
По умолчанию журнал выключен; `received` ещё не означает выполнение.
Для нового параметра обновите и JAR, и wheel.

Короткая программа теперь ждёт команды при обычном выходе из Python.
Явный `close()` в примерах полезен для обработки ошибок в коде. Ошибка,
обнаруженная только обработчиком выхода, печатается в stderr без изменения
кода завершения. Принудительное завершение процесса не ждёт команды.

3. Поставьте и прочитайте блоки
------------------------------

Выберите свою свободную площадку и замените координаты. Все координаты
абсолютные. Для операций с блоками подходить к площадке игроком не требуется:
нужные чанки сервер загружает и при необходимости генерирует сам.

```python
from minebridge.minecraft import Minecraft
from minebridge import block

mc = Minecraft.create("192.168.0.200", 4712)
try:
    mc.setBlocks(0, 80, 0, 9, 80, 9, block.COBBLESTONE)
    for x in range(10):
        mc.setBlock(x, 81, 0, block.OAK_LOG.withStates(axis="x"))

    mc.flush()
    print("Старый ID:", mc.getBlock(0, 80, 0))  # 4
    print("Координаты → ID:", mc.getBlocks(0, 80, 0, 1, 80, 1))
    print("Блок со свойствами:", mc.blocks.getBlock(0, 81, 0))
    mc.postToChat("Площадка построена из Python!")
finally:
    mc.close()
```

По умолчанию используется `writeMode="buffered"`. `setBlock`, `setBlocks` и
`postToChat` отправляются без ожидания каждого ответа. `flush()` ждёт предыдущие
записи; чтение, телепортация, выдача, эффекты и создание сущностей также ждут
своего результата и предыдущих записей. `close()` дожидается записей, затем
закрывает соединение даже при ошибке. Если нужно ждать каждую запись:

```python
mc = Minecraft.create("192.168.0.200", 4712, writeMode="sync")
```

Числовые ID сохранены для проверенного старого набора. Новые блоки могут не
иметь однозначного старого ID — читайте их через `mc.blocks.getBlock/getBlocks`.
Они возвращают `BlockSpec` с `.key` и `.states`.

4. Проверьте SELF, предметы и эффекты
-----------------------------------

Войдите игроком в основной Overworld. В `player` укажите его **текущий** ник,
который виден на сервере в этом занятии. Компьютер и IP ученика на выбор SELF
не влияют. Простое подключение по двум параметрам продолжает работать без SELF.

```python
from minebridge import Minecraft, effects, items, selector
from minebridge.models import ItemStack

mc = Minecraft.create("192.168.0.200", 4712, player="CurrentNick")
try:
    print("Игроки:", mc.players.list())
    print("ID:", mc.getPlayerEntityId("CurrentNick"))
    print("Позиция:", mc.players.getPos(selector.SELF))

    reward = ItemStack(items.IRON_SWORD, name="Меч строителя")
    result = mc.players.giveItem(selector.SELF, reward)
    for target in result.targets:
        print("Выдано:", target.given, "Осталось:", target.leftovers)

    print(mc.effects.add(selector.SELF, effects.SPEED, 30, 2))  # 30 секунд, уровень 2
finally:
    mc.close()
```

При заполненном инвентаре остаток находится в `result.targets[i].leftovers`.
`overflow="drop"` явно выбрасывает непоместившееся рядом с получателем.
Поиск ID сам не назначает SELF. Для отдельной привязки можно вызвать
`other = mc.withContext(player="OtherNick")`: исходный фасад не меняется,
но соединение общее, поэтому закрывайте его один раз после всей работы.

Для всех разделов вместе запустите [пример занятия](../examples/v02_lesson.py):

```powershell
.\.venv-lesson\Scripts\python.exe .\examples\v02_lesson.py CurrentNick --host 192.168.0.200 --port 4712
```

Пример строит маленькую площадку рядом с игроком, читает блоки, телепортирует
его на площадку, выдаёт награду, накладывает эффект, создаёт корову и предмет.
Создание настоящей молнии включается отдельно параметром `--lightning`.
Дальнейшие команды и особенности специальных сущностей описаны в
[справочнике API 0.2](API_V0_2.ru.md).

5. Обработчик чата и точный слот
------------------------------

```python
from minebridge import Minecraft, events, items, slots, selector
from minebridge.models import ChatEvent

with Minecraft.create("192.168.0.200", 4712, player="CurrentNick") as mc:
    inventory = mc.inventories.ofPlayer(selector.SELF)
    inventory.setItem(slots.OFF_HAND, items.SHIELD, 1)

    def on_chat(event: ChatEvent) -> None:
        if event.message == "!reward":
            target_inventory = mc.inventories.ofPlayer(event.player)
            target_inventory.setItem(0, items.EMERALD, 3)
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

Напишите в игре `!reward`: слот 0 автора сообщения будет **заменён** тремя
изумрудами. `!stop` завершит цикл. Функции выполняются в потоке, вызвавшем run;
синхронные команды внутри обработчика разрешены. postToChat не вызывает
CHAT_MESSAGE повторно. Python наблюдает событие и не отменяет его на сервере.
SELF остаётся явно выбранным игроком; к автору обращайтесь через event.player.

```python
from minebridge import Minecraft, items

with Minecraft.create("192.168.0.200", 4712) as mc:
    chest = mc.inventories.ofBlock(10, 80, 10)  # здесь уже должен быть сундук
    chest.setItem(0, items.DIAMOND, 16)
    print(chest.getContents())
    chest.clear(0)

    for event in mc.events.pollChatPosts():
        print(event.player.name, event.message)
```

По умолчанию адресуется физическая половина на 27 слотов; `combined=True`
выбирает общий сундук на 27/54 слота. Пустые слоты — None. ItemView содержит
известные поля и флаги hasAdditionalData/truncated; setter не принимает этот
снимок для обратного копирования всех компонентов предмета.
История pollEvents/getRecent независима от callbacks и ограничена RAM-окном.

Управление 0.3: `mc.setPos(targets, x, y, z)`, `mc.players.setGameMode(...)`,
health/food, remove/clear эффектов, `mc.worlds` time/weather/gamerules.
Подробности всех 14 событий, фильтров и слотов — [API 0.3](API_V0_3.ru.md).
[Пример обработчиков](../examples/v03_game_events.py),
[пример слотов](../examples/v03_inventory_slots.py).

В [общем примере 0.3](../examples/v03_lesson.py) рядом с игроком создаются
площадка и сундук. Выберите свободное место в основном Overworld:

```powershell
.\.venv-lesson\Scripts\python.exe .\examples\v03_lesson.py CurrentNick --host 192.168.0.200 --port 4712
```

Пример меняет режим игрока на creative и запускает обработчики. `!reward`
заменяет слот 0, `!recent` печатает последние сообщения, `!stop` завершает цикл.
Ломание булыжника в пределах площадки выдаёт алмаз; вход в лаву печатается в Python.

Если появилась ошибка
--------------------

| Ошибка или симптом | Что проверить |
|---|---|
| `ConnectionError` | Готовность Minebridge в логе, адрес `listenAddress`, IP в Python, порт и брандмауэр |
| Таймаут, а в логе исключение RaspberryJuice | Python попал на порт RaspberryJuice; назначьте Minebridge отдельный порт |
| `AuthenticationError` | При `authEnabled: true` передайте правильный токен; для учебного запуска можно оставить `false` |
| `PlayerNotFoundError` | Игрок с указанным текущим ником должен быть онлайн |
| `PeacefulSpawnError` | Мир назначения имеет мирную сложность, запрещающую этот тип сущности |
| `InventoryNotFoundError` | На координатах нужен обычный или trapped chest |
| `InventoryChangedError` | Получите новую ofBlock-ссылку после изменения layout |
| `InvalidItemAmountError` | Количество не должно превышать native максимум предмета/слота |
| `EventOverflowError` | Удалите повреждённую подписку, проверьте состояние и подпишитесь заново |
| `EventHistoryLostError` | Непрочитанное окно истории истекло; clearPending явно начнёт чтение с текущего хвоста |
| `MissingContextError` | Для SELF и пространственных селекторов задайте `player` или `withContext(player=...)` |
| `ContextWorldMismatchError` | Для пространственного селектора связанный игрок должен быть в мире соединения |
| `UnsupportedLegacyBlockError` при чтении | Используйте `mc.blocks.getBlock/getBlocks` для современного блока или неоднозначного старого ID |
| `CoordinateOutOfBoundsError` | Высоту мира и WorldBorder |
| `ChunkLoadError` | Сообщения Paper об ошибке загрузки/генерации чанка |
| `RegionBusyError` | Другой запрос Minebridge сейчас меняет пересекающуюся область; дождитесь завершения стройки |

В buffered-режиме ошибка сервера может появиться при следующей записи, чтении,
`flush()` или `close()`. Поля `.method`, `.request_id`, `.code`, `.outcome`
относятся к исходной операции; `.failures` содержит ошибки текущего барьера.
Если при обрыве `.outcome == "unknown"`, операция могла уже выполниться.
Автоматического повторения нет. Подтверждение операции означает выполнение
сервером, а не сохранение мира на диск.

Необязательная авторизация: `authEnabled: true` и непустой `token` в конфиге;
в Python — `token="..."` или переменная `MINEBRIDGE_TOKEN`.
Точные правила поведения — в [контракте 0.2](contracts/V0_2_CONTRACT.ru.md).

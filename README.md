Minebridge 0.3.1 — Python ↔ Minecraft Paper
==========================================

Библиотека и плагин для управления Minecraft из Python. Сохраняются знакомые
`Minecraft.create(ip, port)`, `setBlock`, `setBlocks`, числовые ID и `block.COBBLESTONE`.
Доступны чтение блоков и состояний, загрузка чанков, игроки и селекторы,
телепортация, чат, предметы, эффекты и создание сущностей.

В 0.3 добавлены 14 типов событий с обработчиками, независимым чтением истории
и фильтрами; точные слоты сундуков и игроков; режим игры, здоровье и сытость;
время, погода и gamerules. `setPos` принимает селектор, а
`effects.add(selector.SELF, effects.SPEED, 100, 200)` означает 100 секунд, уровень 200.

В 0.3.1 ускорен `setBlocks` до 32 768 блоков при готовых чанках, добавлены
`selector.playerByName("YourNick")` и понятный `PeacefulSpawnError` при попытке
создать запрещённого мирной сложностью моба. [Изменения](docs/releases/0.3.1.ru.md).
В локальной приёмке куб 27 000 блоков с flush: 0.0665 с вместо 5.286 с;
[условия и проверки](docs/reports/V0_3_1.ru.md).

Готовые локальные файлы находятся в `dist/v0.3.1/`. После публикации комплект
доступен в [GitHub Releases](https://github.com/ilyak163rus/minebridge/releases):

- `minebridge-paper-0.3.1.jar` — в `plugins` сервера.
- `minebridge-0.3.1-py3-none-any.whl` — установить в Python учеников.
- [Быстрый запуск](docs/QUICKSTART.ru.md) — конфигурация, установка и первые программы.
- [API 0.3](docs/API_V0_3.ru.md) и [базовый API 0.2](docs/API_V0_2.ru.md).
- [Общий пример занятия](examples/v03_lesson.py), [игровые события](examples/v03_game_events.py), [слоты](examples/v03_inventory_slots.py).
- [Документация](docs/README.md), [публикация GitHub/PyPI](docs/PUBLISHING.ru.md), [изменения](CHANGELOG.md).

Нужны Python 3.11+ и Paper 26.2 с Java 25. Закреплённая среда проверок — Paper
26.2 build 133; совместимость других сборок отдельно не подтверждена. В PyPI
пакет не публиковался. Плагин и Python-пакет обновляйте вместе.

```powershell
python -m pip install --upgrade --force-reinstall --no-deps .\dist\v0.3.1\minebridge-0.3.1-py3-none-any.whl
```

```python
from minebridge import Minecraft, block

with Minecraft.create("192.168.0.200", 4712) as mc:
    mc.setBlocks(0, 80, 0, 9, 80, 9, block.COBBLESTONE)
    for x in range(10):
        mc.setBlock(x, 81, 0, block.OAK_LOG.withStates(axis="x"))
    mc.flush()
    print(mc.getBlock(0, 80, 0))        # 4
    print(mc.blocks.getBlock(0, 81, 0))  # BlockSpec со всеми состояниями
    mc.postToChat("Площадка готова!")
```

Адрес и координаты замените своими. Для LAN укажите серверный IP в
`listenAddress` конфига плагина; по умолчанию он слушает `127.0.0.1:4711`.
В примере выбран порт 4712, чтобы отделить Minebridge от RaspberryJuice;
он должен совпадать в конфиге и Python. Токен для учебного запуска не требуется,
основной Overworld выбирается автоматически независимо от имени папки.

По умолчанию `writeMode="buffered"`: установка блоков и чат отправляются без
ожидания каждого ответа. `flush`, чтение и методы с результатом дожидаются
предыдущих записей; `close` и обычный выход Python тоже ждут их.
Ожидание каждой записи включается через `writeMode="sync"`.
`logging=True` в `create` включает серверный журнал действий этого соединения.
Для SELF задайте текущий онлайн-ник: `Minecraft.create(ip, port, player="CurrentNick")`.
Для явного выбора по нику используйте `selector.playerByName("YourNick")`;
регистр ника важен. Примеры выдачи и эффектов — в [дополнении API](docs/releases/0.3.1.ru.md).

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("192.168.0.200", 4712) as mc:
    def on_chat(event: ChatEvent) -> None:
        if event.message == "!reward":
            mc.inventories.ofPlayer(event.player).setItem(0, items.EMERALD, 3)
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

`!reward` заменяет слот 0 автора сообщения тремя изумрудами. Обработчики
выполняются в потоке `events.run`; команды внутри них разрешены. Python
наблюдает серверные события и не отменяет их синхронно. Переполнение очереди
и потеря RAM-истории сообщаются отдельными исключениями.

Каталоги содержат 1196 блоков, 1537 предметов, 40 эффектов и 158 типов сущностей.
Константы и параметры типизированы для VS Code/Pylance. Числовой API блоков
покрывает 361 проверенную пару ID/data для 110 ID; современное чтение возвращает
BlockSpec. Полная совместимость mcpi не заявляется. Scoreboard, title/actionbar,
GUI и запись произвольных компонентов предметов остаются будущими функциями.

Документы разработки:

- [План 0.3](docs/IMPLEMENTATION_PLAN_V0_3.ru.md), [контракт](docs/contracts/V0_3_CONTRACT.ru.md), [события](docs/EVENTS_V0_3.ru.md).
- [Архитектура](ARCHITECTURE.ru.md), [команды разработки](docs/DEVELOPMENT.ru.md).
- [Интеграционный стенд](integration/README.md), [среда](docs/ENVIRONMENT_LOCK.ru.md).
- Отчёты 0.3: [I01](docs/reports/V0_3_I01.ru.md), [I02](docs/reports/V0_3_I02.ru.md), [I03](docs/reports/V0_3_I03.ru.md), [I04](docs/reports/V0_3_I04.ru.md), [I05](docs/reports/V0_3_I05.ru.md).
- История: [0.2.1](docs/reports/V0_2_1.ru.md), [план 0.2](docs/IMPLEMENTATION_PLAN_V0_2.ru.md), [контракт 0.2](docs/contracts/V0_2_CONTRACT.ru.md), [план T01–T10](docs/IMPLEMENTATION_PLAN.ru.md).

Артефакты прежних версий сохраняются локально для воспроизводимости. `dist/`
и интеграционные журналы исключены из Git; бинарные файлы прикладываются к Release.
Лицензия проекта — [MIT](LICENSE), [компоненты третьих сторон](THIRD_PARTY_NOTICES.md).
Порядок сборки и участия в разработке — в [CONTRIBUTING](CONTRIBUTING.md).

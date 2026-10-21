Minebridge 0.1: технический прототип
===================================

Python API для Paper: подключение, установка блока и типизированные значения.
Python 3.11+, зависимостей времени выполнения нет.
Имя пакета рабочее; публикация в PyPI не выполнялась.

Перед подключением задайте MINEBRIDGE_TOKEN токеном урока. На сервере нужен
плагин Minebridge и доступный настроенный мир. Позиции должны находиться в
загруженном чанке; выберите их для своего стенда.

```python
from minebridge.minecraft import Minecraft
from minebridge import block

mc = Minecraft.create("localhost", 4711)
try:
    mc.setBlock(0, 80, 0, 4)
    mc.blocks.setBlock(1, 80, 0, block.COBBLESTONE)
finally:
    mc.close()
```

create возвращает объект после успешного hello, оба setBlock возвращают None
после подтверждения выполнения сервером. token=None берёт MINEBRIDGE_TOKEN;
world=None выбирает настроенный мир, coordinates=None — absolute. Можно явно
передать token/world/timeout/coordinates как keyword-only параметры create.
Импорт и подсказки IDE не подключаются к серверу. Экспорт from minebridge import
Minecraft указывает на тот же класс.

Офлайн-нормализация по тем же правилам доступна отдельно:

```python
from minebridge import block
from minebridge.models import normalize_block, normalize_position

assert block.COBBLESTONE.id == 4
assert normalize_block(4) == normalize_block(block.COBBLESTONE)
assert normalize_block(4).key == "minecraft:cobblestone"
assert normalize_position(1.9, -0.2, 0) == (1, -1, 0)
```

Поддерживаются legacy-пары (0,0), (1,0), (4,0), современные namespaced-ключи
без состояний и неизменяемые BlockSpec/LegacyBlock. Действительное наличие
современного блока будет проверять сервер; офлайн-пакет проверяет синтаксис.
Подсказки после `block.` доступны без Minecraft.

Корневой setBlock делегирует mc.blocks.setBlock: нормализаторы и TCP-соединение
общие. Ошибочный локальный аргумент отвергается до RPC. Сервер проверяет материал,
мир, высоту, border и loaded-состояние. При timeout/обрыве после отправки мутации
outcome может быть unknown; автоматических повторов/reconnect нет. close
идемпотентен и не откатывает выполненную запись.

Этот subset не включает setBlocks, getPlayerEntityId, getBlock, игроков/SELF,
селекторы или полную совместимость mcpi. Тестовый observer и локальный gate
собираются отдельно от пользовательского Python API. Область приёмки и
проверенные версии описаны в документах проекта и отчётах этапов.
Модули с префиксом _ и транспорт не относятся к публичному учебному API.


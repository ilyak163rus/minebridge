Контракт Minebridge 0.3 — I01
===========================

26 октября 2026 года. Зафиксированные решения для реализации I01 из
[плана](../IMPLEMENTATION_PLAN_V0_3.ru.md). Документ описывает контракт;
завершённость проверок отмечается отдельным отчётом. События, история и
inventory API пока остаются проектом последующих итераций, не capabilities I01.
Исторический [контракт 0.2](V0_2_CONTRACT.ru.md) не меняется задним числом.

I01 принята 27 октября 2026 года: [отчёт и фактические проверки](../reports/V0_3_I01.ru.md).
Версия исходников — 0.3.0.dev1, без установочной поставки до I05.

Совместимость
-------------

Paper 26.2 build 133, Java 25, Python 3.11+. JSON-RPC/NDJSON protocol 2.0,
minor=0, прежние ограничения кадра/глубины/ID, FIFO и буферизация. Нет повторов
мутаций при неизвестном результате. Token/world необязательны, основной мир
выбирается по ключу Overworld, logging=False. Нормальный выход Python 0.2.1
ожидает записи. Поставки JAR/wheel в I01 нет; build/ JAR только для стенда.

Все новые remote-методы синхронны в обоих writeMode и являются барьером ранее
отправленных записей. Новая capability равна имени RPC. Новый Python проверяет
её до отправки неподдержанной команды. Позиционные эффекты и setPos используют
старые RPC и работают с прежним совместимым плагином. Старый клиент на новом
плагине не получает event frames; в I01 события вообще не отправляются.

Позиционные эффекты и setPos
--------------------------

```text
mc.effects.add(targets,effect,duration,level=1,*,particles=True) -> TargetResult
mc.setPos(targets,x,y,z,*,world=None) -> TargetResult
mc.players.setPos(targets,x,y,z,*,world=None) -> TargetResult
```

Подтверждённый пользователем порядок: длительность в игровых секундах, затем
уровень. `add(...,100,200)` — 100 секунд/уровень 200. Прежний вызов с
duration=.../level=... эквивалентен. Level 1..256, duration конечная положительная
и укладывается в int32 тиков с прежним округлением ceil(duration*20).
Wire effects.add не меняется. Оба setPos делегируют Players.teleport, сохраняя
дроби, world, selector, TargetResult; второй телепорт-движок не появляется.

Игроки
------

```text
players.getGameMode(target) -> GameMode
players.setGameMode(targets,mode) -> TargetResult
players.getHealth(target) -> float
players.setHealth(targets,value) -> TargetResult
players.getFoodLevel(target) -> int
players.setFoodLevel(targets,value) -> TargetResult
```

Getter принимает тот же TargetSpec, но требует ровно одного онлайн-игрока.
Setter разрешает цели один раз и проверяет весь набор до изменений. Фактический
максимум HP проверяется для каждого игрока до первой мутации. HP — очки
здоровья, не сердечки; 0 может привести к смерти. Сытость — целое 0..20.
Bool вместо числа не допускается. Режимы — GameMode и статические
gamemode.SURVIVAL/CREATIVE/ADVENTURE/SPECTATOR; wire lowercase.
Minecraft хранит HP с float32-точностью: значение нормализуется до проверки
максимума и readback. Положительное число, округляющееся в ноль, отклоняется
до мутации; скрытого ограничения к максимуму или обнуления здоровья нет.

Bulk setters исполняются существующим GameplayJobManager частями с общим
бюджетом, FIFO и heartbeat. Результат — прежний matched/applied/targets по UUID.
Void setter Paper не доказывает успех: после вызова сверяется фактическое
значение. Отмена режима даёт per-target GAME_MODE_REJECTED; несовпадение
значения — PLAYER_VALUE_REJECTED; исчезновение — PLAYER_NOT_FOUND.
Успешные другие цели не откатываются; автоматического повтора нет.

Снятие эффектов
---------------

```text
effects.remove(targets,effect) -> TargetResult
effects.clear(targets) -> TargetResult
```

Targets — живые сущности, как для add; весь набор предвалидируется.
Отсутствующий эффект и уже пустой набор считаются успешно обработанными.
Неизвестный effect key — INVALID_EFFECT до мутаций. Исполнение и размер ответа
ограничены прежним gameplay job-механизмом. Снятие, отменённое другим плагином,
проверяется фактическим состоянием и отражается per-target отказом.

Миры и правила
--------------

```text
worlds.getTime(*,world=None) -> int
worlds.setTime(time,*,world=None) -> None
worlds.getWeather(*,world=None) -> Weather
worlds.setWeather(weather,*,world=None) -> None
worlds.getGameRule(rule,*,world=None) -> bool | int
worlds.setGameRule(rule,value,*,world=None) -> None
```

world=None на клиенте передаёт выбранное имя сессии. На сервере совпадающее
имя/ключ сессии обязательно сверяется с её UUID; старое имя не переключает
сессию на пересозданный мир. Явный другой загруженный мир разрешается по
имени/ключу. Никакого обязательного имени в config.yml не добавляется.

Время — целое 0..23999 тиков суток. Следуем World.setTime; абсолютный день
может продвинуться при установке меньшего времени суток. setFullTime не входит.
Погода — Weather с константами weather.CLEAR/RAIN/THUNDER. Setter задаёт
storm/thundering согласованно и проверяет результат; обычные циклы мира могут
позднее изменить погоду/время. Семантика не содержит бессрочного scheduler.

GameRuleKey[T] неизменяем, содержит key, valueType и defaultValue. Каталог
экспортируется из Registry.GAME_RULE закреплённого API133, константы статические,
generic bool/int даёт подсказки IDE без подключения. Ключ на wire равен
canonical GameRule.getKey().toString(). Совместимые старые имена констант
разрешены только при идентичности canonical-объекту; преобразующие тип/смысл
legacy wrappers исключены с явным объяснением, а не скрытой инверсией значения.
Тип bool/int проверяется строго; int — int32. API не предоставляет универсальных
min/max: backend использует корректную проверку конкретного правила и сверяет
значение после установки. Неизвестный ключ — INVALID_GAME_RULE, неподходящее
значение — INVALID_RULE_VALUE. Тип/ключ проверяются до изменения.

При отклонённом setter до изменения outcome=not-applied. Если setter уже
начался, но ожидаемое состояние не подтверждено/выброшено исключение,
outcome=unknown: скрытого rollback или повторной попытки нет.

Публичные сведения и context manager
-----------------------------------

server.getInfo() возвращает неизменяемый ConnectionInfo из успешного hello:
sessionId, protocolMajor/minor, pluginVersion, serverVersion, метаданные мира,
writeMode, logging и capabilities. server.getCapabilities() — tuple[str,...].
Оба вызова локальные, без RPC и обещания текущих TPS/онлайн-состояния мира.
withContext сохраняет эти сведения и общий транспорт.

Minecraft поддерживает with. На выходе вызывает close с ожиданием записей.
Если тело уже выбросило исключение, ошибка close не скрывает исходную:
добавляется note. Без исходного исключения ошибка close выходит как обычно.
Автоматический выход из обычного скрипта сохраняется; неявного event loop нет.

Wire I01
--------

Общий selection: `{world:string, executor:UUID|null, targets:TargetSpec}`.
Те же правила селекторов/SELF/числа целей, что в 0.2.

| RPC | Параметры сверх selection | Result |
|---|---|---|
| players.getGameMode | — | `{mode:"survival"|"creative"|"adventure"|"spectator"}` |
| players.setGameMode | mode:string | TargetResult |
| players.getHealth / getFoodLevel | — | `{value:number}` |
| players.setHealth / setFoodLevel | value:number | TargetResult |
| effects.remove | effect:{key:string} | TargetResult |
| effects.clear | — | TargetResult |

| RPC | Params | Result |
|---|---|---|
| worlds.getTime | world | `{time:int}` |
| worlds.setTime | world,time | `{applied:true}` |
| worlds.getWeather | world | `{weather:string}` |
| worlds.setWeather | world,weather | `{applied:true}` |
| worlds.getGameRule | world,rule | `{rule:string,value:bool|int}` |
| worlds.setGameRule | world,rule,value | `{applied:true}` |

Неверная форма/неожиданные ключи — INVALID_PARAMS. Доменные коды:

| JSON-RPC | Code | Python |
|---|---|---|
| -32038 | INVALID_GAME_MODE | InvalidGameModeError |
| -32039 | INVALID_GAME_RULE | InvalidGameRuleError |
| -32040 | INVALID_RULE_VALUE | InvalidRuleValueError |
| -32041 | INVALID_PLAYER_VALUE | InvalidPlayerValueError |
| -32042 | INVALID_WEATHER | InvalidWeatherError |
| -32043 | WORLD_CHANGE_REJECTED | WorldChangeRejectedError |

Чужие сообщения исключений/параметры токена не выходят в диагностику.
SessionActivityLog поддерживает новые методы с прежним opt-in logging=True.

Проверка завершения I01
----------------------

Согласованные Python/Java codec fixtures, прежние suites и точечные проверки
новых операций. Один компактный Paper-прогон из исходников: два игрока,
селекторы, режим/HP/сытость, эффекты remove/clear, time/weather/gamerules и
фактические чтения. Отмена режима/эффекта тестовым listener и предвалидация
всех целей должны отличаться от успешного вызова. Неверное/неизменённое
значение не выдаётся за applied. Pinned catalog provenance фиксируется;
UI/LAN/полный класс отдельно не объявляются проверенными.

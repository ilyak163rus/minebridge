"""Give a diamond for !diamond; stop with !stop."""

from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent


def main() -> None:
    with Minecraft.create("localhost", 4711) as mc:
        def on_chat(event: ChatEvent) -> None:
            print(event.player.name, event.message)
            if event.message == "!diamond":
                # The actor is explicit: SELF keeps its connection context.
                result = mc.players.giveItem(event.player, items.DIAMOND, 1)
                print(result)
            elif event.message == "!stop":
                mc.events.stop()

        subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
        try:
            # This thread executes on_chat; Ctrl+C also reaches this thread.
            mc.events.run()
        except KeyboardInterrupt:
            pass
        finally:
            subscription.unsubscribe()

        # History remains independent of the live callbacks above.
        for event in mc.events.getRecent(events.CHAT_MESSAGE, limit=10):
            print(event.player.name, event.message)


if __name__ == "__main__":
    main()

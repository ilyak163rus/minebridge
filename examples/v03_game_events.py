"""I03: chat commands, a block reward and lava-contact notifications."""

from minebridge import Minecraft, block, events, items
from minebridge.models import BlockBreakEvent, ChatEvent, LavaEnterEvent, Region


def main() -> None:
    with Minecraft.create("192.168.0.200", 4712) as mc:
        world = mc.server.getInfo().world
        arena = Region(world.uuid, (0, -64, 0), (100, 319, 100))

        def on_chat(event: ChatEvent) -> None:
            if event.message == "!stop":
                mc.events.stop()

        def on_break(event: BlockBreakEvent) -> None:
            print(event.player.name, event.position, event.block)
            mc.players.giveItem(event.player, items.DIAMOND, 1)

        def on_lava(event: LavaEnterEvent) -> None:
            # This observes contact; it does not cancel damage or pause the game.
            mc.postToChat(f"{event.player.name}: lava contact at {event.position}")

        subscriptions = [
            mc.events.subscribe(events.CHAT_MESSAGE, on_chat),
            mc.events.subscribe(events.BLOCK_BREAK, on_break,
                                region=arena, blocks=block.COBBLESTONE),
            mc.events.subscribe(events.PLAYER_ENTER_LAVA, on_lava),
        ]
        try:
            mc.events.run()
        except KeyboardInterrupt:
            pass
        finally:
            for subscription in subscriptions:
                subscription.unsubscribe()

        for hit in mc.events.pollBlockHits():
            print(hit.player.name, hit.position, hit.action, hit.hand)
        for shot in mc.events.pollProjectileShots():
            print(shot.projectile.uuid, shot.shooter, shot.velocity)


if __name__ == "__main__":
    main()

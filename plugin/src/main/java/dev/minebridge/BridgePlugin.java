package dev.minebridge;

import dev.minebridge.config.BridgeConfig;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.PaperBlockBackend;
import dev.minebridge.players.PaperPlayerBackend;
import dev.minebridge.players.PlayerService;
import dev.minebridge.gameplay.GameplayService;
import dev.minebridge.gameplay.PaperGameplayBackend;
import dev.minebridge.execution.ExecutionLimits;
import dev.minebridge.execution.GameExecutor;
import dev.minebridge.execution.OperationTrace;
import dev.minebridge.protocol.RequestRouter;
import dev.minebridge.session.SessionManager;
import dev.minebridge.session.WorldContext;
import dev.minebridge.transport.TcpServer;
import dev.minebridge.transport.TransportLimits;
import dev.minebridge.session.Session;
import dev.minebridge.session.SessionActivityLog;
import dev.minebridge.testing.TestControl;
import dev.minebridge.worlds.WorldsService;
import dev.minebridge.worlds.PaperWorldsBackend;
import dev.minebridge.events.EventsService;
import dev.minebridge.events.PaperChatListener;
import dev.minebridge.events.PaperGameListener;
import dev.minebridge.inventories.InventoryService;
import dev.minebridge.inventories.PaperInventoryBackend;
import java.io.File;
import java.io.IOException;
import net.kyori.adventure.key.Key;
import org.bukkit.configuration.InvalidConfigurationException;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.plugin.IllegalPluginAccessException;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.plugin.ServicePriority;

/** Bounded TCP transport and optionally authenticated handshake on Paper's server thread. */
public final class BridgePlugin extends JavaPlugin {
    private BridgeConfig bridgeConfig;
    private volatile TcpServer tcpServer;
    private SessionManager sessions;
    private GameExecutor gameExecutor;
    private BukkitTask dispatchTask;
    private OperationTrace operationTrace;
    private TestControl testControl;
    private RequestRouter requestRouter;
    private SessionActivityLog activityLog;
    private BukkitTask activityLogTask;
    private EventsService events;
    private PaperChatListener chatListener;
    private PaperGameListener gameListener;

    @Override
    public void onEnable() {
        bridgeConfig = null;
        try {
            saveDefaultConfig();
        } catch (IllegalArgumentException | IllegalStateException exception) {
            disableWithMessage("Cannot prepare config.yml; check the plugin data directory.");
            return;
        }

        // Read the actual file without applying defaults or letting a YAML parser log
        // source snippets containing the token through JavaPlugin#getConfig().
        YamlConfiguration rawConfig = new YamlConfiguration();
        try {
            rawConfig.load(new File(getDataFolder(), "config.yml"));
        } catch (IOException | InvalidConfigurationException exception) {
            disableWithMessage("Cannot read config.yml; check file access and YAML syntax.");
            return;
        }

        BridgeConfig candidate;
        try {
            candidate = BridgeConfig.from(rawConfig.getValues(false));
        } catch (IllegalArgumentException exception) {
            // BridgeConfig diagnostics contain fixed setting names, never supplied values.
            disableWithMessage("Invalid config.yml: " + exception.getMessage());
            return;
        }

        if (rawConfig.contains("defaultWorld")) {
            getLogger().info("The deprecated defaultWorld setting is ignored; the primary Overworld is selected automatically.");
        }
        // Registry identity survives level-name changes. Never select the first loaded world.
        org.bukkit.World primaryWorld = getServer().getWorld(Key.key("minecraft:overworld"));
        if (primaryWorld == null) {
            disableWithMessage("Primary world minecraft:overworld is not loaded; enable Minebridge after world startup.");
            return;
        }

        bridgeConfig = candidate;
        TransportLimits transportLimits = TransportLimits.defaults();
        ExecutionLimits executionLimits = ExecutionLimits.defaults();
        // Local JVM diagnostic switch only; not a wire parameter or extra config key.
        boolean enableTestControl = Boolean.getBoolean("minebridge.testControl");
        Thread gameThread = Thread.currentThread();
        operationTrace = new OperationTrace(Boolean.getBoolean("minebridge.diagnostics") || enableTestControl,
                () -> Thread.currentThread() == gameThread);
        OperationTrace trace = operationTrace;
        TcpServer transport = new TcpServer(candidate.listenAddress(), candidate.port(), transportLimits, trace);
        tcpServer = transport;
        sessions = new SessionManager(transportLimits.maxSessions());
        if (enableTestControl) {
            testControl = new TestControl(transport::sessions, trace, this::requireGameThread);
            getServer().getServicesManager().register(TestControl.class, testControl, this, ServicePriority.Normal);
            getLogger().info("Local integration test control enabled.");
        }
        PaperBlockBackend blockBackend = new PaperBlockBackend(getServer(), this);
        BlockService blocks = new BlockService(blockBackend, this::requireGameThread);
        PlayerService players = new PlayerService(new PaperPlayerBackend(getServer(), blockBackend), blocks, this::requireGameThread);
        GameplayService gameplay = new GameplayService(new PaperGameplayBackend(getServer()), this::requireGameThread);
        activityLog = new SessionActivityLog();
        RequestRouter.WorldLookup worldLookup = name -> {
            requireGameThread();
            org.bukkit.World world = getServer().getWorld(name);
            if (world == null && name.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")) {
                world = getServer().getWorld(Key.key(name));
            }
            return world == null ? null : new WorldContext(world.getName(), world.getKey().toString(), world.getUID(),
                    world.getMinHeight(), world.getMaxHeight());
        };
        events = new EventsService(worldLookup::find, transport::sessions, name -> {
            requireGameThread();
            org.bukkit.entity.Player player = getServer().getPlayerExact(name);
            return player == null ? null : player.getUniqueId();
        }, this::requireGameThread);
        EventsService eventService = events;
        chatListener = new PaperChatListener(getServer(), eventService);
        PaperChatListener listener = chatListener;
        listener.refreshPlayers();
        getServer().getPluginManager().registerEvents(listener, this);
        gameListener = new PaperGameListener(getServer(), eventService);
        PaperGameListener nativeEvents = gameListener;
        eventService.beforeLavaSubscribe(nativeEvents::sampleLava);
        getServer().getPluginManager().registerEvents(nativeEvents, this);
        RequestRouter router = new RequestRouter(candidate, sessions, worldLookup,
                getPluginMeta().getVersion(), getServer().getMinecraftVersion(), transportLimits, executionLimits,
                blocks, trace, players, gameplay, activityLog,
                new WorldsService(new PaperWorldsBackend(getServer()), this::requireGameThread), eventService,
                new InventoryService(new PaperInventoryBackend(getServer(), blockBackend), blocks, players, this::requireGameThread));
        requestRouter = router;
        SessionActivityLog log = activityLog;
        java.util.logging.Logger logger = getLogger();
        activityLogTask = getServer().getScheduler().runTaskTimerAsynchronously(this,
                () -> log.drain(logger::info), 1L, 1L);
        gameExecutor = new GameExecutor(transport::sessions, router::route, () -> {
            listener.refreshPlayers();
            eventService.tick();
            nativeEvents.tick();
            router.pruneClosed();
            trace.drain(event -> getLogger().info(event.logLine()));
        },
                this::requireGameThread, executionLimits, testControl);
        dispatchTask = getServer().getScheduler().runTaskTimer(this, gameExecutor, 1L, 1L);
        transport.ready().whenComplete((address, failure) -> {
            // Binding and literal parsing happen on the reactor. Only this small
            // lifecycle notification is scheduled back onto Paper's server thread.
            if (tcpServer != transport) return;
            try {
                getServer().getScheduler().runTask(this, () -> {
                    if (tcpServer != transport || !isEnabled()) return;
                    if (failure != null) {
                        disableWithMessage("Cannot start TCP listener; check listenAddress and whether port is already in use.");
                    } else {
                        getLogger().info("TCP listener ready on port " + address.getPort()
                            + ". Handshake, blocks, players, selectors, chat, items, effects and entities are available (authentication "
                            + (candidate.authEnabled() ? "enabled" : "disabled") + ").");
                    }
                });
            } catch (IllegalPluginAccessException ignored) {
                // Disable may race with asynchronous startup; the old instance
                // must never schedule work or revive itself after that point.
            }
        });
        transport.start();
        getLogger().info("Lifecycle initialized for world '" + primaryWorld.getName()
            + "'. TCP transport is starting.");
    }

    @Override
    public void onDisable() {
        TcpServer transport = tcpServer;
        tcpServer = null;
        if (dispatchTask != null) {
            dispatchTask.cancel();
            dispatchTask = null;
        }
        if (activityLogTask != null) {
            activityLogTask.cancel();
            activityLogTask = null;
        }
        if (gameExecutor != null) {
            gameExecutor.close();
            gameExecutor = null;
        }
        if (requestRouter != null) {
            requestRouter.close();
            requestRouter = null;
        }
        if (chatListener != null) {
            org.bukkit.event.HandlerList.unregisterAll(chatListener);
            chatListener.close();
            chatListener = null;
        }
        if (events != null) {
            if (gameListener != null) {
                org.bukkit.event.HandlerList.unregisterAll(gameListener);
                gameListener.close();
                gameListener = null;
            }
            events.close();
            events = null;
        }
        // Cancellation is bounded memory work; the reactor still owns all socket IO.
        if (transport != null) transport.sessions().forEach(Session::close);
        if (sessions != null) {
            sessions.close();
            sessions = null;
        }
        if (activityLog != null) {
            activityLog.drain(line -> getLogger().info(line));
            activityLog = null;
        }
        if (operationTrace != null) {
            operationTrace.drain(event -> getLogger().info(event.logLine()));
            if (operationTrace.droppedEvents() != 0) {
                getLogger().info("Diagnostic trace buffer dropped events: " + operationTrace.droppedEvents());
            }
            operationTrace = null;
        }
        if (testControl != null) {
            getServer().getServicesManager().unregister(TestControl.class, testControl);
            testControl.close();
            testControl = null;
        }
        // Never join a network thread or close its channels on Paper's thread.
        // The reactor owns cleanup; close only signals it and wakes its selector.
        if (transport != null) transport.close();
        if (bridgeConfig != null) {
            bridgeConfig = null;
            getLogger().info("Lifecycle stopped. TCP shutdown requested.");
        }
    }

    private void disableWithMessage(String message) {
        getLogger().severe(message);
        getServer().getPluginManager().disablePlugin(this);
    }

    private void requireGameThread() {
        if (!getServer().isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }
}

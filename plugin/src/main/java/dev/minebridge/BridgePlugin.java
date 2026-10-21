package dev.minebridge;

import dev.minebridge.config.BridgeConfig;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.PaperBlockBackend;
import dev.minebridge.execution.ExecutionLimits;
import dev.minebridge.execution.GameExecutor;
import dev.minebridge.execution.OperationTrace;
import dev.minebridge.protocol.RequestRouter;
import dev.minebridge.session.SessionManager;
import dev.minebridge.session.WorldContext;
import dev.minebridge.transport.TcpServer;
import dev.minebridge.transport.TransportLimits;
import dev.minebridge.session.Session;
import dev.minebridge.testing.TestControl;
import java.io.File;
import java.io.IOException;
import org.bukkit.configuration.InvalidConfigurationException;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.plugin.IllegalPluginAccessException;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.plugin.ServicePriority;

/** Bounded TCP transport and authenticated handshake dispatched on Paper's server thread. */
public final class BridgePlugin extends JavaPlugin {
    private BridgeConfig bridgeConfig;
    private volatile TcpServer tcpServer;
    private SessionManager sessions;
    private GameExecutor gameExecutor;
    private BukkitTask dispatchTask;
    private OperationTrace operationTrace;
    private TestControl testControl;

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

        // POSTWORLD onEnable runs on Paper's server thread. Never choose a fallback world.
        if (getServer().getWorld(candidate.defaultWorld()) == null) {
            disableWithMessage("Configured defaultWorld is not loaded; check its name in config.yml.");
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
        BlockService blocks = new BlockService(new PaperBlockBackend(getServer()), this::requireGameThread);
        RequestRouter router = new RequestRouter(candidate, sessions, name -> {
            requireGameThread();
            org.bukkit.World world = getServer().getWorld(name);
            return world == null ? null : new WorldContext(world.getName(), world.getUID(),
                    world.getMinHeight(), world.getMaxHeight());
        }, getPluginMeta().getVersion(), getServer().getMinecraftVersion(), transportLimits, executionLimits,
                blocks, trace);
        gameExecutor = new GameExecutor(transport::sessions, router::route, () -> {
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
                            + ". Authenticated handshake and blocks.set are available.");
                    }
                });
            } catch (IllegalPluginAccessException ignored) {
                // Disable may race with asynchronous startup; the old instance
                // must never schedule work or revive itself after that point.
            }
        });
        transport.start();
        getLogger().info("Lifecycle initialized for world '" + candidate.defaultWorld()
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
        if (gameExecutor != null) {
            gameExecutor.close();
            gameExecutor = null;
        }
        // Cancellation is bounded memory work; the reactor still owns all socket IO.
        if (transport != null) transport.sessions().forEach(Session::close);
        if (sessions != null) {
            sessions.close();
            sessions = null;
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

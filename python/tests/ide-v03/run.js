"use strict";

// Runs inside the actual VS Code extension host. All definitions must resolve
// into the final wheel's site-packages; repository sources are not search paths.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "../../..");
const workspace = path.join(root, ".work/ide-v03-workspace");
const resultPath = path.join(root, ".work/ide-v03-results.json");
const configPath = path.join(workspace, "ide-v03-config.json");
const probePath = path.join(workspace, "completion_probe.py");
const wrongPath = path.join(workspace, "wrong_types_probe.py");

const probe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import Minecraft, block, items, effects, entity, selector",
  "from minebridge import events, slots, gamemode, weather, gamerule, damageCause",
  "",
  "block.COBBLESTONE  # catalog-block",
  "items.IRON_SWORD  # catalog-items",
  "effects.SPEED  # catalog-effects",
  "entity.LIGHTNING_BOLT  # catalog-entity",
  "selector.SELF  # catalog-selector",
  "events.CHAT_MESSAGE  # catalog-events",
  "slots.HEAD  # catalog-slots",
  "gamemode.SURVIVAL  # catalog-gamemode",
  "weather.CLEAR  # catalog-weather",
  "gamerule.KEEP_INVENTORY  # catalog-gamerule",
  "damageCause.LAVA  # catalog-damage",
  "",
  "if TYPE_CHECKING:",
  "    mc = Minecraft.create('localhost', 4712, player='Alice', logging=False)  # sig-create",
  "    mc.flush()  # facade",
  "    mc.setPos(selector.SELF, 0.5, 80, 0.5)  # sig-setpos",
  "    mc.players.setPos(selector.SELF, 0.5, 80, 0.5)  # sig-player-pos",
  "    mc.effects.add(selector.SELF, effects.SPEED, 100, 200)  # sig-effects",
  "    mc.effects.remove(selector.SELF, effects.SPEED)  # sig-remove-effect",
  "    mc.effects.clear(selector.SELF)  # sig-clear-effects",
  "    mc.players.setGameMode(selector.ALL_PLAYERS, gamemode.ADVENTURE)  # sig-gamemode",
  "    mc.worlds.setTime(6000)  # sig-world-time",
  "    mc.worlds.setWeather(weather.CLEAR)  # sig-world-weather",
  "    mc.worlds.setGameRule(gamerule.KEEP_INVENTORY, True)  # sig-rule",
  "    keep = mc.worlds.getGameRule(gamerule.KEEP_INVENTORY)  # hover-bool-rule",
  "    speed = mc.worlds.getGameRule(gamerule.RANDOM_TICK_SPEED)  # hover-int-rule",
  "    info = mc.server.getInfo()  # sig-info",
  "    inventory = mc.inventories.ofPlayer(selector.SELF)  # sig-of-player",
  "    chest = mc.inventories.ofBlock(10, 80, 10, combined=True)  # sig-of-block",
  "    inventory.getItem(slots.OFF_HAND)  # sig-get-item",
  "    inventory.getContents()  # sig-contents",
  "    written = inventory.setItem(slots.HEAD, items.DIAMOND_HELMET, 1)  # sig-set-item",
  "    cleared = inventory.clear(slots.OFF_HAND)  # sig-clear",
  "    mc.players.setItem(selector.ALL_PLAYERS, 8, items.COMPASS, 1)  # sig-bulk",
  "    view = inventory.getItem(0)  # hover-view",
  "    if view is not None:",
  "        print(view.hasAdditionalData)  # view-completion",
  "    mc.events.subscribe(events.CHAT_MESSAGE, lambda chat_ev: print(chat_ev.message))  # inferred-chat",
  "    mc.events.subscribe(events.BLOCK_BREAK, lambda break_ev: print(break_ev.block.key))  # inferred-break",
  "    mc.events.subscribe(events.PROJECTILE_HIT, lambda hit_ev: print(hit_ev.hitBlock))  # inferred-hit",
  "    mc.events.subscribe(events.CHAT_MESSAGE, None)  # sig-subscribe",
  "    mc.events.run()  # sig-run",
  "    mc.events.poll(timeout=0.0)  # sig-poll",
  "    mc.events.stop()  # sig-stop",
  "    chats = mc.events.pollEvents(events.CHAT_MESSAGE)  # sig-poll-events",
  "    recent = mc.events.getRecent(events.CHAT_MESSAGE, 20)  # sig-recent",
  "    mc.events.pollBlockHits()  # sig-block-hits",
  "    mc.events.pollDamageEvents()  # sig-damage-events",
  "    mc.events.pollProjectileShots()  # sig-shots",
  "    mc.events.clearPending(events.CHAT_MESSAGE)  # sig-clear-pending",
  "    mc.events.clearAll()  # sig-clear-all",
  "    mc.close()  # sig-close",
  "",
].join("\n");
const wrongProbe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import Minecraft, items, effects, events, selector, slots",
  "",
  "if TYPE_CHECKING:",
  "    mc = Minecraft.create()",
  "    inventory = mc.inventories.ofPlayer(selector.SELF)",
  "    mc.players.giveItem(selector.SELF, effects.SPEED)  # wrong-item",
  "    mc.effects.add(selector.SELF, items.IRON_SWORD, 100, 200)  # wrong-effect",
  "    mc.spawnEntity(0, 80, 0, effects.SPEED)  # wrong-entity",
  "    inventory.setItem(slots.HEAD, effects.SPEED)  # wrong-inventory-item",
  "    inventory.setItem(0.5, items.DIAMOND)  # wrong-slot",
  "    view = inventory.getItem(0)",
  "    if view is not None:",
  "        inventory.setItem(1, view)  # wrong-view",
  "    mc.events.subscribe(events.CHAT_MESSAGE, lambda chat_ev: print(chat_ev.block))  # wrong-event-field",
  "",
].join("\n");

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n", "utf8");
}
function prepare(pythonArgument) {
  const python = path.resolve(pythonArgument || path.join(root, ".venv-v03-314/Scripts/python.exe"));
  const installedPackage = path.resolve(path.dirname(python), "../Lib/site-packages/minebridge");
  assert.ok(fs.existsSync(python), "Missing final-wheel interpreter");
  assert.ok(fs.existsSync(path.join(installedPackage, "py.typed")), "Install final wheel first");
  const config = { python, installedPackage, expectedVersion: "0.3.0" };
  writeJson(configPath, config);
  writeJson(path.join(workspace, ".vscode/settings.json"), {
    "python.defaultInterpreterPath": python,
    "python.analysis.autoSearchPaths": false,
    "python.analysis.extraPaths": [],
    "python.analysis.diagnosticMode": "openFilesOnly",
    "python.analysis.typeCheckingMode": "basic",
    "python.terminal.activateEnvironment": false,
    "python.experiments.enabled": false,
    "telemetry.telemetryLevel": "off",
    "update.mode": "none",
    "extensions.autoUpdate": false,
    "extensions.autoCheckUpdates": false,
    "workbench.startupEditor": "none",
    "workbench.welcomePage.walkthroughs.openOnInstall": false,
  });
  fs.writeFileSync(probePath, probe, "utf8");
  fs.writeFileSync(wrongPath, wrongProbe, "utf8");
  writeJson(resultPath, { status: "prepared", config });
  return { workspace, resultPath, ...config };
}
function textOf(value) {
  return typeof value === "string" ? value : value && typeof value.value === "string"
    ? value.value : value == null ? "" : JSON.stringify(value);
}
function labelOf(item) { return typeof item.label === "string" ? item.label : item.label.label; }
function position(vscode, source, marker, after) {
  const lines = source.split("\n");
  const line = lines.findIndex((value) => value.includes("#") && value.slice(value.indexOf("#") + 1).trim() === marker);
  assert.ok(line >= 0, "Unknown marker: " + marker);
  const start = lines[line].indexOf(after);
  assert.ok(start >= 0, "Missing token: " + after);
  return new vscode.Position(line, start + after.length);
}
async function waitForProvider(query, accepts, message) {
  const deadline = Date.now() + 60000;
  do {
    const value = await query();
    if (accepts(value)) return value;
    await new Promise((resolve) => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  assert.fail(message);
}
function installedDefinition(config, values) {
  const files = (values || []).map((value) => (value.targetUri || value.uri).fsPath);
  assert.ok(files.length > 0, "No definition returned");
  assert.ok(files.every((file) => path.resolve(file).toLowerCase().startsWith(
    path.resolve(config.installedPackage).toLowerCase() + path.sep)),
  "Definition outside installed final wheel: " + files.join(", "));
  return files;
}
function runtime(config) {
  const script = [
    "import sys,json,socket",
    "attempts=[]",
    "def deny(*args,**kwargs):",
    "    attempts.append('network')",
    "    raise AssertionError('Import attempted a network connection')",
    "socket.socket.connect=deny",
    "socket.socket.connect_ex=deny",
    "socket.create_connection=deny",
    "from importlib import metadata",
    "import minebridge",
    "from minebridge import Minecraft,events,slots,gamemode,weather,gamerule,damageCause,block,items,effects,entity,selector",
    "from minebridge.models import InventoryRef,ItemView,ChatEvent,BlockBreakEvent",
    "print(json.dumps({'python':sys.version,'package':minebridge.__file__,'version':minebridge.__version__,",
    "'distributionVersion':metadata.version('minebridge'),'sysPath':sys.path,'networkAttempts':len(attempts),",
    "'types':{'event':type(events.CHAT_MESSAGE).__name__,'slot':type(slots.HEAD).__name__,",
    "'gamemode':type(gamemode.SURVIVAL).__name__,'weather':type(weather.CLEAR).__name__,",
    "'gamerule':type(gamerule.KEEP_INVENTORY).__name__,'damageCause':type(damageCause.LAVA).__name__}}))",
  ].join("\n");
  const completed = spawnSync(config.python, ["-I", "-c", script], {
    cwd: workspace, encoding: "utf8", windowsHide: true, timeout: 20000,
  });
  assert.equal(completed.status, 0, completed.stderr || String(completed.error));
  const data = JSON.parse(completed.stdout);
  assert.equal(path.resolve(data.package).toLowerCase(), path.join(config.installedPackage, "__init__.py").toLowerCase());
  assert.equal(data.version, config.expectedVersion);
  assert.equal(data.distributionVersion, config.expectedVersion);
  assert.equal(data.networkAttempts, 0);
  assert.ok(data.sysPath.every((entry) => !path.resolve(entry).toLowerCase().startsWith(path.join(root, "python/src").toLowerCase())));
  assert.deepEqual(data.types, {event:"EventType",slot:"EquipmentSlot",gamemode:"GameMode",weather:"Weather",gamerule:"GameRuleKey",damageCause:"DamageCause"});
  return data;
}

exports.run = async function run() {
  const vscode = require("vscode");
  const result = {status:"running",vscode:vscode.version,extensions:{},catalogs:{},signatures:{},inferredTypes:{}};
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    result.config = config; result.runtime = runtime(config);
    for (const id of ["ms-python.python", "ms-python.vscode-pylance"]) {
      const extension = vscode.extensions.getExtension(id);
      assert.ok(extension, "Missing extension: " + id); await extension.activate();
      result.extensions[id] = {version:extension.packageJSON.version,extensionPath:extension.extensionPath,active:extension.isActive};
    }
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(probePath));
    await vscode.window.showTextDocument(document, {preview:false});
    for (const [marker,target,expected,type] of [
      ["catalog-block","block.",["COBBLESTONE","OAK_STAIRS","COPPER_GOLEM_STATUE"],"LegacyBlock"],
      ["catalog-items","items.",["IRON_SWORD","DIAMOND","MACE"],"ItemKey"],
      ["catalog-effects","effects.",["SPEED","HASTE","LEVITATION"],"EffectKey"],
      ["catalog-entity","entity.",["LIGHTNING_BOLT","ZOMBIE","ARMADILLO"],"EntityTypeKey"],
      ["catalog-selector","selector.",["SELF","ALL_PLAYERS","NEAREST_PLAYER"],"Selector"],
      ["catalog-events","events.",["CHAT_MESSAGE","BLOCK_BREAK","PLAYER_DAMAGE","PROJECTILE_HIT","PLAYER_ENTER_LAVA"],"EventType[ChatEvent]"],
      ["catalog-slots","slots.",["HEAD","CHEST","LEGS","FEET","OFF_HAND"],"EquipmentSlot"],
      ["catalog-gamemode","gamemode.",["SURVIVAL","CREATIVE","ADVENTURE","SPECTATOR"],"GameMode"],
      ["catalog-weather","weather.",["CLEAR","RAIN","THUNDER"],"Weather"],
      ["catalog-gamerule","gamerule.",["KEEP_INVENTORY","RANDOM_TICK_SPEED","ADVANCE_TIME"],"GameRuleKey[bool]"],
      ["catalog-damage","damageCause.",["LAVA","FALL","PROJECTILE","VOID"],"DamageCause"],
    ]) {
      const completions = await waitForProvider(() => vscode.commands.executeCommand("vscode.executeCompletionItemProvider",document.uri,
        position(vscode,probe,marker,target),undefined,100),
      (value) => expected.every((name) => (value?.items || []).some((item) => labelOf(item) === name)), "Missing catalog completion: " + target);
      const hovers = await waitForProvider(() => vscode.commands.executeCommand("vscode.executeHoverProvider",document.uri,
        position(vscode,probe,marker,target+expected[0].slice(0,2))),
      (value) => (value || []).flatMap((item) => item.contents.map(textOf)).join("\n").includes(type), "Missing catalog type: " + type);
      const definitions = await vscode.commands.executeCommand("vscode.executeDefinitionProvider",document.uri,position(vscode,probe,marker,target+expected[0].slice(0,2)));
      result.catalogs[target] = {completionCount:completions.items.length,expected,found:expected.filter((name) => completions.items.some((item) => labelOf(item)===name)),
        hover:hovers.flatMap((item) => item.contents.map(textOf)),definitions:installedDefinition(config,definitions)};
      writeJson(resultPath,result);
    }
    for (const [marker,target,names] of [
      ["sig-create","Minecraft.create(",["ip","port","writeMode","token","world","timeout","coordinates","player","logging"]],
      ["sig-setpos","mc.setPos(",["targets","x","y","z","world"]],
      ["sig-player-pos","mc.players.setPos(",["targets","x","y","z","world"]],
      ["sig-effects","mc.effects.add(",["targets","effect","duration","level","particles"]],
      ["sig-remove-effect","mc.effects.remove(",["targets","effect"]],
      ["sig-clear-effects","mc.effects.clear(",["targets"]],
      ["sig-gamemode","mc.players.setGameMode(",["targets","mode"]],
      ["sig-world-time","mc.worlds.setTime(",["time","world"]],
      ["sig-world-weather","mc.worlds.setWeather(",["weather","world"]],
      ["sig-rule","mc.worlds.setGameRule(",["rule","value","world"]],
      ["sig-info","mc.server.getInfo(",[]],
      ["sig-of-player","mc.inventories.ofPlayer(",["target"]],
      ["sig-of-block","mc.inventories.ofBlock(",["x","y","z","world","combined"]],
      ["sig-get-item","inventory.getItem(",["slot"]],
      ["sig-contents","inventory.getContents(",[]],
      ["sig-set-item","inventory.setItem(",["slot","item","amount"]],
      ["sig-clear","inventory.clear(",["slot"]],
      ["sig-bulk","mc.players.setItem(",["targets","slot","item","amount"]],
      ["sig-subscribe","mc.events.subscribe(",["eventType","handler","players","world","region","blocks"]],
      ["sig-run","mc.events.run(",[]],
      ["sig-poll","mc.events.poll(",["timeout"]],
      ["sig-stop","mc.events.stop(",[]],
      ["sig-poll-events","mc.events.pollEvents(",["eventType","limit"]],
      ["sig-recent","mc.events.getRecent(",["eventType","limit"]],
      ["sig-block-hits","mc.events.pollBlockHits(",["limit"]],
      ["sig-damage-events","mc.events.pollDamageEvents(",["limit"]],
      ["sig-shots","mc.events.pollProjectileShots(",["limit"]],
      ["sig-clear-pending","mc.events.clearPending(",["eventType"]],
      ["sig-clear-all","mc.events.clearAll(",[]],
      ["sig-close","mc.close(",[]],
    ]) {
      const help = await waitForProvider(() => vscode.commands.executeCommand("vscode.executeSignatureHelpProvider",document.uri,
        position(vscode,probe,marker,target),"("),(value) => !!value?.signatures?.length,"Missing signature: " + marker);
      const signature = help.signatures[help.activeSignature || 0];
      const parameters = signature.parameters.map((value) => typeof value.label === "string" ? value.label : signature.label.slice(...value.label));
      assert.deepEqual(parameters.map((value) => value.match(/^\s*(\w+)/)?.[1]).filter(Boolean),names,"Wrong signature: " + marker);
      const expectedReturn = {"sig-block-hits":"EventBatch[BlockInteractEvent]", "sig-damage-events":"EventBatch[EntityDamageEvent]", "sig-shots":"EventBatch[ProjectileShotEvent]"}[marker];
      if (expectedReturn) assert.ok(signature.label.includes(expectedReturn), "Missing typed poll result: " + marker + " => " + signature.label);
      const definitions = await vscode.commands.executeCommand("vscode.executeDefinitionProvider",document.uri,position(vscode,probe,marker,target.slice(0,-2)));
      result.signatures[marker] = {label:signature.label,parameters,documentation:textOf(signature.documentation),definitions:installedDefinition(config,definitions)};
      writeJson(resultPath,result);
    }
    for (const [marker,token,type] of [
      ["inferred-chat","chat_ev","ChatEvent"],["inferred-break","break_ev","BlockBreakEvent"],["inferred-hit","hit_ev","ProjectileHitEvent"],
      ["sig-of-player","inventory","InventoryRef"],["sig-set-item","written","SlotWriteResult"],["sig-clear","cleared","InventoryUpdateResult"],
      ["hover-view","view","ItemView | None"],["sig-poll-events","chats","EventBatch[ChatEvent]"],["sig-recent","recent","RecentEvents[ChatEvent]"],
      ["hover-bool-rule","keep","bool"],["hover-int-rule","speed","int"],
    ]) {
      const hover = await waitForProvider(async () => {
        const values = await vscode.commands.executeCommand("vscode.executeHoverProvider",document.uri,position(vscode,probe,marker,token.slice(0,2)));
        result.inferredTypes[marker] = (values || []).flatMap((item) => item.contents.map(textOf));
        writeJson(resultPath,result); return values;
      },
        (value) => (value || []).flatMap((item) => item.contents.map(textOf)).join("\n").includes(type),"Missing inferred type: " + marker + " => " + type);
      result.inferredTypes[marker] = hover.flatMap((item) => item.contents.map(textOf)); writeJson(resultPath,result);
    }
    for (const [marker,token,expected] of [
      ["facade","mc.",["events","inventories","worlds","server","setPos","players","setBlock","setBlocks","getBlock","close"]],
      ["view-completion","view.",["key","amount","name","lore","hasAdditionalData","truncated"]],
    ]) {
      const completions = await waitForProvider(() => vscode.commands.executeCommand("vscode.executeCompletionItemProvider",document.uri,position(vscode,probe,marker,token),undefined,100),
        (value) => expected.every((name) => (value?.items || []).some((item) => labelOf(item)===name)),"Missing facade/model completion: " + marker);
      result[marker+"Completions"] = completions.items.map(labelOf);
    }
    const wrong = await vscode.workspace.openTextDocument(vscode.Uri.file(wrongPath));
    await vscode.window.showTextDocument(wrong,{preview:false});
    const expectedDiagnostics = ["wrong-item","wrong-effect","wrong-entity","wrong-inventory-item","wrong-slot","wrong-view"].map((marker) => ({
      marker,line:position(vscode,wrongProbe,marker,["wrong-inventory-item","wrong-slot","wrong-view"].includes(marker) ? "inventory." : "mc.").line,code:"reportArgumentType"}));
    expectedDiagnostics.push({marker:"wrong-event-field",line:position(vscode,wrongProbe,"wrong-event-field","mc.").line,code:"reportAttributeAccessIssue"});
    const diagnostics = await waitForProvider(() => vscode.languages.getDiagnostics(wrong.uri),
      (values) => expectedDiagnostics.every((expected) => values.some((item) => item.range.start.line===expected.line
        && String(typeof item.code==="object" ? item.code.value : item.code)===expected.code)),"Expected incorrect-type diagnostics missing");
    result.wrongTypeDiagnostics = diagnostics.map((item) => ({message:item.message,code:typeof item.code==="object" ? item.code.value : item.code,line:item.range.start.line+1}));
    result.expectedDiagnostics=expectedDiagnostics;
    result.probeDiagnostics = vscode.languages.getDiagnostics(document.uri).map((item) => ({message:item.message,code:typeof item.code==="object" ? item.code.value : item.code,line:item.range.start.line+1}));
    assert.equal(result.probeDiagnostics.length,0,"Valid installed API probe has diagnostics");
    result.status="passed";
  } catch (error) {
    result.status="failed";result.error=error.stack || String(error);throw error;
  } finally { writeJson(resultPath,result); }
};

if (require.main===module) {
  assert.equal(process.argv[2],"--prepare","Usage: node run.js --prepare [python-exe]");
  process.stdout.write(JSON.stringify(prepare(process.argv[3]),null,2)+"\n");
}

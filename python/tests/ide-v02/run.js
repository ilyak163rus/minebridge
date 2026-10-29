"use strict";

// Actual VS Code/Pylance checks against a final wheel in a clean interpreter.
// This helper never adds python/src to the language server or runtime paths.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "../../..");
const workspace = path.join(root, ".work/ide-v02-workspace");
const resultPath = path.join(root, ".work/ide-v02-results.json");
const configPath = path.join(workspace, "ide-v02-config.json");
const probePath = path.join(workspace, "completion_probe.py");
const diagnosticsPath = path.join(workspace, "wrong_key_probe.py");
const probe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import Minecraft, block, items, effects, entity, selector",
  "",
  "block.COBBLESTONE  # block-completion-hover",
  "block.OAK_STAIRS.withStates(facing='east')  # states-signature",
  "items.IRON_SWORD  # item-completion-hover",
  "effects.SPEED  # effect-completion-hover",
  "entity.LIGHTNING_BOLT  # entity-completion-hover",
  "selector.SELF  # selector-completion-hover",
  "",
  "if TYPE_CHECKING:",
  "    mc = Minecraft.create('localhost', 4711, writeMode='buffered', player='Alice')  # create-signature",
  "    mc.flush()  # facade-completion",
  "    mc.withContext(player='Alice')  # context-signature",
  "    mc.setBlock(0, 80, 0, block.COBBLESTONE)  # set-signature",
  "    mc.setBlocks(0, 80, 0, 1, 80, 1, block.STONE)  # fill-signature",
  "    mc.getBlock(0, 80, 0)  # get-signature",
  "    mc.getBlocks(0, 80, 0, 1, 80, 1)  # region-signature",
  "    mc.blocks.getBlock(0, 80, 0)  # modern-get-signature",
  "    mc.blocks.getBlocks(0, 80, 0, 1, 80, 1)  # modern-region-signature",
  "    mc.getPlayerEntityId('Alice')  # id-signature",
  "    mc.players.get('Alice')  # player-get-signature",
  "    mc.players.list()  # list-signature",
  "    mc.players.getPos(selector.SELF)  # pos-signature",
  "    mc.players.teleport(selector.SELF, 0, 80, 0)  # teleport-signature",
  "    mc.players.giveItem(selector.ALL_PLAYERS, items.IRON_SWORD)  # give-signature",
  "    mc.effects.add(selector.SELF, effects.SPEED, duration=30, level=2)  # effect-signature",
  "    mc.entities.spawn(entity.ZOMBIE, 0, 80, 0)  # entity-signature",
  "    mc.spawnEntity(0, 80, 0, entity.LIGHTNING_BOLT)  # root-signature",
  "    mc.postToChat('Hello')  # chat-signature",
  "    mc.flush()  # flush-signature",
  "    mc.close()  # close-signature",
  "",
].join("\n");
const wrongProbe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import Minecraft, items, effects, selector",
  "",
  "if TYPE_CHECKING:",
  "    mc = Minecraft.create()",
  "    mc.players.giveItem(selector.SELF, effects.SPEED)  # wrong-item",
  "    mc.effects.add(selector.SELF, items.IRON_SWORD, duration=1)  # wrong-effect",
  "    mc.spawnEntity(0, 80, 0, effects.SPEED)  # wrong-entity",
  "",
].join("\n");

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n", "utf8");
}

function prepare(pythonArgument) {
  const python = path.resolve(pythonArgument || path.join(root, ".venv-v02-314/Scripts/python.exe"));
  const installedPackage = path.resolve(path.dirname(python), "../Lib/site-packages/minebridge");
  assert.ok(fs.existsSync(python), "Missing test interpreter");
  assert.ok(fs.existsSync(path.join(installedPackage, "py.typed")), "Install the final wheel first");
  const config = { python, installedPackage, expectedVersion: "0.2.0" };
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
  fs.writeFileSync(diagnosticsPath, wrongProbe, "utf8");
  writeJson(resultPath, { status: "prepared", config });
  return { workspace, resultPath, ...config };
}

function textOf(value) {
  if (typeof value === "string") return value;
  if (value && typeof value.value === "string") return value.value;
  return value == null ? "" : JSON.stringify(value);
}

function labelOf(item) {
  return typeof item.label === "string" ? item.label : item.label.label;
}

function position(vscode, source, marker, after) {
  const lines = source.split("\n");
  const line = lines.findIndex((value) => value.includes("# " + marker));
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

function installedRuntime(config) {
  const script = [
    "import sys, json, socket",
    "attempts = []",
    "def deny(*args, **kwargs):",
    "    attempts.append('network')",
    "    raise AssertionError('Import attempted to connect')",
    "socket.socket.connect = deny",
    "socket.socket.connect_ex = deny",
    "socket.create_connection = deny",
    "from importlib import metadata",
    "from minebridge import Minecraft, block, items, effects, entity, selector",
    "import minebridge",
    "print(json.dumps({'python': sys.version, 'package': minebridge.__file__,",
    "    'version': minebridge.__version__, 'distributionVersion': metadata.version('minebridge'),",
    "    'sysPath': sys.path, 'networkAttempts': len(attempts),",
    "    'types': {name: type(value).__name__ for name, value in [('item', items.IRON_SWORD),",
    "    ('effect', effects.SPEED), ('entity', entity.LIGHTNING_BOLT), ('selector', selector.SELF)]}}))",
  ].join("\n");
  const completed = spawnSync(config.python, ["-I", "-c", script], {
    cwd: workspace, encoding: "utf8", windowsHide: true, timeout: 20000,
  });
  assert.equal(completed.status, 0, completed.stderr || String(completed.error));
  const runtime = JSON.parse(completed.stdout);
  assert.equal(path.resolve(runtime.package).toLowerCase(),
    path.join(config.installedPackage, "__init__.py").toLowerCase());
  assert.equal(runtime.version, config.expectedVersion);
  assert.equal(runtime.distributionVersion, config.expectedVersion);
  assert.ok(runtime.sysPath.every((entry) => !path.resolve(entry).toLowerCase().startsWith(
    path.join(root, "python/src").toLowerCase())), "Source path leaked into isolated interpreter");
  assert.equal(runtime.networkAttempts, 0);
  assert.deepEqual(runtime.types, {
    item: "ItemKey", effect: "EffectKey", entity: "EntityTypeKey", selector: "Selector",
  });
  return runtime;
}

function installedDefinition(config, definitions) {
  const files = (definitions || []).map((value) => (value.targetUri || value.uri).fsPath);
  assert.ok(files.length > 0, "No source definition was returned");
  assert.ok(files.every((file) => path.resolve(file).toLowerCase().startsWith(
    path.resolve(config.installedPackage).toLowerCase() + path.sep,
  )), "A definition resolved outside the installed final wheel: " + files.join(", "));
  return files;
}

exports.run = async function run() {
  const vscode = require("vscode");
  const result = { status: "running", vscode: vscode.version, extensions: {}, catalogs: {}, signatures: {} };
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    result.config = config;
    result.runtime = installedRuntime(config);
    for (const id of ["ms-python.python", "ms-python.vscode-pylance"]) {
      const extension = vscode.extensions.getExtension(id);
      assert.ok(extension, "Missing extension: " + id);
      await extension.activate();
      result.extensions[id] = { version: extension.packageJSON.version,
        extensionPath: extension.extensionPath, active: extension.isActive };
    }
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(probePath));
    await vscode.window.showTextDocument(document, { preview: false });
    for (const [marker, target, expected, type] of [
      ["block-completion-hover", "block.", ["COBBLESTONE", "OAK_STAIRS", "COPPER_GOLEM_STATUE"], "LegacyBlock"],
      ["item-completion-hover", "items.", ["IRON_SWORD", "DIAMOND", "MACE"], "ItemKey"],
      ["effect-completion-hover", "effects.", ["SPEED", "HASTE", "LEVITATION"], "EffectKey"],
      ["entity-completion-hover", "entity.", ["LIGHTNING_BOLT", "ZOMBIE", "ARMADILLO"], "EntityTypeKey"],
      ["selector-completion-hover", "selector.", ["SELF", "ALL_PLAYERS", "NEAREST_PLAYER"], "Selector"],
    ]) {
      const completions = await waitForProvider(() => vscode.commands.executeCommand(
        "vscode.executeCompletionItemProvider", document.uri,
        position(vscode, probe, marker, target), undefined, 100,
      ), (value) => expected.every((name) => (value?.items || []).some((item) => labelOf(item) === name)),
      "Catalog completion missing: " + target);
      const labels = completions.items.map(labelOf);
      const hovers = await waitForProvider(() => vscode.commands.executeCommand(
        "vscode.executeHoverProvider", document.uri,
        position(vscode, probe, marker, target + expected[0].slice(0, 3)),
      ), (value) => (value || []).flatMap((item) => item.contents.map(textOf)).join("\n").includes(type),
      "Typed hover missing: " + type);
      const definitions = await vscode.commands.executeCommand("vscode.executeDefinitionProvider", document.uri,
        position(vscode, probe, marker, target + expected[0].slice(0, 3)));
      result.catalogs[target] = { completionCount: labels.length,
        expected, found: expected.filter((name) => labels.includes(name)),
        hover: hovers.flatMap((item) => item.contents.map(textOf)),
        definitions: installedDefinition(config, definitions) };
      writeJson(resultPath, result);
    }
    for (const [marker, target, parameters] of [
      ["create-signature", "Minecraft.create(", ["ip", "port", "writeMode", "token", "world", "timeout", "coordinates", "player"]],
      ["context-signature", "mc.withContext(", ["player"]],
      ["set-signature", "mc.setBlock(", ["x", "y", "z", "block", "data"]],
      ["fill-signature", "mc.setBlocks(", ["x1", "y1", "z1", "x2", "y2", "z2", "block", "data"]],
      ["get-signature", "mc.getBlock(", ["x", "y", "z"]],
      ["region-signature", "mc.getBlocks(", ["x1", "y1", "z1", "x2", "y2", "z2"]],
      ["modern-get-signature", "mc.blocks.getBlock(", ["x", "y", "z"]],
      ["modern-region-signature", "mc.blocks.getBlocks(", ["x1", "y1", "z1", "x2", "y2", "z2"]],
      ["id-signature", "mc.getPlayerEntityId(", ["name"]],
      ["player-get-signature", "mc.players.get(", ["target"]],
      ["list-signature", "mc.players.list(", ["targets"]],
      ["pos-signature", "mc.players.getPos(", ["target"]],
      ["teleport-signature", "mc.players.teleport(", ["targets", "x", "y", "z", "world"]],
      ["give-signature", "mc.players.giveItem(", ["targets", "item", "amount", "overflow"]],
      ["effect-signature", "mc.effects.add(", ["targets", "effect", "duration", "level", "particles"]],
      ["entity-signature", "mc.entities.spawn(", ["entityType", "x", "y", "z", "world", "item", "block", "face", "owner"]],
      ["root-signature", "mc.spawnEntity(", ["x", "y", "z", "entityType", "world", "item", "block", "face", "owner"]],
      ["chat-signature", "mc.postToChat(", ["message"]],
      ["flush-signature", "mc.flush(", []],
      ["close-signature", "mc.close(", []],
    ]) {
      const help = await waitForProvider(() => vscode.commands.executeCommand(
        "vscode.executeSignatureHelpProvider", document.uri,
        position(vscode, probe, marker, target), "(",
      ), (value) => !!value?.signatures?.length, "Missing signature: " + marker);
      const signature = help.signatures[help.activeSignature || 0];
      const parameterLabels = signature.parameters.map((value) => typeof value.label === "string"
        ? value.label : signature.label.slice(value.label[0], value.label[1]));
      const parameterNames = parameterLabels.map((value) => value.match(/^\s*(\w+)/)?.[1]).filter(Boolean);
      assert.deepEqual(parameterNames, parameters, "Unexpected signature: " + marker);
      const definitions = await vscode.commands.executeCommand("vscode.executeDefinitionProvider", document.uri,
        position(vscode, probe, marker, target.slice(0, -2)));
      result.signatures[marker] = { label: signature.label, parameters: parameterLabels,
        documentation: textOf(signature.documentation), definitions: installedDefinition(config, definitions) };
      writeJson(resultPath, result);
    }
    const facade = await waitForProvider(() => vscode.commands.executeCommand(
      "vscode.executeCompletionItemProvider", document.uri,
      position(vscode, probe, "facade-completion", "mc."), undefined, 100,
    ), (value) => ["blocks", "players", "effects", "entities", "setBlock", "setBlocks", "getBlock",
      "getBlocks", "getPlayerEntityId", "withContext", "postToChat", "spawnEntity", "flush", "close"]
      .every((name) => (value?.items || []).some((item) => labelOf(item) === name)),
    "Final facade completion is incomplete");
    result.facadeCompletions = facade.items.map(labelOf);
    const wrong = await vscode.workspace.openTextDocument(vscode.Uri.file(diagnosticsPath));
    await vscode.window.showTextDocument(wrong, { preview: false });
    const diagnosticLines = ["wrong-item", "wrong-effect", "wrong-entity"].map((marker) =>
      position(vscode, wrongProbe, marker, "mc.").line);
    const diagnostics = await waitForProvider(() => vscode.languages.getDiagnostics(wrong.uri),
      (values) => diagnosticLines.every((line) => values.some((item) => item.range.start.line === line
        && String(typeof item.code === "object" ? item.code.value : item.code) === "reportArgumentType")),
      "Pylance did not reject wrong registry-key types");
    result.wrongKeyDiagnostics = diagnostics.map((item) => ({
      message: item.message, code: typeof item.code === "object" ? item.code.value : item.code,
      line: item.range.start.line + 1,
    }));
    result.probeDiagnostics = vscode.languages.getDiagnostics(document.uri).map((item) => ({
      message: item.message, code: typeof item.code === "object" ? item.code.value : item.code,
      line: item.range.start.line + 1,
    }));
    assert.equal(result.probeDiagnostics.length, 0, "The valid installed API probe has diagnostics");
    result.status = "passed";
  } catch (error) {
    result.status = "failed";
    result.error = error.stack || String(error);
    throw error;
  } finally {
    writeJson(resultPath, result);
  }
};

if (require.main === module) {
  assert.equal(process.argv[2], "--prepare", "Usage: node run.js --prepare [python-exe]");
  process.stdout.write(JSON.stringify(prepare(process.argv[3]), null, 2) + "\n");
}

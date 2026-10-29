"use strict";

// Actual VS Code extension-host checks against python/src; no wheel is built or
// installed. Preparation uses the Node runtime bundled with portable VS Code.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "../../..");
const workspace = path.join(root, ".work/ide-i04-workspace");
const resultPath = path.join(root, ".work/ide-i04-results.json");
const configPath = path.join(workspace, "ide-i04-config.json");
const probePath = path.join(workspace, "completion_probe.py");
const diagnosticsPath = path.join(workspace, "wrong_key_probe.py");
const probe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import Minecraft, items, effects, entity, selector",
  "",
  "items.IRON_SWORD  # item-completion-hover",
  "effects.SPEED  # effect-completion-hover",
  "entity.LIGHTNING_BOLT  # entity-completion-hover",
  "selector.SELF  # selector-completion-hover",
  "",
  "if TYPE_CHECKING:",
  "    mc = Minecraft.create()",
  "    mc.players.giveItem(selector.ALL_PLAYERS, items.IRON_SWORD)  # give-signature",
  "    mc.effects.add(selector.SELF, effects.SPEED, duration=30, level=2)  # effect-signature",
  "    mc.entities.spawn(entity.ZOMBIE, 0, 80, 0)  # entity-signature",
  "    mc.spawnEntity(0, 80, 0, entity.LIGHTNING_BOLT)  # root-signature",
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
  const python = path.resolve(pythonArgument || path.join(root, ".venv-tools/Scripts/python.exe"));
  const source = path.join(root, "python/src");
  assert.ok(fs.existsSync(python), "Missing test interpreter");
  assert.ok(fs.existsSync(path.join(source, "minebridge/py.typed")), "Source py.typed is required");
  const config = { python, source, package: path.join(source, "minebridge") };
  writeJson(configPath, config);
  writeJson(path.join(workspace, ".vscode/settings.json"), {
    "python.defaultInterpreterPath": python,
    "python.analysis.autoSearchPaths": false,
    "python.analysis.extraPaths": [source],
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

function sourceRuntime(config) {
  const script = [
    "import sys, json, socket",
    "sys.path.insert(0, " + JSON.stringify(config.source) + ")",
    "attempts = []",
    "def deny(*args, **kwargs):",
    "    attempts.append('network')",
    "    raise AssertionError('Import attempted to connect')",
    "socket.socket.connect = deny",
    "socket.socket.connect_ex = deny",
    "socket.create_connection = deny",
    "from minebridge import items, effects, entity, selector",
    "import minebridge",
    "print(json.dumps({'python': sys.version, 'package': minebridge.__file__,",
    "    'version': minebridge.__version__, 'networkAttempts': len(attempts),",
    "    'types': {name: type(value).__name__ for name, value in [('item', items.IRON_SWORD),",
    "    ('effect', effects.SPEED), ('entity', entity.LIGHTNING_BOLT), ('selector', selector.SELF)]}}))",
  ].join("\n");
  const completed = spawnSync(config.python, ["-I", "-c", script], {
    cwd: workspace, encoding: "utf8", windowsHide: true, timeout: 20000,
  });
  assert.equal(completed.status, 0, completed.stderr || String(completed.error));
  const runtime = JSON.parse(completed.stdout);
  assert.equal(path.resolve(runtime.package).toLowerCase(),
    path.join(config.package, "__init__.py").toLowerCase());
  assert.equal(runtime.networkAttempts, 0);
  assert.deepEqual(runtime.types, {
    item: "ItemKey", effect: "EffectKey", entity: "EntityTypeKey", selector: "Selector",
  });
  return runtime;
}

function sourceDefinition(config, definitions) {
  const files = (definitions || []).map((value) => (value.targetUri || value.uri).fsPath);
  assert.ok(files.length > 0, "No source definition was returned");
  assert.ok(files.every((file) => path.resolve(file).toLowerCase().startsWith(
    path.resolve(config.package).toLowerCase() + path.sep,
  )), "A definition resolved outside python/src/minebridge: " + files.join(", "));
  return files;
}

exports.run = async function run() {
  const vscode = require("vscode");
  const result = { status: "running", vscode: vscode.version, extensions: {}, catalogs: {}, signatures: {} };
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    result.config = config;
    result.runtime = sourceRuntime(config);
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
        definitions: sourceDefinition(config, definitions) };
      writeJson(resultPath, result);
    }
    for (const [marker, target, parameters] of [
      ["give-signature", "mc.players.giveItem(", ["targets", "item", "amount", "overflow"]],
      ["effect-signature", "mc.effects.add(", ["targets", "effect", "duration", "level", "particles"]],
      ["entity-signature", "mc.entities.spawn(", ["entityType", "x", "y", "z", "world", "item", "block", "face", "owner"]],
      ["root-signature", "mc.spawnEntity(", ["x", "y", "z", "entityType", "world", "item", "block", "face", "owner"]],
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
        documentation: textOf(signature.documentation), definitions: sourceDefinition(config, definitions) };
      writeJson(resultPath, result);
    }
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
    assert.equal(result.probeDiagnostics.length, 0, "The valid source API probe has diagnostics");
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

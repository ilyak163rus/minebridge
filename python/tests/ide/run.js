"use strict";

// No npm dependencies. Preparation can run with Node or VS Code's bundled Node:
//   $env:ELECTRON_RUN_AS_NODE='1'; & $codeExe run.js --prepare $pythonExe
// Then launch VS Code with --extensionDevelopmentPath <this directory>,
// --extensionTestsPath <this file>, --user-data-dir <repo>/.work/ide-user-data,
// --extensions-dir <installed extensions>, and <repo>/.work/ide-workspace.
// The Python interpreter must contain an installed wheel, not an editable install.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "../../..");
const work = path.join(root, ".work");
const workspace = path.join(work, "ide-workspace");
const resultPath = path.join(work, "ide-results.json");
const configPath = path.join(workspace, "ide-test-config.json");
const probePath = path.join(workspace, "completion_probe.py");
const constants = ["AIR", "STONE", "COBBLESTONE"];
const probe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import block",
  "from minebridge.minecraft import Minecraft",
  "",
  "block.  # constants-completion",
  "block.COBBLESTONE  # constant-hover",
  "",
  "if TYPE_CHECKING:",
  '    mc = Minecraft.create("localhost", 4711)',
  "    Minecraft.  # minecraft-completion",
  "    Minecraft.create()  # create-signature",
  "    mc.  # facade-completion",
  "    mc.blocks.  # blocks-completion",
  "    mc.setBlock(0, 64, 0, block.COBBLESTONE)  # root-signature",
  "    mc.blocks.setBlock(0, 64, 0, block.COBBLESTONE)  # blocks-signature",
  "",
].join("\n");

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n", "utf8");
}

function prepare(pythonArgument) {
  const python = path.resolve(
    pythonArgument || path.join(root, ".venv-t01-314/Scripts/python.exe"),
  );
  assert.ok(fs.existsSync(python), "Python interpreter does not exist: " + python);
  const sitePackages = path.resolve(path.dirname(python), "../Lib/site-packages");
  const installedPackage = path.join(sitePackages, "minebridge");
  assert.ok(fs.existsSync(path.join(installedPackage, "py.typed")),
    "Install the minebridge wheel into the test interpreter before preparing.");

  fs.mkdirSync(workspace, { recursive: true });
  writeJson(configPath, { python, installedPackage });
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
  // Clear a previous result so an unsuccessful run cannot appear to pass.
  writeJson(resultPath, { status: "prepared", config: { python, installedPackage } });
  return { workspace, resultPath, python, installedPackage };
}

function textOf(value) {
  if (typeof value === "string") return value;
  if (value && typeof value.value === "string") return value.value;
  return value == null ? "" : JSON.stringify(value);
}

function labelOf(item) {
  return typeof item.label === "string" ? item.label : item.label.label;
}

function installedRuntime(config) {
  const source = [
    "import json, socket, importlib.metadata",
    "attempts = []",
    "def deny(*args, **kwargs):",
    "    attempts.append('network call')",
    "    raise AssertionError('The offline package tried to connect to a server')",
    "socket.socket.connect = deny",
    "socket.socket.connect_ex = deny",
    "socket.create_connection = deny",
    "from minebridge import block",
    "from minebridge.minecraft import Minecraft",
    "import minebridge, sys",
    "print(json.dumps({'python': sys.version, 'package': minebridge.__file__,",
    "    'version': importlib.metadata.version('minebridge'),",
    "    'facade': Minecraft.__module__ + '.' + Minecraft.__name__,",
    "    'constants': {name: {'id': getattr(block, name).id, 'data': getattr(block, name).data}",
    "                  for name in ('AIR', 'STONE', 'COBBLESTONE')},",
    "    'networkAttempts': len(attempts)}))",
  ].join("\n");
  const completed = spawnSync(config.python, ["-I", "-c", source], {
    cwd: workspace, encoding: "utf8", windowsHide: true, timeout: 20000,
  });
  assert.equal(completed.status, 0,
    "Offline installed-wheel import failed: " + (completed.stderr || completed.error));
  const runtime = JSON.parse(completed.stdout);
  assert.equal(runtime.networkAttempts, 0);
  assert.equal(runtime.facade, "minebridge.minecraft.Minecraft");
  assert.ok(path.resolve(runtime.package).toLowerCase().startsWith(
    path.resolve(config.installedPackage).toLowerCase() + path.sep,
  ), "Runtime imported a source tree instead of the installed wheel");
  assert.deepEqual(runtime.constants, {
    AIR: { id: 0, data: 0 }, STONE: { id: 1, data: 0 },
    COBBLESTONE: { id: 4, data: 0 },
  });
  return runtime;
}

function probePosition(vscode, marker, after) {
  const lines = probe.split("\n");
  const line = lines.findIndex((value) => value.includes("# " + marker));
  assert.ok(line >= 0, "Unknown probe marker: " + marker);
  const character = lines[line].indexOf(after) + after.length;
  assert.ok(character >= after.length, "Missing probe target: " + after);
  return new vscode.Position(line, character);
}

async function waitForProvider(query, accepts, message) {
  const deadline = Date.now() + 90000;
  let value;
  do {
    value = await query();
    if (accepts(value)) return value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  assert.fail(message);
}

function parameterText(signature, parameter) {
  return typeof parameter.label === "string"
    ? parameter.label
    : signature.label.slice(parameter.label[0], parameter.label[1]);
}

function signatureRecord(help) {
  const signature = help.signatures[help.activeSignature || 0];
  return {
    label: signature.label,
    parameters: signature.parameters.map((parameter) => parameterText(signature, parameter)),
    documentation: textOf(signature.documentation),
  };
}

function parameterName(value) {
  return value.match(/^\s*(\w+)/)?.[1];
}

exports.run = async function run() {
  const vscode = require("vscode");
  const result = {
    status: "running", vscode: vscode.version,
    extensions: {}, expectedCompletions: constants,
  };
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    result.config = config;
    result.runtime = installedRuntime(config);

    for (const id of ["ms-python.python", "ms-python.vscode-pylance"]) {
      const extension = vscode.extensions.getExtension(id);
      assert.ok(extension, "Missing IDE extension: " + id);
      await extension.activate();
      result.extensions[id] = {
        version: extension.packageJSON.version,
        extensionPath: extension.extensionPath,
        active: extension.isActive,
      };
    }

    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(probePath));
    assert.equal(document.languageId, "python");
    const completions = await waitForProvider(
      () => vscode.commands.executeCommand(
        "vscode.executeCompletionItemProvider", document.uri,
        probePosition(vscode, "constants-completion", "block."), undefined, 100,
      ),
      (items) => constants.every((name) => (items?.items || []).some((item) => labelOf(item) === name)),
      "Required block constants were absent from the IDE completion list",
    );

    result.completionLabels = (completions?.items || []).map(labelOf);
    result.completions = (completions?.items || [])
      .filter((item) => constants.includes(labelOf(item)))
      .map((item) => ({
        label: labelOf(item), detail: item.detail || "",
        documentation: textOf(item.documentation),
      }));
    assert.ok(constants.every((name) => result.completionLabels.includes(name)),
      "Required block constants were absent from the IDE completion list");

    const hovers = await vscode.commands.executeCommand(
      "vscode.executeHoverProvider", document.uri,
      probePosition(vscode, "constant-hover", "block.COBBLE"),
    );
    result.hover = (hovers || []).flatMap((hover) => hover.contents.map(textOf));
    assert.match(result.hover.join("\n"), /LegacyBlock/,
      "Hover must describe the typed constant");
    assert.match(result.hover.join("\n"), /minecraft:cobblestone|legacy ID 4/i,
      "Hover must include documentation for COBBLESTONE");

    const definitions = await vscode.commands.executeCommand(
      "vscode.executeDefinitionProvider", document.uri,
      probePosition(vscode, "constant-hover", "block.COBBLE"),
    );
    result.definitions = (definitions || []).map((definition) =>
      (definition.targetUri || definition.uri).fsPath);
    assert.ok(result.definitions.some((file) => path.resolve(file).toLowerCase()
      .startsWith(path.resolve(config.installedPackage).toLowerCase() + path.sep)),
    "Pylance must resolve the installed wheel, not the repository source tree");

    const facadeDefinitions = await vscode.commands.executeCommand(
      "vscode.executeDefinitionProvider", document.uri,
      probePosition(vscode, "create-signature", "Minecraft.cre"),
    );
    result.facadeDefinitions = (facadeDefinitions || []).map((definition) =>
      (definition.targetUri || definition.uri).fsPath);
    assert.ok(result.facadeDefinitions.some((file) => path.resolve(file).toLowerCase()
      .startsWith(path.resolve(config.installedPackage).toLowerCase() + path.sep)),
    "Pylance must resolve Minecraft.create from the installed wheel");

    result.facadeCompletions = {};
    for (const [marker, target, expected] of [
      ["minecraft-completion", "Minecraft.", ["create"]],
      ["facade-completion", "mc.", ["setBlock", "blocks", "close"]],
      ["blocks-completion", "mc.blocks.", ["setBlock"]],
    ]) {
      const items = await waitForProvider(
        () => vscode.commands.executeCommand(
          "vscode.executeCompletionItemProvider", document.uri,
          probePosition(vscode, marker, target), undefined, 100,
        ),
        (value) => expected.every((name) => (value?.items || []).some((item) => labelOf(item) === name)),
        "Required facade completions were absent: " + marker,
      );
      result.facadeCompletions[marker] = items.items.map(labelOf);
    }

    result.signatures = {};
    for (const [marker, target, names] of [
      ["create-signature", "Minecraft.create(", ["ip", "port", "token", "world", "timeout", "coordinates"]],
      ["root-signature", "mc.setBlock(", ["x", "y", "z", "block", "data"]],
      ["blocks-signature", "mc.blocks.setBlock(", ["x", "y", "z", "block", "data"]],
    ]) {
      const help = await waitForProvider(
        () => vscode.commands.executeCommand(
          "vscode.executeSignatureHelpProvider", document.uri,
          probePosition(vscode, marker, target), "(",
        ),
        (value) => !!value?.signatures?.length,
        "Signature help was absent: " + marker,
      );
      const signature = signatureRecord(help);
      result.signatures[marker] = signature;
      assert.deepEqual(signature.parameters.map(parameterName).filter(Boolean), names,
        "Unexpected parameters in " + marker);
      if (marker === "create-signature") {
        assert.match(signature.label, /port[^]*,\s*\*,\s*token/,
          "create must advertise keyword-only token/world/timeout/coordinates");
      } else {
        assert.match(signature.parameters.at(-1), /^data\s*:[^]*=\s*0\s*$/,
          "setBlock must advertise default data=0");
      }
    }

    result.diagnostics = vscode.languages.getDiagnostics(document.uri)
      .map((item) => ({ message: item.message, code: item.code }));
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
  assert.equal(process.argv[2], "--prepare",
    "Usage: node run.js --prepare [path-to-venv-python]");
  process.stdout.write(JSON.stringify(prepare(process.argv[3]), null, 2) + "\n");
}

"use strict";

// Runs in a separate real VS Code extension host, against the installed wheel.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "../../..");
const workspace = path.join(root, ".work/ide-v031-workspace");
const resultPath = path.join(root, ".work/ide-v031-results.json");
const configPath = path.join(workspace, "config.json");
const probePath = path.join(workspace, "valid_probe.py");
const wrongPath = path.join(workspace, "wrong_probe.py");
const probe = [
  "from typing import TYPE_CHECKING",
  "from minebridge import Minecraft, effects, entity, errors, items, selector",
  "",
  "selected = selector.playerByName('YourNick')  # named-factory",
  "blocked_error = errors.PeacefulSpawnError  # peaceful-class",
  "",
  "if TYPE_CHECKING:",
  "    mc = Minecraft.create('localhost', 4712)",
  "    mc.players.giveItem(selected, items.EMERALD, 3)",
  "    mc.effects.add(selected, effects.SPEED, 100, 200)",
  "    mc.setPos(selected, 0, 80, 0)",
  "    inventory = mc.inventories.ofPlayer(selected)  # named-inventory",
  "    inventory.setItem(0, items.DIAMOND, 1)",
  "    try:",
  "        mc.spawnEntity(0, 80, 0, entity.GIANT)",
  "    except errors.PeacefulSpawnError as blocked:",
  "        print(blocked.code)  # peaceful-instance",
  "",
].join("\n");
const wrongProbe = [
  "from minebridge import selector",
  "selector.playerByName(42)  # wrong-name-type",
  "",
].join("\n");

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n", "utf8");
}
function textOf(value) {
  return typeof value === "string" ? value : value && typeof value.value === "string"
    ? value.value : value == null ? "" : JSON.stringify(value);
}
function position(vscode, source, marker, token) {
  const lines = source.split("\n");
  const line = lines.findIndex(value => value.includes("#") && value.slice(value.indexOf("#") + 1).trim() === marker);
  assert.ok(line >= 0, "Missing marker: " + marker);
  const offset = lines[line].indexOf(token);
  assert.ok(offset >= 0, "Missing token: " + token);
  return new vscode.Position(line, offset + token.length);
}
function labelOf(value) { return typeof value.label === "string" ? value.label : value.label.label; }
async function waitFor(query, accepts, message) {
  const deadline = Date.now() + 60000;
  do {
    const value = await query();
    if (accepts(value)) return value;
    await new Promise(resolve => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  assert.fail(message);
}
function definitions(config, values) {
  const files = (values || []).map(value => (value.targetUri || value.uri).fsPath);
  assert.ok(files.length, "Definition provider returned nothing");
  const prefix = path.resolve(config.installedPackage).toLowerCase() + path.sep;
  assert.ok(files.every(file => path.resolve(file).toLowerCase().startsWith(prefix)), "Definition outside installed wheel");
  return files;
}
function prepare(pythonArgument, wheelArgument) {
  const python = path.resolve(pythonArgument || path.join(root, ".venv-v031-314/Scripts/python.exe"));
  const wheel = path.resolve(wheelArgument || path.join(root, "dist/v0.3.1/minebridge-0.3.1-py3-none-any.whl"));
  assert.ok(fs.existsSync(python), "Install the final wheel in the clean interpreter first");
  assert.ok(fs.existsSync(wheel), "Missing frozen final wheel");
  const located = spawnSync(python, ["-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], {
    cwd: root, encoding: "utf8", windowsHide: true, timeout: 20000,
  });
  assert.equal(located.status, 0, located.stderr || String(located.error));
  const installedPackage = path.join(located.stdout.trim(), "minebridge");
  assert.ok(fs.existsSync(path.join(installedPackage, "py.typed")), "Missing installed typing marker");
  const config = {python, wheel, installedPackage, expectedVersion:"0.3.1"};
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
  });
  fs.writeFileSync(probePath, probe, "utf8");
  fs.writeFileSync(wrongPath, wrongProbe, "utf8");
  writeJson(resultPath, {status:"prepared", config});
  return config;
}
function runtime(config) {
  const script = [
    "import json,socket,sys",
    "from importlib import metadata",
    "attempts=[]",
    "def deny(*args,**kwargs):",
    "    attempts.append('network')",
    "    raise AssertionError('Unexpected network access')",
    "socket.socket.connect=deny",
    "socket.socket.connect_ex=deny",
    "socket.create_connection=deny",
    "import minebridge",
    "from minebridge import selector,errors",
    "selected=selector.playerByName('YourNick')",
    "print(json.dumps({'python':sys.version,'version':minebridge.__version__,",
    "'distributionVersion':metadata.version('minebridge'),'package':minebridge.__file__,",
    "'sysPath':sys.path,'networkAttempts':len(attempts),'selectionType':type(selected).__name__,",
    "'selection':str(selected),'errorCode':errors.PeacefulSpawnError.code}))",
  ].join("\n");
  const child = spawnSync(config.python, ["-I", "-c", script], {
    cwd: workspace, encoding:"utf8", windowsHide:true, timeout:20000,
  });
  assert.equal(child.status, 0, child.stderr || String(child.error));
  const value = JSON.parse(child.stdout);
  assert.equal(value.version, config.expectedVersion);
  assert.equal(value.distributionVersion, config.expectedVersion);
  assert.equal(path.resolve(value.package).toLowerCase(), path.join(config.installedPackage, "__init__.py").toLowerCase());
  assert.equal(value.networkAttempts, 0);
  assert.equal(value.selectionType, "Selector");
  assert.equal(value.selection, "@a[name=YourNick,limit=1]");
  assert.equal(value.errorCode, "PEACEFUL_SPAWN_BLOCKED");
  const source = path.join(root, "python/src").toLowerCase();
  assert.ok(value.sysPath.every(entry => !path.resolve(entry).toLowerCase().startsWith(source)));
  return value;
}

exports.run = async function run() {
  const vscode = require("vscode");
  const result = {status:"running",vscode:vscode.version,extensions:{},completions:{},signatures:{},inferredTypes:{}};
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    result.config = config;
    result.runtime = runtime(config);
    for (const id of ["ms-python.python", "ms-python.vscode-pylance"]) {
      const extension = vscode.extensions.getExtension(id);
      assert.ok(extension, "Missing extension: " + id);
      await extension.activate();
      result.extensions[id] = {version:extension.packageJSON.version,extensionPath:extension.extensionPath};
    }
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(probePath));
    await vscode.window.showTextDocument(document, {preview:false});
    for (const [marker,token,expected,hoverType] of [
      ["named-factory","selector.","playerByName","Selector"],
      ["peaceful-class","errors.","PeacefulSpawnError","PeacefulSpawnError"],
    ]) {
      const completion = await waitFor(() => vscode.commands.executeCommand("vscode.executeCompletionItemProvider",
        document.uri,position(vscode,probe,marker,token),undefined,100),
      value => (value?.items || []).some(item => labelOf(item) === expected), "Missing completion: " + expected);
      const hover = await waitFor(() => vscode.commands.executeCommand("vscode.executeHoverProvider", document.uri,
        position(vscode,probe,marker,token + expected.slice(0,2))),
      values => (values || []).flatMap(item => item.contents.map(textOf)).join("\n").includes(hoverType), "Missing hover: " + expected);
      const definition = await vscode.commands.executeCommand("vscode.executeDefinitionProvider", document.uri,
        position(vscode,probe,marker,token + expected.slice(0,2)));
      result.completions[marker] = {found:expected,completionCount:completion.items.length,
        hover:hover.flatMap(item => item.contents.map(textOf)),definitions:definitions(config,definition)};
      writeJson(resultPath,result);
    }
    const help = await waitFor(() => vscode.commands.executeCommand("vscode.executeSignatureHelpProvider", document.uri,
      position(vscode,probe,"named-factory","selector.playerByName("),"("), value => !!value?.signatures?.length,
    "Missing playerByName signature");
    const signature = help.signatures[help.activeSignature || 0];
    assert.match(signature.label, /name:\s*str/);
    assert.match(signature.label, /->\s*Selector/);
    assert.equal(signature.parameters.length,1);
    result.signatures.playerByName = {label:signature.label,documentation:textOf(signature.documentation),
      definitions:result.completions["named-factory"].definitions};
    for (const [marker,token,type] of [
      ["named-factory","selected","Selector"],
      ["named-inventory","inventory","InventoryRef"],
      ["peaceful-instance","blocked","PeacefulSpawnError"],
    ]) {
      const hover = await waitFor(() => vscode.commands.executeCommand("vscode.executeHoverProvider", document.uri,
        position(vscode,probe,marker,token.slice(0,2))),
      values => (values || []).flatMap(item => item.contents.map(textOf)).join("\n").includes(type), "Missing inferred type: " + type);
      result.inferredTypes[marker] = hover.flatMap(item => item.contents.map(textOf));
      writeJson(resultPath,result);
    }
    const wrong = await vscode.workspace.openTextDocument(vscode.Uri.file(wrongPath));
    await vscode.window.showTextDocument(wrong,{preview:false});
    const wrongLine = position(vscode,wrongProbe,"wrong-name-type","selector.").line;
    const diagnostics = await waitFor(() => vscode.languages.getDiagnostics(wrong.uri),
      values => values.some(item => item.range.start.line === wrongLine &&
        String(typeof item.code === "object" ? item.code.value : item.code) === "reportArgumentType"),
      "Expected wrong-name-type diagnostic missing");
    const describe = item => ({line:item.range.start.line+1,code:typeof item.code === "object" ? item.code.value : item.code,message:item.message});
    result.wrongTypeDiagnostics = diagnostics.map(describe);
    result.probeDiagnostics = vscode.languages.getDiagnostics(document.uri).map(describe);
    assert.equal(result.probeDiagnostics.length,0,"Valid factory usage has diagnostics");
    result.status = "passed";
  } catch (error) {
    result.status = "failed";
    result.error = error.stack || String(error);
    throw error;
  } finally { writeJson(resultPath,result); }
};

if (require.main === module) {
  assert.equal(process.argv[2],"--prepare","Usage: node run.js --prepare [python] [wheel]");
  process.stdout.write(JSON.stringify(prepare(process.argv[3],process.argv[4]),null,2) + "\n");
}

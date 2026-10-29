"""Final0.3 installed-wheel acceptance, restart/config check and real0.2.1 baseline."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from smoke_i05 import I05Harness
from smoke_i03 import I03Paper
sys.path.insert(0,str(ROOT/"integration/tests"))
from conftest import require_port_free,sha256
from game_client import GameClient
from observer_client import ObserverClient
from v03_i05_probe_support import probe


def save(path,value):path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")


class ReleaseHarness(I05Harness):
    def __init__(self,*,number,baseline=False,port=None):
        release=ROOT/("dist/v0.2.1" if baseline else "dist/v0.3")
        version="0.2.1" if baseline else "0.3.0"
        python=ROOT/(".venv-v021-314" if baseline else ".venv-v03-314")/"Scripts/python.exe"
        super().__init__(release/f"minebridge-paper-{version}.jar",
            release/f"minebridge-{version}-py3-none-any.whl",python,number=number,port=port)
        self.stage="V03-I05";self.world_name="v03-release-"+str(number)
        self.workspace=ROOT/".work"/("v03-i05-"+self.run_id);self.server=self.workspace/"server"
        self.artifacts=ROOT/"integration/artifacts"/("v03-i05-"+self.run_id)
        self.baseline=baseline

    def prepare(self):
        super().prepare()
        self.manifest.update(stage="V03-I05",contract="v0.3/protocol-2.0",
            scope="Final installed artifacts; local2process/2gameclients; not LAN or classroom-scale",
            baseline021=self.baseline)
        scripts=[Path(__file__),ROOT/"integration/tests/v03_i05_worker.py",
            ROOT/"integration/tests/v03_i05_acceptance.py",ROOT/"integration/tests/v03_i05_probe.py",
            ROOT/"integration/tests/v03_i05_probe_support.py",ROOT/"integration/tests/game_client.py",
            ROOT/"examples/buffered_blocks.py"]
        self.manifest["scripts"]={str(p.relative_to(ROOT)):sha256(p) for p in scripts}
        self.save_manifest()


class Worker:
    def __init__(self,harness,player=None,*,logging=False):
        self.events=queue.Queue();self.stderr=[];self.pending=None;self.sequence=0;self.closed=None
        env=os.environ.copy();env.pop("MINEBRIDGE_TOKEN",None);env.pop("PYTHONPATH",None)
        command=[str(harness.python),"-I",str(ROOT/"integration/tests/v03_i05_worker.py"),"--port",str(harness.port)]
        if player:command.extend(["--player",player])
        if logging:command.append("--logging")
        self.process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding="utf-8",creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        def output():
            for line in self.process.stdout:
                try:self.events.put(json.loads(line))
                except ValueError:self.events.put({"type":"fatal","line":line[:200]})
            self.events.put({"type":"eof"})
        def errors():
            for line in self.process.stderr:
                if len(self.stderr)<80:self.stderr.append(line)
        self.threads=[threading.Thread(target=output,daemon=True),threading.Thread(target=errors,daemon=True)]
        for thread in self.threads:thread.start()
        try:
            row=self.event();assert row["type"]=="ready",row
            self.context=row["result"]
            assert self.context["isolated"] and self.context["version"]=="0.3.0"
            assert "site-packages" in self.context["package"] and self.context["tokenEnvironmentAbsent"]
        except BaseException:self.abort();raise

    def event(self,timeout=90):
        try:row=self.events.get(timeout=timeout)
        except queue.Empty:raise AssertionError("Final installed worker timeout: "+"".join(self.stderr)[-1500:]) from None
        assert row["type"] not in ("fatal","eof"),(row,self.stderr)
        return row

    def start(self,op,**params):
        assert self.pending is None
        self.sequence+=1;self.pending=self.sequence
        self.process.stdin.write(json.dumps({"id":self.sequence,"op":op,**params})+"\n");self.process.stdin.flush()

    def result(self,*,error=None):
        row=self.event();assert row["id"]==self.pending,row;self.pending=None
        if error:
            assert row.get("error",{}).get("type")==error,row
            return row["error"]
        assert "error" not in row,row
        return row["result"]

    def call(self,op,*,error=None,**params):self.start(op,**params);return self.result(error=error)

    def close(self,*,remote=False):
        if self.process.poll() is None:
            self.closed=self.call("close")
            assert not self.closed["remainingThreads"],self.closed
            failure=self.closed["closeError"]
            assert failure is None or remote and failure["type"]=="ConnectionError",self.closed
            self.process.stdin.close();self.process.wait(timeout=15)
        assert self.process.returncode==0 and not self.stderr,self.stderr
        for thread in self.threads:thread.join(timeout=5)
        for pipe in (self.process.stdout,self.process.stderr):
            if not pipe.closed:pipe.close()
        return self.closed

    def abort(self):
        if self.process.poll() is None:self.process.kill();self.process.wait(timeout=10)
        for thread in self.threads:thread.join(timeout=5)
        for pipe in (self.process.stdin,self.process.stdout,self.process.stderr):
            if pipe is not None and not pipe.closed:pipe.close()


def check_inputs(harness):
    for row in harness.manifest["artifacts"].values():assert sha256(Path(row["path"]))==row["sha256"],row
    for rel,digest in harness.manifest["scripts"].items():assert sha256(ROOT/rel)==digest,rel


def run():
    main=ReleaseHarness(number=1);main.prepare()
    harnesses=[main];games=[];workers=[]
    summary={"allPassed":False,"manifest":str(main.artifacts/"manifest.json"),"additionalManifests":[]}
    def check(name,result):
        main.manifest["checks"].append({"name":name,"passed":True,"result":result})
        main.save_manifest();print(json.dumps({"passed":name}),flush=True)
    print(json.dumps({"phase":"main-server-start","workspace":str(main.workspace),"runId":main.run_id}),flush=True)
    try:
        with I03Paper(main,control=True,mode="v03-i05-combined") as paper:
            paper.wait_ready()
            from v03_i05_acceptance import acceptance
            result=acceptance(main,paper,Worker,games,workers,check)
            main.manifest["modes"].append(paper.finish());require_port_free(main.game_port)
            watch=result["watch"]
            disconnected=watch.call("waitRunEnd")
            assert disconnected["runErrors"] and disconnected["runErrors"][-1]["type"]=="ConnectionError",disconnected
            watch.close(remote=True)
            check("server-shutdown-wakes-live-reader-with-connection-error-and-clean-close",disconnected)
        config=(main.server/"plugins/Minebridge/config.yml").read_bytes()
        # Same bridge port/config bytes, fresh level-name and UUID; no test-control service.
        fresh=ReleaseHarness(number=2,port=main.port);fresh.prepare();harnesses.append(fresh)
        summary["additionalManifests"].append(str(fresh.artifacts/"manifest.json"))
        assert (fresh.server/"plugins/Minebridge/config.yml").read_bytes()==config
        print(json.dumps({"phase":"fresh-world-start","workspace":str(fresh.workspace)}),flush=True)
        with I03Paper(fresh,control=False,mode="v03-i05-fresh-world") as paper:
            paper.wait_ready();observer=ObserverClient(paper,fresh.artifacts/"observer.json");case=observer.case_id()
            api=probe(fresh,fresh.python,"fresh")
            assert api["block"]==4 and api["world"]["name"]==fresh.world_name
            assert api["world"]["uuid"]!=result["world"]["uuid"]
            stats=observer.result(case,"status");assert not stats["controlEnabled"]
            # Hold a different cell in the same chunk after the SDK closes.
            # setup clears only its listed position; the target (0,0,0) is untouched.
            held=observer.result(case,"setup",api["world"]["uuid"],"1,0,1")
            native=observer.result(case,"read",api["world"]["uuid"],0,0,0)
            assert native["key"]=="minecraft:cobblestone"
            observer.result(case,"cleanup")
            record={"api":api,"native":native,"heldChunks":held["chunks"],"configSha256":sha256(fresh.server/"plugins/Minebridge/config.yml"),"stats":stats}
            fresh.manifest["checks"].append({"name":"fresh-world-identical-config-two-argument-create","passed":True,"result":record})
            fresh.manifest["modes"].append(paper.finish());require_port_free(fresh.game_port)
            check("fresh-world-and-plugin-restart-with-identical-config-and-two-argument-create",record)
        check_inputs(fresh);fresh.manifest["allPassed"]=True;fresh.save_manifest()

        # True baseline uses BOTH old plugin and old SDK, never mislabeled client-only comparison.
        baseline=ReleaseHarness(number="baseline021",baseline=True);baseline.prepare();harnesses.append(baseline)
        summary["additionalManifests"].append(str(baseline.artifacts/"manifest.json"))
        print(json.dumps({"phase":"true-021-baseline-start","workspace":str(baseline.workspace)}),flush=True)
        baseline_games=[]
        with I03Paper(baseline,control=True,mode="v03-i05-true-021-baseline") as paper:
            paper.wait_ready();observer=ObserverClient(paper,baseline.artifacts/"observer.json");case=observer.case_id()
            protocol=observer.result(case,"gameProtocol")
            world=next(w for w in observer.result(case,"worlds")["worlds"] if w["name"]==baseline.world_name)
            for index,name in enumerate(("BaseAlice","BaseBob")):
                game=GameClient(baseline.game_port,name,protocol);games.append(game);baseline_games.append(game);game.wait_ready()
                observer.result(case,"playerPlace",name,world["uuid"],128+index*32,210,128)
            observer.result(case,"setup",world["uuid"],"256,209,128","272,209,128","256,209,144","272,209,144")
            timings=probe(baseline,baseline.python,"benchmark",version="0.2.1")
            assert timings["info"]["version"]=="0.2.1"
            native=observer.result(case,"read",world["uuid"],263,210,159);assert native["key"]=="minecraft:cobblestone"
            observer.result(case,"cleanup")
            baseline.manifest["checks"].append({"name":"true-021-plugin-and-sdk-buffered-block-baseline","passed":True,"result":timings})
            for game in baseline_games:assert not game.errors;game.close()
            baseline.manifest["modes"].append(paper.finish());require_port_free(baseline.game_port)
        check_inputs(baseline);baseline.manifest["allPassed"]=True;baseline.save_manifest()
        def medians(rows):return {str(n):statistics.median(row["seconds"] for row in rows if row["blocks"]==n) for n in (100,1000)}
        paired_rows=lambda version:[row for run in result["pairedFresh"] if run["info"]["version"]==version for row in run["measurements"]]
        summary["performance"]={"persistentFinalSDKAfterEvents":result["finalTimings"],"pairedFreshSDKRuns":result["pairedFresh"],
            "oldPluginOldSDK":timings["measurements"],"medians":{"persistentFinalAfterEvents":medians(result["finalTimings"]),
            "freshFinal":medians(paired_rows("0.3.0")),"freshOldClientOnFinal":medians(paired_rows("0.2.1")),"true021":medians(timings["measurements"])},
            "includesFlush":True,"logging":False,"eventFloodActive":False,"testControl":True,"chunksPreloadedAndHeld":True,
            "freshProcessUntimedWarmupBlocks":1000,"freshFinalSdkOrder":["0.3.0","0.2.1","0.2.1","0.3.0"],
            "repeatsPerCount":{"pairedEachSDK":6,"true021":3,"persistentPostEvents":3}}
        check("true-021-plugin-sdk-baseline-versus-final-acknowledged-block-measurements",summary["performance"])
        for harness in harnesses:check_inputs(harness)
        main.manifest["allPassed"]=summary["allPassed"]=True
    finally:
        for game in games:game.close()
        for worker in workers:worker.abort()
        for harness in harnesses:harness.save_manifest()
        main.manifest["finalGameClients"]=[game.evidence() for game in games];main.save_manifest()
        save(ROOT/".work/v03-i05-paper-results.json",summary)
    return summary


if __name__=="__main__":print(json.dumps(run(),indent=2))

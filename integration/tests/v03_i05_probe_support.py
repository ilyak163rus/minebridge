"""Parent-side isolated probes; none imports source Minebridge."""

import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def environment():
    env=os.environ.copy();env.pop("MINEBRIDGE_TOKEN",None);env.pop("PYTHONPATH",None)
    return env


def command(harness,python,op,version,marker):
    return [str(python),"-I",str(ROOT/"integration/tests/v03_i05_probe.py"),op,
            "--port",str(harness.port),"--expect-version",version,"--marker",marker]


def probe(harness,python,op,*,version="0.3.0",marker="i05-probe"):
    result=subprocess.run(command(harness,python,op,version,marker),cwd=ROOT,env=environment(),
        capture_output=True,text=True,encoding="utf-8",timeout=100,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    assert result.returncode==0 and not result.stderr,(result.stdout,result.stderr)
    value=json.loads(result.stdout)
    assert value["info"]["isolated"] and "site-packages" in value["info"]["package"]
    return value


def legacy_example(harness,python):
    result=subprocess.run([str(python),"-I","-X","utf8",str(ROOT/"examples/buffered_blocks.py"),
        "--host","127.0.0.1","--port",str(harness.port),"--x","300","--y","210","--z","140","--count","10"],
        cwd=ROOT,env=environment(),capture_output=True,text=True,encoding="utf-8",timeout=30,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    assert result.returncode==0 and not result.stderr,(result.stdout,result.stderr)
    assert "10" in result.stdout
    return {"python":str(python),"exitCode":result.returncode,"stdout":result.stdout}


def short_exit(harness,paper,observer,case,game):
    process=subprocess.Popen(command(harness,harness.python,"short","0.3.0","i05-normal-exit"),
        cwd=ROOT,env=environment(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try:
        ready=json.loads(process.stdout.readline());assert ready["type"]=="ready"
        sid=ready["info"]["sessionId"]
        observer.result(case,"gateArm",sid,2)
        process.stdin.write("\n");process.stdin.flush()
        status=observer.await_value(case,"gateStatus",(sid,2),lambda row:row["state"]=="GATED")
        assert process.poll() is None,"Normal exit abandoned an accepted gated write"
        observer.result(case,"gateRelease",sid,2)
        stdout,stderr=process.communicate(timeout=30)
        assert process.returncode==0 and not stderr,(stdout,stderr)
        chat=game.wait_chat("i05-normal-exit")
        return {"installed":ready["info"],"gate":status,"chat":chat,"exitCode":process.returncode}
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)
        for pipe in (process.stdin,process.stdout,process.stderr):
            if pipe is not None and not pipe.closed:pipe.close()

#!/usr/bin/env python3
"""FIFO queue lock for a shared resource (a local stack, a test DB, a browser
profile, a delivery channel), so parallel agents never collide and waiters are
served in arrival order.

    python scripts/stack_lock.py run [--name stack] [--wait 3600] [--stale 5400] -- <command...>
    python scripts/stack_lock.py status [--name stack]

Each waiter drops a ticket file in <lockdir>/smekit-<name>.queue/. The oldest
ticket whose process is alive holds the lock. Tickets of dead processes are
removed; a live ticket older than --stale seconds is reported but never stolen.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time


def lock_path(name):
    return os.path.join(os.environ.get("SMEKIT_LOCK_DIR", tempfile.gettempdir()), f"smekit-{name}.queue")


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def tickets(path):
    out = []
    for f in sorted(os.listdir(path)) if os.path.isdir(path) else []:
        try:
            with open(os.path.join(path, f), encoding="utf-8") as fh:
                out.append((f, json.load(fh)))
        except (OSError, ValueError):
            continue
    return out


def _mine(path):
    return [f for f, t in tickets(path) if t.get("pid") == os.getpid()]


def acquire(path, owner, wait=3600, stale=5400, poll=5):
    """Queue up and wait until this process's ticket is first. True = holding."""
    os.makedirs(path, exist_ok=True)
    mine = _mine(path)
    name = mine[0] if mine else f"{time.time_ns():020d}-{os.getpid()}.json"
    if not mine:
        with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "owner": owner, "since": time.time()}, fh)
    deadline = time.time() + wait
    while True:
        queue = tickets(path)
        for f, t in queue:  # drop tickets of processes that died without releasing
            if f != name and not pid_alive(t.get("pid")):
                try:
                    os.remove(os.path.join(path, f))
                except OSError:
                    pass
        queue = [q for q in tickets(path)]
        if queue and queue[0][0] == name:
            return True
        if time.time() >= deadline:
            try:
                os.remove(os.path.join(path, name))
            except OSError:
                pass
            return False
        head = queue[0][1] if queue else {}
        age = int(time.time() - head.get("since", time.time()))
        note = " (older than --stale; check that process)" if age > stale else ""
        print(f"[stack_lock] waiting: {len(queue) - 1} ahead, held by {head.get('owner')} for {age}s{note}", flush=True)
        time.sleep(poll)


def release(path):
    for f in _mine(path):
        try:
            os.remove(os.path.join(path, f))
        except OSError:
            pass


def read(path):
    q = tickets(path)
    return {"holder": q[0][1], "waiting": len(q) - 1} if q else {"free": True}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("run", "status"))
    ap.add_argument("--name", default="stack")
    ap.add_argument("--owner", default=os.environ.get("SMEKIT_AGENT", "agent"))
    ap.add_argument("--wait", type=int, default=3600)
    ap.add_argument("--stale", type=int, default=5400)
    a = ap.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    path = lock_path(a.name)
    if a.action == "status":
        print(json.dumps(read(path)))
        return 0
    if not cmd:
        ap.error("run needs a command after --")
    if not acquire(path, a.owner, a.wait, a.stale):
        print(f"[stack_lock] gave up after {a.wait}s", file=sys.stderr)
        return 3
    try:
        return subprocess.run(cmd).returncode
    finally:
        release(path)


if __name__ == "__main__":
    sys.exit(main())

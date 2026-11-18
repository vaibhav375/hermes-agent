"""TEMPORARY wine2e diagnostics for two Windows flakes (never merged)."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

from tests.waiting import wait_until

pytestmark = pytest.mark.platforms("windows")
ROOT = Path(__file__).resolve().parents[2]


def test_probe_identify_cold_cost(tmp_path):
    from gateway.control_socket import identify_gateway
    from tests.gateway.test_control_socket_windows_live import _CHILD_CODE, _kill_tree, _readline

    t = time.monotonic()
    out = subprocess.run(
        [sys.executable, "-c", "import time;t=time.monotonic();"
         "from hermes_cli.version_info import get_code_identity;get_code_identity();"
         "print(round(time.monotonic()-t,3))"],
        capture_output=True, text=True, cwd=str(ROOT), check=False)
    print(f"PROBE get_code_identity in a fresh process: {out.stdout.strip()}s (spawn+all {time.monotonic()-t:.2f}s)")
    for i in range(6):
        home = tmp_path / f"h{i}"
        home.mkdir()
        proc = subprocess.Popen([sys.executable, "-c", _CHILD_CODE, str(ROOT), str(home)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(ROOT))
        line = _readline(proc.stdout).strip()
        t = time.monotonic()
        first = identify_gateway(home, timeout=60)
        cold = time.monotonic() - t
        t = time.monotonic()
        second = identify_gateway(home, timeout=60)
        warm = time.monotonic() - t
        print(f"PROBE identify #{i}: {line} launcher={proc.pid} cold={cold:.2f}s warm={warm:.3f}s "
              f"ok={first is not None}/{second is not None}")
        _kill_tree(proc)


_BACKUP_CHILD = """
    import importlib, os, sys
    from pathlib import Path
    from argparse import Namespace
    from hermes_cli import backup

    def pause_copy(src, dst, **_kwargs):
        dst.write_bytes(b'\\\\0' * 4096)
        print('READY ' + str(os.getpid()) + ' ' + str(dst), flush=True)
        sys.stdin.read(1)
        (Path(sys.argv[1]) / 'child-saw-eof').write_text('x')
        return False

    backup._safe_copy_db = pause_copy
    setattr(importlib.import_module(sys.argv[3]), sys.argv[4], pause_copy)
    backup._run_backup_locked(Namespace(output=sys.argv[2]), Path(sys.argv[1]))
"""


def test_probe_backup_kill_reaches_the_backup_process(tmp_path):
    from tests.fixtures.storage_holder import store_copy_seam
    from tests.hermes_cli.test_backup_staging_recovery import _home

    module, name = store_copy_seam()
    tally = {"real_pid_differs": 0, "survived_kill": 0, "saw_eof": 0, "stage_gone": 0}
    for i in range(20):
        home = _home(tmp_path / f"home{i}")
        proc = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(_BACKUP_CHILD), str(home), str(home / "b.zip"),
             module.__name__, name],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "HERMES_HOME": str(home)}, creationflags=subprocess.CREATE_NO_WINDOW)
        line = proc.stdout.readline().split()
        real_pid, snapshot = int(line[1]), Path(line[2])
        tally["real_pid_differs"] += real_pid != proc.pid
        proc.kill()
        proc.communicate(timeout=30)
        tally["survived_kill"] += psutil.pid_exists(real_pid)
        wait_until(lambda: not psutil.pid_exists(real_pid), timeout=30, what="real backup pid gone")
        tally["saw_eof"] += (home / "child-saw-eof").exists()
        tally["stage_gone"] += not snapshot.parent.exists()
    print("PROBE backup kill tally over 20:", tally)

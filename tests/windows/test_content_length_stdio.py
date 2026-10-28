"""Guard Content-Length byte framing through the real daemon-backed entrypoint.

Usage: python tests/windows/test_content_length_stdio.py <binary> [--state-dir PATH]
Uses a private cache AND daemon runtime; never the operator's graph/daemon.
If TEMP has cross-account-writable ancestors, --state-dir names an explicit
owner-private application-validation directory. Keep its evidence for inspection.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def framed(obj):
    # CRLF inside JSON whitespace detects translated reads as well as writes.
    body = json.dumps(obj, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode("utf-8")
    return ("Content-Length: %d\r\n\r\n" % len(body)).encode("ascii") + body


def responses(data):
    messages = []
    while data:
        head, delimiter, rest = data.partition(b"\r\n\r\n")
        if not delimiter or b"\r\r\n" in head:
            raise AssertionError("Content-Length response header is missing or CRLF-translated")
        fields = dict(line.split(b":", 1) for line in head.split(b"\r\n"))
        size = int(fields[b"Content-Length"].strip())
        if len(rest) < size:
            raise AssertionError("truncated Content-Length response body")
        messages.append(json.loads(rest[:size].decode("utf-8")))
        data = rest[size:]
    return messages


def main(binary, state_dir=None):
    binary = str(Path(binary).resolve())
    with tempfile.TemporaryDirectory(prefix="cbm-framed-stdio-") as tmp:
        work = Path(tmp)
        state = Path(state_dir).resolve() / work.name if state_dir else work
        # Inherit only toolchain/OS essentials, not API credentials or app state.
        keep = {"PATH", "PATHEXT", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE"}
        env = {key: value for key, value in os.environ.items() if key in keep}
        for name, path in {
            "HOME": state / "home", "USERPROFILE": state / "home",
            "LOCALAPPDATA": state / "local", "APPDATA": state / "roaming",
            "CBM_CACHE_DIR": state / "cache", "CBM_RUNTIME_DIR": state / "runtime",
            "TMP": work / "tmp", "TEMP": work / "tmp", "TMPDIR": work / "tmp",
        }.items():
            path.mkdir(parents=True, exist_ok=True)
            env[name] = str(path)
        payload = framed({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "windows-framing-guard", "version": "1"}}})
        payload += framed({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        payload += framed({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        try:
            proc = subprocess.run([binary], input=payload, capture_output=True, env=env,
                                  cwd=state, timeout=60)
            messages = responses(proc.stdout)
            by_id = {msg.get("id"): msg for msg in messages}
            if proc.returncode != 0 or set(by_id) != {1, 2}:
                raise AssertionError("framed initialize/tools/list failed (exit=%s, ids=%s, stderr=%r)" %
                                     (proc.returncode, sorted(by_id), proc.stderr[-500:]))
            if any("error" in msg for msg in messages):
                raise AssertionError("framed MCP request returned an error")
            if not by_id[2].get("result", {}).get("tools"):
                raise AssertionError("framed tools/list returned no tools")
            print("PASS: daemon-backed Content-Length input/output preserves exact CRLF byte counts")
        finally:
            # This namespace was created by this test, not the operator's daemon.
            stop = subprocess.run([binary, "daemon", "stop"], capture_output=True,
                                  env=env, cwd=state, timeout=30)
            if (stop.returncode != 0 and sys.exc_info()[0] is None
                    and b"not running" not in (stop.stdout + stop.stderr).lower()):
                raise AssertionError("could not retire the fixture daemon: %r" % stop.stderr[-300:])
            # The stop acknowledgement precedes Windows closing its log/CWD
            # handles. Remove only this fixture, with a bounded sharing-lock wait.
            deadline = time.monotonic() + 10
            while work.exists():
                try:
                    shutil.rmtree(work)
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--state-dir", help="explicit owner-private persistent validation state root")
    args = parser.parse_args()
    raise SystemExit(main(args.binary, args.state_dir))

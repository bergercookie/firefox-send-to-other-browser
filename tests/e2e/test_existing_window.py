"""A real Chromium-family browser that is already running must receive the URLs as
tabs of its existing window, not in a new window.

Skipped unless a Chromium/Chrome binary (CHROMIUM_BIN, or on PATH / under
/opt/pw-browsers) and Xvfb are available.
"""

import glob
import json
import os
import shutil
import socket
import stat
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
import send_to_other_browser as host
import websocket


def find_chromium() -> str | None:
    candidates: list[str | None] = [os.environ.get("CHROMIUM_BIN")]
    candidates += [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser")]
    candidates += glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
    return next((c for c in candidates if c and os.access(c, os.X_OK)), None)


CHROMIUM = find_chromium()
pytestmark = pytest.mark.skipif(
    not CHROMIUM or not shutil.which("Xvfb"), reason="needs a Chromium/Chrome binary and Xvfb"
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def windows_and_tabs(port: int) -> dict[int, list[str]]:
    version = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version"))
    ws = websocket.create_connection(version["webSocketDebuggerUrl"])
    pages = [
        t
        for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
        if t["type"] == "page"
    ]
    windows: dict[int, list[str]] = {}
    for i, page in enumerate(pages):
        ws.send(
            json.dumps(
                {
                    "id": i,
                    "method": "Browser.getWindowForTarget",
                    "params": {"targetId": page["id"]},
                }
            )
        )
        while (reply := json.loads(ws.recv())).get("id") != i:
            pass
        windows.setdefault(reply["result"]["windowId"], []).append(page["url"])
    ws.close()
    return windows


def test_urls_open_as_tabs_in_the_running_window(tmp_path: Path) -> None:
    port = free_port()
    flags = f"--no-sandbox --user-data-dir={tmp_path}/profile --remote-debugging-port={port} --remote-allow-origins=* --no-first-run"
    # Stands in for `google-chrome` on PATH, adding only flags the sandboxed test environment needs.
    wrapper = tmp_path / "bin" / "google-chrome"
    wrapper.parent.mkdir()
    wrapper.write_text(f'#!/bin/sh\nexec "{CHROMIUM}" {flags} "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    xvfb = subprocess.Popen(
        ["Xvfb", ":97", "-screen", "0", "1280x800x24"], stderr=subprocess.DEVNULL
    )
    env = {**os.environ, "DISPLAY": ":97"}
    first: subprocess.Popen[bytes] | None = None
    try:
        time.sleep(1)
        first = subprocess.Popen(
            [str(wrapper), "about:blank"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version")
                break
            except OSError:
                time.sleep(0.2)

        browsers = host.discover_browsers(path=str(wrapper.parent))
        urls = ["http://127.0.0.1:1/a", "http://127.0.0.1:1/b"]
        old_env = dict(os.environ)
        os.environ.update(env)
        try:
            reply = host.handle_request(
                {"action": "send", "browser": "chrome", "urls": urls}, discover=lambda: browsers
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        assert reply["ok"]

        deadline = time.time() + 20
        while time.time() < deadline:
            windows = windows_and_tabs(port)
            if sum(len(v) for v in windows.values()) >= 3:
                break
            time.sleep(0.3)
        assert len(windows) == 1, windows
        assert sorted(next(iter(windows.values()))) == sorted(["about:blank", *urls])
    finally:
        if first:
            first.kill()
        xvfb.kill()

#!/usr/bin/env python3
"""Native messaging host for the "Send to Other Browser" Firefox extension.

Speaks the WebExtensions native messaging protocol on stdin/stdout (a 4-byte
native-endian length followed by UTF-8 JSON) and opens URLs in another
Chromium-family browser installed on this machine.

Requests:
    {"action": "ping"}
    {"action": "list"}
    {"action": "send", "browser": "<id>", "urls": ["https://..."]}
Every response has "ok": true/false, plus "error" when false.

Set SEND_TO_OTHER_BROWSER_PATH to a ':'-separated list of directories that are
searched for browser executables before $PATH (used by the tests).
"""

import json
import os
import shutil
import struct
import subprocess
import sys
from collections.abc import Callable
from collections.abc import Mapping
from typing import IO
from typing import Any
from urllib.parse import urlsplit

VERSION = "0.1.0"
MAX_URLS = 500
MAX_MESSAGE_BYTES = 1024 * 1024  # Firefox never sends more than 4 GiB; we are stricter.

Browser = dict[str, str]

# id -> (display name, executable names tried in order)
BROWSERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "vivaldi": ("Vivaldi", ("vivaldi", "vivaldi-stable", "vivaldi.vivaldi-stable")),
    "chrome": ("Google Chrome", ("google-chrome", "google-chrome-stable")),
    "chromium": ("Chromium", ("chromium", "chromium-browser")),
    "brave": ("Brave", ("brave-browser", "brave")),
    "edge": ("Microsoft Edge", ("microsoft-edge", "microsoft-edge-stable")),
}


# Where browsers usually live. Added after $PATH because a host started by the
# xdg-desktop-portal (the snap Firefox case) gets a minimal environment, not the
# user's shell PATH.
FALLBACK_DIRS = (
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/snap/bin",
    "/opt/vivaldi",
    "/opt/google/chrome",
    "/opt/brave.com/brave",
    "/opt/microsoft/msedge",
    "~/.local/bin",
)


def search_path(env: Mapping[str, str] | None = None) -> str:
    source: Mapping[str, str] = os.environ if env is None else env
    extra = [p for p in source.get("SEND_TO_OTHER_BROWSER_PATH", "").split(os.pathsep) if p]
    fallback = [os.path.expanduser(d) for d in FALLBACK_DIRS]
    return os.pathsep.join([*extra, source.get("PATH", os.defpath), *fallback])


def discover_browsers(path: str | None = None) -> list[Browser]:
    """Return [{"id", "name", "path"}] for every supported browser found."""
    path = search_path() if path is None else path
    found: list[Browser] = []
    for browser_id, (name, executables) in BROWSERS.items():
        for exe in executables:
            resolved = shutil.which(exe, path=path)
            if resolved:
                found.append({"id": browser_id, "name": name, "path": resolved})
                break
    return found


def is_web_url(url: object) -> bool:
    if not isinstance(url, str) or not url or len(url) > 32768:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _spawn(argv: list[str]) -> None:
    # Detached, so the browser outlives this short-lived host. A running
    # Chromium-family browser hands the URLs to the existing instance, which
    # opens them as new tabs in its most recent window and the child exits
    # straight away. Never add --new-window here: that is what would open a
    # separate window per send.
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def handle_request(
    request: object,
    discover: Callable[[], list[Browser]] = discover_browsers,
    spawn: Callable[[list[str]], object] = _spawn,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {"ok": False, "error": "request must be a JSON object"}
    action = request.get("action")

    if action == "ping":
        return {"ok": True, "version": VERSION}

    if action == "list":
        return {"ok": True, "browsers": discover()}

    if action == "send":
        urls = request.get("urls")
        if not isinstance(urls, list) or not urls:
            return {"ok": False, "error": "'urls' must be a non-empty list"}
        if len(urls) > MAX_URLS:
            return {"ok": False, "error": f"too many urls (max {MAX_URLS})"}
        valid = [u for u in urls if is_web_url(u)]
        skipped = [u for u in urls if not is_web_url(u)]
        if not valid:
            return {"ok": False, "error": "no valid http(s) urls", "skipped": skipped}
        browsers = {b["id"]: b for b in discover()}
        browser_id = request.get("browser")
        target = browsers.get(browser_id) if isinstance(browser_id, str) else None
        if target is None:
            return {
                "ok": False,
                "error": f"browser {request.get('browser')!r} not found on this system",
            }
        try:
            spawn([target["path"], *valid])
        except OSError as exc:
            return {"ok": False, "error": f"failed to start {target['name']}: {exc}"}
        return {"ok": True, "opened": len(valid), "skipped": skipped, "browser": target["id"]}

    return {"ok": False, "error": f"unknown action {action!r}"}


def read_message(stream: IO[bytes]) -> Any:
    """Read one framed message; None on clean EOF."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("=I", header)
    if length > MAX_MESSAGE_BYTES:
        raise ValueError(f"message too large: {length} bytes")
    body = stream.read(length)
    if len(body) < length:
        raise ValueError("truncated message")
    return json.loads(body.decode("utf-8"))


def write_message(stream: IO[bytes], message: object) -> None:
    body = json.dumps(message).encode("utf-8")
    stream.write(struct.pack("=I", len(body)) + body)
    stream.flush()


def serve(stdin: IO[bytes], stdout: IO[bytes], **kwargs: Any) -> int:
    """Answer requests until the browser closes the pipe."""
    while True:
        try:
            request = read_message(stdin)
        except (ValueError, json.JSONDecodeError) as exc:
            write_message(stdout, {"ok": False, "error": f"bad message: {exc}"})
            return 1
        if request is None:
            return 0
        write_message(stdout, handle_request(request, **kwargs))


def main() -> int:
    return serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    sys.exit(main())

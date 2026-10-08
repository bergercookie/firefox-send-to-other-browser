import io
import json
import os
import stat
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))

import install  # noqa: E402
import send_to_other_browser as host  # noqa: E402


def make_exe(directory, name):
    path = Path(directory) / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class DiscoverTest(unittest.TestCase):
    def test_finds_installed_browsers_only(self):
        with tempfile.TemporaryDirectory() as d:
            vivaldi = make_exe(d, "vivaldi-stable")
            chrome = make_exe(d, "google-chrome")
            found = host.discover_browsers(path=d)
        self.assertEqual(
            found,
            [
                {"id": "vivaldi", "name": "Vivaldi", "path": vivaldi},
                {"id": "chrome", "name": "Google Chrome", "path": chrome},
            ],
        )

    def test_finds_snap_vivaldi(self):
        with tempfile.TemporaryDirectory() as d:
            exe = make_exe(d, "vivaldi.vivaldi-stable")
            self.assertEqual(host.discover_browsers(path=d), [{"id": "vivaldi", "name": "Vivaldi", "path": exe}])

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(host.discover_browsers(path=d), [])

    def test_extra_path_env_comes_first(self):
        env = {"SEND_TO_OTHER_BROWSER_PATH": "/a:/b", "PATH": "/usr/bin"}
        self.assertTrue(host.search_path(env).startswith("/a:/b:/usr/bin:"))

    def test_minimal_environment_still_searches_standard_locations(self):
        # What a host started by xdg-desktop-portal (snap Firefox) sees: no real PATH.
        path = host.search_path({"PATH": "/nonexistent"}).split(os.pathsep)
        for expected in ("/usr/bin", "/snap/bin", "/opt/vivaldi", "/opt/google/chrome", os.path.expanduser("~/.local/bin")):
            self.assertIn(expected, path)


class IsWebUrlTest(unittest.TestCase):
    def test_accepts_http_and_https(self):
        self.assertTrue(host.is_web_url("https://example.com/a?b=c#d"))
        self.assertTrue(host.is_web_url("http://localhost:8080/"))

    def test_rejects_everything_else(self):
        for bad in [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "about:config",
            "moz-extension://x/y.html",
            "--user-data-dir=/tmp/x",
            "-https://example.com",
            "https://",
            "",
            None,
            42,
        ]:
            self.assertFalse(host.is_web_url(bad), bad)


class HandleRequestTest(unittest.TestCase):
    def setUp(self):
        self.spawned = []
        self.browsers = [{"id": "vivaldi", "name": "Vivaldi", "path": "/opt/vivaldi"}]

    def handle(self, request):
        return host.handle_request(
            request, discover=lambda: self.browsers, spawn=self.spawned.append
        )

    def test_ping(self):
        self.assertEqual(self.handle({"action": "ping"}), {"ok": True, "version": host.VERSION})

    def test_list(self):
        self.assertEqual(self.handle({"action": "list"}), {"ok": True, "browsers": self.browsers})

    def test_send_spawns_browser_with_all_urls(self):
        reply = self.handle(
            {"action": "send", "browser": "vivaldi", "urls": ["https://a.example/", "http://b.example/x"]}
        )
        self.assertEqual(self.spawned, [["/opt/vivaldi", "https://a.example/", "http://b.example/x"]])
        self.assertEqual(reply, {"ok": True, "opened": 2, "skipped": [], "browser": "vivaldi"})

    def test_send_never_forces_a_new_window(self):
        # Without extra switches a running browser opens the URLs as tabs in its existing window.
        self.handle({"action": "send", "browser": "vivaldi", "urls": ["https://a.example/"]})
        argv = self.spawned[0]
        self.assertEqual(argv[0], "/opt/vivaldi")
        self.assertFalse([a for a in argv[1:] if a.startswith("-")])

    def test_send_drops_non_web_urls(self):
        reply = self.handle(
            {"action": "send", "browser": "vivaldi", "urls": ["https://a.example/", "file:///etc/passwd", "--evil"]}
        )
        self.assertEqual(self.spawned, [["/opt/vivaldi", "https://a.example/"]])
        self.assertEqual(reply["skipped"], ["file:///etc/passwd", "--evil"])

    def test_send_with_only_invalid_urls_fails_without_spawning(self):
        reply = self.handle({"action": "send", "browser": "vivaldi", "urls": ["about:blank"]})
        self.assertFalse(reply["ok"])
        self.assertEqual(self.spawned, [])

    def test_send_to_missing_browser(self):
        reply = self.handle({"action": "send", "browser": "chrome", "urls": ["https://a.example/"]})
        self.assertFalse(reply["ok"])
        self.assertIn("not found", reply["error"])
        self.assertEqual(self.spawned, [])

    def test_send_cannot_run_arbitrary_executables(self):
        reply = self.handle({"action": "send", "browser": "/bin/sh", "urls": ["https://a.example/"]})
        self.assertFalse(reply["ok"])
        self.assertEqual(self.spawned, [])

    def test_send_validates_url_list(self):
        for urls in (None, [], "https://a.example/"):
            self.assertFalse(self.handle({"action": "send", "browser": "vivaldi", "urls": urls})["ok"])
        too_many = ["https://a.example/"] * (host.MAX_URLS + 1)
        self.assertFalse(self.handle({"action": "send", "browser": "vivaldi", "urls": too_many})["ok"])

    def test_spawn_failure_is_reported(self):
        def boom(argv):
            raise OSError("exec format error")

        reply = host.handle_request(
            {"action": "send", "browser": "vivaldi", "urls": ["https://a.example/"]},
            discover=lambda: self.browsers,
            spawn=boom,
        )
        self.assertFalse(reply["ok"])
        self.assertIn("exec format error", reply["error"])

    def test_unknown_action_and_garbage(self):
        self.assertFalse(self.handle({"action": "rm -rf"})["ok"])
        self.assertFalse(self.handle([1, 2])["ok"])


def frame(obj):
    body = json.dumps(obj).encode()
    return struct.pack("=I", len(body)) + body


def unframe_all(data):
    out, stream = [], io.BytesIO(data)
    while (msg := host.read_message(stream)) is not None:
        out.append(msg)
    return out


class ProtocolTest(unittest.TestCase):
    def test_roundtrip(self):
        buf = io.BytesIO()
        host.write_message(buf, {"ok": True, "n": "é"})
        self.assertEqual(unframe_all(buf.getvalue()), [{"ok": True, "n": "é"}])

    def test_serve_answers_each_request_until_eof(self):
        stdin = io.BytesIO(frame({"action": "ping"}) + frame({"action": "nope"}))
        stdout = io.BytesIO()
        self.assertEqual(host.serve(stdin, stdout), 0)
        replies = unframe_all(stdout.getvalue())
        self.assertEqual([r["ok"] for r in replies], [True, False])

    def test_serve_rejects_oversized_message(self):
        stdin = io.BytesIO(struct.pack("=I", host.MAX_MESSAGE_BYTES + 1))
        stdout = io.BytesIO()
        self.assertEqual(host.serve(stdin, stdout), 1)
        self.assertFalse(unframe_all(stdout.getvalue())[0]["ok"])

    def test_serve_rejects_invalid_json(self):
        body = b"not json"
        stdin = io.BytesIO(struct.pack("=I", len(body)) + body)
        stdout = io.BytesIO()
        self.assertEqual(host.serve(stdin, stdout), 1)
        self.assertFalse(unframe_all(stdout.getvalue())[0]["ok"])


class InstallTest(unittest.TestCase):
    def test_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "nmh"
            self.assertEqual(install.main(["--dest", str(dest)]), 0)
            manifest = json.loads((dest / "send_to_other_browser.json").read_text())
            self.assertEqual(manifest["name"], "send_to_other_browser")
            self.assertEqual(manifest["type"], "stdio")
            self.assertEqual(manifest["allowed_extensions"], [install.EXTENSION_ID])
            self.assertTrue(os.path.isabs(manifest["path"]))
            self.assertTrue(os.access(manifest["path"], os.X_OK))
            self.assertEqual(install.main(["--dest", str(dest), "--uninstall"]), 0)
            self.assertFalse((dest / "send_to_other_browser.json").exists())

    def test_extension_id_matches_manifest(self):
        manifest = json.loads((ROOT / "extension" / "manifest.json").read_text())
        self.assertEqual(manifest["browser_specific_settings"]["gecko"]["id"], install.EXTENSION_ID)


if __name__ == "__main__":
    unittest.main()

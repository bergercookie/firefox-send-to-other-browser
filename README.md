# Send to Other Browser

A Firefox extension that sends the URLs of your selected tabs to another browser
(Vivaldi, Google Chrome, Chromium, Brave, Edge) running on the same Linux machine.

Firefox extensions cannot start other programs, so there are two parts:

1. **the extension** (`extension/`): popup and tab context menu;
2. **a tiny native messaging host** (`host/`, Python 3, stdlib only) that starts the
   target browser with the URLs. A running Chromium-family browser opens them as new tabs.

## Prerequisites

Everything is driven by [`just`](https://just.systems). If you don't have it, bootstrap it first:

```sh
scripts/install-just.sh          # installs a pinned release to ~/.local/bin (override: JUST_VERSION=..., or pass a directory)
```

You also need Python 3, Node.js 22+ (for `web-ext` and the extension unit tests) and Firefox.

## Use

1. Install the extension (zip from the releases page, or `just run` for development).
2. Register the host: `just install-host` (writes `~/.mozilla/native-messaging-hosts/send_to_other_browser.json`).
3. Select tabs (ctrl/shift-click), click the toolbar button, pick a browser.
   Or right-click a tab → *Send to …*. Only `http(s)` tabs are sent.

If the target browser is already running, the URLs open as new tabs in its existing window
(the host never passes `--new-window`); a window is only created if the browser isn't running.

### Snap Firefox

A confined Firefox cannot spawn programs itself; on Ubuntu it asks `xdg-desktop-portal` to start the
host *outside* the sandbox. That needs a portal with Ubuntu's native-messaging patch (see
[the Ubuntu call for testing](https://discourse.ubuntu.com/t/call-for-testing-native-messaging-support-in-the-firefox-snap/29759))
and, if the host isn't found, `widget.use-xdg-desktop-portal.native-messaging` = `1` or `2` in `about:config`.
The manifest goes in the usual `~/.mozilla/native-messaging-hosts/` (`just install-host` prints a reminder when it sees the snap).
Because the portal starts the host with a minimal environment, the host also searches standard
install locations (`/usr/bin`, `/snap/bin`, `/opt/vivaldi`, `/opt/google/chrome`, `~/.local/bin`, ...).

**Status: not verified end to end.** The development container has no systemd, so snapd cannot run there.
Verified: host discovery with an empty environment. Not verified: the portal hand-off with the real snap.
Please try it and report back; Flatpak Firefox is unsupported.
Release builds are unsigned: load them via `about:debugging`, or sign them through AMO.

## Privacy

Nothing is collected or transmitted; see [PRIVACY.md](PRIVACY.md).

## Development

Everything goes through the [`justfile`](justfile) (`just` lists recipes); CI calls the same recipes.

Python tooling is managed by [uv](https://docs.astral.sh/uv/) from [`pyproject.toml`](pyproject.toml), which
is the single source of truth for the dependencies (dev group) and the pytest, mypy and ruff configuration.
`just setup` creates `.venv` and installs it; every command below runs inside that venv via `uv run`.

All lint checks live in [`.pre-commit-config.yaml`](.pre-commit-config.yaml) — `ruff check`, `ruff format`,
`mypy` and `web-ext lint` — and `just lint` runs all of them over the whole tree. Run
`uv run pre-commit install` once if you also want them on every commit.

| Recipe | What |
| --- | --- |
| `just setup` | `uv sync`: create `.venv` and install the dev dependencies |
| `just lint` | every lint check via pre-commit (ruff check, ruff format, mypy, web-ext lint) |
| `just test-unit` | python (host) and node (extension) unit tests |
| `just test-e2e` | headless Firefox + real extension + real host, fake `vivaldi`/`google-chrome` executables (`FIREFOX_BIN` selects Firefox) |
| `just ci` | all of the above |
| `just package [version]` | `dist/` zip + host tarball |

## Workflows

* `ci.yml`: `just ci` on pushes to main/master and PRs.
* `release.yml`: on tags `v*` that are on main/master and match the manifest version: tests, packages, creates a GitHub release.
* `nightly.yml`: on each push to main/master (plus a daily safety net) publishes the rolling `nightly` pre-release if main has moved since the last one.

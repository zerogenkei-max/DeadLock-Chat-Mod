"""Deadlock Chat Mod: the Windows customiser. Python standard library only."""
from __future__ import annotations

import argparse
import base64
import codecs
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
from build import build
from settings import normalize
from source2 import VPK, png_texture
from switchboard_version import PUBLIC_NAME, VERSION, artifact_name

PORT = 18742
OWN_ENTRY = "panorama/scripts/switchboard_runtime.vts_c"
OWN_RESOURCES = frozenset({
    OWN_ENTRY, "panorama/scripts/switchboard_shared.vts_c", "panorama/scripts/switchboard_boot.vts_c",
    "panorama/styles/switchboard.vcss_c", "panorama/layout/switchboard_panel.vxml_c",
    "panorama/layout/chat.vxml_c", "panorama/layout/popups/popup_settings.vxml_c",
    "panorama/layout/citadel_dashboard_footer_bar.vxml_c",
    "panorama/images/switchboard/custom_background.vtex_c",
})
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
# The game only loads addons named pak01_dir.vpk ... pak99_dir.vpk. Deadlock Mod
# Manager keeps switched-off mods in the same folder under other names.
ENABLED_ADDON = re.compile(r"pak\d\d_dir\.vpk", re.I)
DMM_STATE = ".dmm.json"
DMM_START = "// Deadlock Mod Manager - Start"
DMM_END = "// Deadlock Mod Manager - End"
BACKUPS_KEPT = 3
PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=")
WINDOWS_LOCKED = {5, 32, 33}  # access denied, sharing violation, lock violation


def quiet_run(args, **kwargs):
    return subprocess.run(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)


def running() -> bool:
    if os.name != "nt":
        return False
    r = quiet_run(["tasklist", "/FI", "IMAGENAME eq deadlock.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return '"deadlock.exe"' in r.stdout.lower()


def steam_root() -> Path | None:
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                return Path(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            pass
    return None


def valid_game(folder: Path | None) -> bool:
    return folder is not None and (folder / "game/citadel/pak01_dir.vpk").is_file()


def find_game() -> Path | None:
    steam = steam_root()
    libraries = [steam] if steam else []
    if steam:
        file = steam / "steamapps/libraryfolders.vdf"
        if file.is_file():
            libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', file.read_text(encoding="utf-8"))]
    for library in libraries:
        game = library / "steamapps/common/Deadlock"
        if valid_game(game):
            return game
    return None


def resolve_game(data: Path, game_root: Path | None = None) -> Path | None:
    """Use --game-root, then the saved folder if it still holds Deadlock, then Steam."""
    if game_root:
        return game_root
    try:
        saved = Path(json.loads((data / "installation.json").read_text(encoding="utf-8"))["game"])
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        saved = None
    return saved if valid_game(saved) else find_game()


def game_folder(text: str) -> Path:
    """Turn a pasted path into the Deadlock folder. Accepts quotes and the game, citadel or addons subfolders."""
    value = text.strip().strip('"\'').strip()
    if not value or len(value) > 4096:
        raise ValueError("Paste the path of your Deadlock folder.")
    folder = Path(value).expanduser()
    for candidate in (folder, folder.parent, folder.parent.parent, folder.parent.parent.parent):
        if valid_game(candidate):
            return candidate.resolve()
    raise ValueError("That folder doesn't look like Deadlock. Choose the folder that contains game\\citadel.")


def friendly_error(exc: BaseException) -> str:
    """Plain wording for errors shown in the customiser."""
    name = Path(exc.filename).name if isinstance(exc, OSError) and exc.filename else "a mod file"
    if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in WINDOWS_LOCKED:
        return (f"Windows blocked access to {name}. Another program, often antivirus or Mod Manager, "
                "may be using it. The customiser will try again.")
    if isinstance(exc, OSError) and exc.errno is not None:
        return f"Couldn't write {name}: {exc.strerror or 'unknown error'}."
    return str(exc) or exc.__class__.__name__


def show_error(text: str):
    """Print the error, and show it in a message box when there is no console (pythonw or the exe)."""
    if sys.stderr is not None:
        try:
            print(text, file=sys.stderr)
        except (OSError, ValueError):
            pass
    if os.name == "nt" and (sys.stderr is None or getattr(sys, "frozen", False)):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, PUBLIC_NAME, 0x10)
        except (OSError, AttributeError):
            pass


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".switchboard-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def package_owner(path: Path) -> str:
    try:
        package = VPK(path, allow_duplicate_entries=True)
        names = set(package.entries)
        if OWN_ENTRY not in names:
            return "other"
        return "own" if names <= OWN_RESOURCES and not package.has_duplicate_entries else "mixed"
    except (OSError, ValueError, KeyError, UnicodeError):
        return "unreadable"


def is_ours(path: Path) -> bool:
    return package_owner(path) == "own"


def read_dmm(addons: Path) -> dict | None:
    """Deadlock Mod Manager's record of the addons folder, {} if present but unreadable, None if absent."""
    file = addons / DMM_STATE
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def dmm_switched_off(dmm: dict | None) -> set[str]:
    """Lower-case file names Mod Manager has switched off."""
    names = set()
    mods = dmm.get("mods") if isinstance(dmm, dict) else None
    if not isinstance(mods, dict):
        return names
    for mod in mods.values():
        if not isinstance(mod, dict):
            continue
        lists = [mod.get("disabledVpks")]
        if mod.get("enabled") is False:
            lists.append(mod.get("currentVpks"))
        for entries in lists:
            if isinstance(entries, list):
                names.update(n.lower() for n in entries if isinstance(n, str))
    return names


def addon_files(addons: Path) -> tuple[list[Path], list[Path]]:
    """(files the game loads, other VPKs in the folder)."""
    try:
        files = sorted(p for p in addons.glob("*.vpk") if p.is_file())
    except OSError:
        return [], []
    off = dmm_switched_off(read_dmm(addons))
    enabled = [p for p in files if ENABLED_ADDON.fullmatch(p.name) and p.name.lower() not in off]
    return enabled, [p for p in files if p not in enabled]


def strip_comment(line: str) -> str:
    return line.split("//", 1)[0]


def gameinfo_with_addons(original: bytes) -> bytes | None:
    """gameinfo.gi with `Game citadel/addons` added, or None when an active line already has it."""
    bom = original.startswith(codecs.BOM_UTF8)
    text = original.decode("utf-8-sig")
    if any(re.search(r"\bGame\s+\"?citadel/addons\"?(?:\s|$)", strip_comment(line), re.I) for line in text.splitlines()):
        return None
    managed = []
    start = text.find(DMM_START)
    while start >= 0:
        end = text.find(DMM_END, start)
        end = len(text) if end < 0 else end + len(DMM_END)
        managed.append((start, end))
        start = text.find(DMM_START, end)
    for match in re.finditer(r"\bSearchPaths\s*\{", text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if "//" in text[line_start:match.start()] or any(a <= match.start() < b for a, b in managed):
            continue
        newline = "\r\n" if "\r\n" in text else "\n"
        text = text[:match.end()] + newline + "            Game                citadel/addons" + text[match.end():]
        return (codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8")
    if managed:
        raise ValueError("Deadlock Mod Manager controls the game's mod folder. Turn mods on in Mod Manager instead.")
    raise ValueError("Deadlock's SearchPaths block was not found.")


class Server(ThreadingHTTPServer):
    """Only one customiser may own the port; a second copy opens the first one's page."""
    allow_reuse_address = False
    allow_reuse_port = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class App:
    def __init__(self, data: Path, game: Path | None, no_install=False):
        self.data, self.game, self.no_install = data, game, no_install
        self.data.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.token_file = data / "local-token.txt"
        try:
            self.token = self.token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            self.token = ""
        if not TOKEN_PATTERN.fullmatch(self.token):
            self.token = secrets.token_urlsafe(32)
            atomic_write(self.token_file, self.token.encode())
        file = data / "settings.json"
        try:
            self.settings = normalize(json.loads(file.read_text(encoding="utf-8"))) if file.exists() else normalize({})
        except (ValueError, OSError, RecursionError):
            self.settings = normalize({})
        self.pending, self.error, self.notice, self.game_running = True, "", "", running()
        self.last_built = ""
        self.installed, self.mixed_installed, self.disabled_copies = [], [], []
        self.dmm = False
        self._owners = {}
        self._installed_set = None
        self._next_detect = 0.0
        self.refresh_installed()

    @property
    def artwork(self):
        return self.data / "artwork.png"

    @property
    def package(self):
        return self.data / "build/switchboard_dir.vpk"

    def owner(self, path: Path) -> str:
        """package_owner, cached by size and modification time so state polls stay cheap."""
        try:
            stat = path.stat()
        except OSError:
            return "unreadable"
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self._owners:
            if len(self._owners) > 256:
                self._owners.clear()
            self._owners[key] = package_owner(path)
        return self._owners[key]

    def refresh_installed(self):
        with self.lock:
            self.installed, self.mixed_installed, self.disabled_copies = [], [], []
            self.dmm = False
            if not self.game:
                return
            folder = self.game / "game/citadel/addons"
            self.dmm = (folder / DMM_STATE).is_file()
            enabled, others = addon_files(folder)
            for path in enabled:
                owner = self.owner(path)
                if owner == "own":
                    self.installed.append(path)
                elif owner == "mixed":
                    self.mixed_installed.append(path)
            for path in others:
                if self.owner(path) == "own":
                    self.disabled_copies.append(path)
            current = frozenset(self.installed)
            # A copy switched on in Mod Manager may be older than the current preferences.
            if self._installed_set is not None and current and current != self._installed_set:
                self.pending = True
            self._installed_set = current

    def update_targets(self):
        """Finish ownership/duplicate checks before compiling or replacing files."""
        self.refresh_installed()
        if self.mixed_installed:
            raise ValueError("An enabled mod combines this chat mod with other files. Keep the chat mod as its own mod in Mod Manager.")
        if len(self.installed) > 1:
            raise ValueError("More than one copy of the chat mod is turned on. Turn off the extra copies in Mod Manager.")
        targets = list(self.installed)
        cache = Path(os.environ.get("LOCALAPPDATA", self.data.parent)) / "dev.stormix.deadlock-mod-manager/mods"
        if cache.is_dir():
            for path in cache.rglob("*.vpk"):
                owner = self.owner(path)
                if owner == "mixed":
                    raise ValueError("A Mod Manager download combines this chat mod with other files. Add the chat mod on its own.")
                if owner == "own":
                    targets.append(path)
        return {path: path.read_bytes() for path in dict.fromkeys(targets)}

    def set_game(self, folder: Path):
        with self.lock:
            if not valid_game(folder):
                raise ValueError("Choose the Deadlock folder that contains game\\citadel.")
            atomic_write(self.data / "installation.json", json.dumps({"game": str(folder)}).encode())
            self.game = folder
            self.pending = True
            self.refresh_installed()

    def save_artwork(self, data: bytes):
        png_texture(data)
        with self.lock:
            atomic_write(self.artwork, data)
            self.save(dict(self.settings, artwork=True))

    def export_package(self) -> bytes:
        with self.lock:
            artwork = self.artwork if self.settings["artwork"] and self.artwork.exists() else None
            settings = dict(self.settings, artwork=artwork is not None)
            path = build(settings, token="", artwork=artwork,
                         output=self.data / "build/export/switchboard_dir.vpk", verify=False)
            return path.read_bytes()

    def compatibility(self):
        if not self.game:
            return "Choose the Deadlock folder to install the mod."
        file = ROOT / "research/baseline.json"
        if not file.exists():
            return "Compatibility information is missing. Use a complete download of the Windows customiser."
        baseline = json.loads(file.read_text(encoding="utf-8"))
        try:
            package = VPK(self.game / "game/citadel/pak01_dir.vpk")
            changed = [p for p, crc in baseline["resource_crcs"].items()
                       if p not in package.entries or package.entries[p][0] != crc]
        except (OSError, ValueError):
            return "The Deadlock game files could not be read."
        return "A Deadlock update changed the chat or settings screens. Wait for a mod update before installing." if changed else ""

    def save(self, value):
        config = normalize(value)
        with self.lock:
            notice = ""
            if config["artwork"] and not self.artwork.exists():
                config["artwork"] = False
                notice = "Background artwork was switched off because no image has been added."
            self.settings = config
            atomic_write(self.data / "settings.json", (json.dumps(config, indent=2) + "\n").encode("utf-8"))
            self.notice = notice
            self.pending = True
        return config

    def rebuild(self, update_installed=True):
        with self.lock:
            self.game_running = running()
            if self.game_running:
                self.pending = True
                return
            issue = self.compatibility() if not self.no_install else ""
            if issue:
                self.error = issue
                self.pending = False
                return
            if self.settings["artwork"] and not self.artwork.exists():
                self.save(dict(self.settings, artwork=False))
            targets = self.update_targets() if not self.no_install and update_installed else {}
            path = build(self.settings, self.token, self.artwork if self.settings["artwork"] else None,
                         output=self.package, verify=False)
            self.write_targets(targets, path.read_bytes())
            self.pending, self.error = False, ""
            self.last_built = time.strftime("%H:%M:%S")
            return path

    def write_targets(self, targets, data):
        def verify_target(target, previous):
            if previous is None:
                if target.exists():
                    raise ValueError("A mod file appeared during the update. Try again once Mod Manager has finished.")
            elif not target.is_file() or target.read_bytes() != previous or not is_ours(target):
                raise ValueError("A mod file changed during the update. Try again once Mod Manager has finished.")
        for target, previous in targets.items():
            verify_target(target, previous)
            self.backup_vpk(target)
        if targets and running():
            raise ValueError("Deadlock started during the update, so nothing was changed.")
        for target, previous in targets.items():
            if running():
                raise ValueError("Deadlock started during the update, so nothing was changed.")
            verify_target(target, previous)
            atomic_write(target, data)

    @staticmethod
    def backup_group(kind: str, target: Path) -> str:
        """File-name prefix shared by every backup of one target."""
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", kind)[:40]
        return stem + "-" + hashlib.sha256(str(target).lower().encode("utf-8")).hexdigest()[:8]

    def backup(self, kind: str, target: Path, data: bytes, suffix: str) -> Path:
        """Keep the first backup of each target plus the newest BACKUPS_KEPT; prune the rest."""
        folder = self.data / "backups"
        group = self.backup_group(kind, target)
        pattern = re.compile(re.escape(group) + r"-(original-)?([0-9a-f]{16})" + re.escape(suffix))
        digest = hashlib.sha256(data).hexdigest()[:16]
        existing = [p for p in folder.glob(group + "-*" + suffix) if pattern.fullmatch(p.name)] if folder.is_dir() else []
        same = [p for p in existing if pattern.fullmatch(p.name).group(2) == digest]
        if same:
            path = same[0]
            try:
                os.utime(path)
            except OSError:
                pass
        else:
            has_original = any(pattern.fullmatch(p.name).group(1) for p in existing)
            path = folder / f"{group}-{'' if has_original else 'original-'}{digest}{suffix}"
            atomic_write(path, data)
        if path.read_bytes() != data:
            raise OSError("The previous file could not be backed up, so nothing was changed.")
        recent = sorted((p for p in folder.glob(group + "-*" + suffix)
                         if pattern.fullmatch(p.name) and not pattern.fullmatch(p.name).group(1)),
                        key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for old in recent[BACKUPS_KEPT:]:
            if old != path:
                try:
                    old.unlink()
                except OSError:
                    pass
        self.prune_legacy_backups(folder)
        return path

    @staticmethod
    def prune_legacy_backups(folder: Path):
        """Backups from 0.2.3 and earlier (name-<digest>.vpk|.gi): keep the oldest and newest three per name."""
        groups = {}
        for path in folder.glob("*"):
            match = re.fullmatch(r"(.+?)-([0-9a-f]{16})\.(vpk|gi)", path.name)
            if match and not re.fullmatch(r".+-[0-9a-f]{8}(-original)?", match.group(1)):
                groups.setdefault((match.group(1), match.group(3)), []).append(path)
        for paths in groups.values():
            paths.sort(key=lambda p: p.stat().st_mtime_ns)
            for old in paths[1:-BACKUPS_KEPT]:
                try:
                    old.unlink()
                except OSError:
                    pass

    def backup_vpk(self, target: Path):
        if target.is_file():
            self.backup(target.stem, target, target.read_bytes(), ".vpk")

    def install(self):
        with self.lock:
            self._install()

    def _install(self):
        if self.no_install:
            raise ValueError("Installing is turned off in this development session.")
        if running():
            raise ValueError("Close Deadlock before installing or updating the mod.")
        issue = self.compatibility()
        if issue:
            raise ValueError(issue)
        targets = self.update_targets()
        if self.dmm:
            # Mod Manager owns the addons folder and gameinfo. Only connect a copy it has enabled.
            if not self.installed:
                if self.disabled_copies:
                    raise ValueError("The chat mod is turned off in Deadlock Mod Manager. Turn it on there, then click Install again.")
                raise ValueError("Deadlock Mod Manager looks after your mods. Add the chat mod there and turn it on, "
                                 "then click Install again to connect that copy.")
            path = self.rebuild(update_installed=False)
            if path is None:
                raise ValueError(self.error or "Close Deadlock before installing or updating the mod.")
            self.write_targets(targets, path.read_bytes())
            self.refresh_installed()
            self.pending = False
            return
        folder = self.game / "game/citadel/addons"
        target = self.installed[0] if self.installed else None
        if target is None:
            for index in range(99, 3, -1):
                candidate = folder / f"pak{index:02d}_dir.vpk"
                if not candidate.exists():
                    target = candidate
                    break
        if target is None:
            raise ValueError("No free addon file name was found.")
        if target not in targets:
            targets[target] = None
        gi = self.game / "game/citadel/gameinfo.gi"
        original = gi.read_bytes()
        updated_gameinfo = gameinfo_with_addons(original)
        path = self.rebuild(update_installed=False)
        if path is None:
            raise ValueError(self.error or "Close Deadlock before installing or updating the mod.")
        if running():
            raise ValueError("Deadlock started during installation, so nothing was changed.")
        if gi.read_bytes() != original:
            raise ValueError("Deadlock's gameinfo.gi changed during installation, so nothing was changed.")
        if updated_gameinfo is not None:
            self.backup("gameinfo", gi, original, ".gi")
        self.write_targets(targets, path.read_bytes())
        if updated_gameinfo is not None:
            if running():
                raise ValueError("Deadlock started during installation; gameinfo.gi was not changed.")
            if gi.read_bytes() != original:
                raise ValueError("Deadlock's gameinfo.gi changed during installation, so it was not changed.")
            atomic_write(gi, updated_gameinfo)
        self.refresh_installed()
        self.pending = False

    def state(self):
        with self.lock:
            if self.game and not valid_game(self.game) and time.monotonic() >= self._next_detect:
                # The saved folder moved or its drive is missing; look for the game again.
                self._next_detect = time.monotonic() + 30
                found = find_game()
                if found and found != self.game:
                    self.game, self.pending = found, True
            self.refresh_installed()
            return {"name": PUBLIC_NAME, "version": VERSION, "settings": dict(self.settings),
                    "gameFound": valid_game(self.game), "gameFolder": str(self.game) if self.game else "",
                    "gameRunning": self.game_running,
                    "installed": bool(self.installed or self.mixed_installed),
                    "installedCopies": len(self.installed) + len(self.mixed_installed),
                    "disabledCopies": len(self.disabled_copies), "modManager": self.dmm,
                    "pending": self.pending, "error": self.error, "notice": self.notice,
                    "lastBuilt": self.last_built, "artwork": self.artwork.exists(),
                    "zipName": artifact_name("Mod"), "format": 1}

    def worker_step(self, delay: float) -> float:
        """One background pass. Returns the wait before the next one; failures back off up to a minute."""
        try:
            self.game_running = running()
            if self.pending and not self.game_running:
                self.rebuild()
            return 2
        except Exception as exc:  # keep the worker alive; report and retry
            with self.lock:
                self.error = friendly_error(exc)
                self.pending = True
            return min(60, max(2, delay) * 2)

    def worker(self):
        delay = 2
        while not self.stop.wait(delay):
            delay = self.worker_step(delay)


def handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Switchboard/" + VERSION
        timeout = 5

        def log_message(self, *args):
            pass  # URLs can contain preferences; no request logging.

        def respond(self, body, code=200, mime="application/json", attachment=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode("utf-8")
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def accepted_host(self):
            hosts = self.headers.get_all("Host", [])
            return len(hosts) == 1 and hosts[0] in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def accepted_origin(self):
            origins = self.headers.get_all("Origin", [])
            return (len(origins) <= 1 and (not origins or origins[0] in
                    (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"))
                    and self.headers.get("Sec-Fetch-Site", "").lower() != "cross-site")

        def authorized(self, query, allow_query=False):
            # Only the game's sync.png image request may carry the token in its URL.
            value = self.headers.get("X-Switchboard-Token", "") or (query.get("token", [""])[0] if allow_query else "")
            return self.accepted_host() and bool(TOKEN_PATTERN.fullmatch(value)) and secrets.compare_digest(value, app.token)

        def do_GET(self):
            path = urlsplit(self.path)
            q = parse_qs(path.query)
            if not self.accepted_host():
                return self.respond({"error": "Unexpected host"}, 403)
            if path.path == "/health":
                return self.respond({"app": "switchboard", "version": VERSION})
            if path.path == "/":
                page = (ROOT / "web/index.html").read_text(encoding="utf-8").replace("__SWITCHBOARD_TOKEN__", app.token)
                return self.respond(page, mime="text/html; charset=utf-8")
            if path.path in ("/app.js", "/style.css"):
                file = ROOT / "web" / path.path[1:]
                return self.respond(file.read_bytes(), mime=mimetypes.guess_type(file)[0] or "text/plain")
            if path.path == "/model.js":
                return self.respond((ROOT / "src/panorama/scripts/switchboard_shared.vts").read_bytes(), mime="text/javascript")
            if path.path in ("/gallery", "/gallery/"):
                return self.respond((ROOT / "gallery/index.html").read_bytes(), mime="text/html; charset=utf-8")
            if path.path.startswith("/gallery/"):
                name = path.path.removeprefix("/gallery/")
                if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.(?:html|css|js|json|png|jpg|webp)", name):
                    return self.respond({"error": "Not found"}, 404)
                file = ROOT / "gallery" / name
                if not file.is_file():
                    return self.respond({"error": "Not found"}, 404)
                return self.respond(file.read_bytes(), mime=mimetypes.guess_type(file)[0] or "application/octet-stream")
            sync = path.path == "/sync.png"
            if not self.authorized(q, allow_query=sync):
                return self.respond({"error": "Local token required"}, 403)
            if not self.accepted_origin():
                return self.respond(PIXEL, 403, "image/png") if sync else self.respond({"error": "Unexpected origin"}, 403)
            if path.path == "/api/state":
                return self.respond(app.state())
            if sync:
                try:
                    if len(self.path) > 18000:
                        raise ValueError("Settings payload too large")
                    app.save(json.loads(q.get("settings", [""])[0]))
                    return self.respond(PIXEL, mime="image/png")
                except (ValueError, KeyError, TypeError, RuntimeError, OSError):
                    return self.respond(PIXEL, 400, "image/png")
            if path.path == "/artwork.png" and app.artwork.exists():
                return self.respond(app.artwork.read_bytes(), mime="image/png")
            if path.path == "/download/switchboard.zip":
                try:
                    shareable = app.export_package()
                except (ValueError, OSError, RuntimeError) as exc:
                    return self.respond({"error": "Couldn't make the ZIP: " + friendly_error(exc)}, 400)
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
                    z.writestr("switchboard_dir.vpk", shareable)
                    z.writestr("README.txt", f"{PUBLIC_NAME} {VERSION}\r\n\r\n"
                               "Add this ZIP in Deadlock Mod Manager (Add mods > Add Local Mod) and turn it on.\r\n"
                               "Keep only one copy of the chat mod turned on.\r\n"
                               "In game, open Settings and click CHAT MOD at the bottom.\r\n"
                               "This copy has your current look but doesn't save changes on its own.\r\n")
                return self.respond(data.getvalue(), mime="application/zip", attachment=artifact_name("Mod"))
            return self.respond({"error": "Not found"}, 404)

        def do_POST(self):
            path = urlsplit(self.path)
            if not self.authorized(parse_qs(path.query)):
                return self.respond({"error": "Local token required"}, 403)
            if not self.accepted_origin():
                return self.respond({"error": "Unexpected origin"}, 403)
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
                    return self.respond({"error": "Provide one valid Content-Length without transfer encoding"}, 400)
                size = int(lengths[0])
                if size > 4 * 1024 * 1024:
                    return self.respond({"error": "File is too large"}, 413)
                data = self.rfile.read(size)
                if len(data) != size:
                    return self.respond({"error": "Request body is incomplete"}, 400)
                if path.path == "/api/config":
                    app.save(json.loads(data))
                elif path.path == "/api/artwork":
                    app.save_artwork(data)
                elif path.path == "/api/game-folder":
                    value = json.loads(data)
                    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
                        raise ValueError("Paste the path of your Deadlock folder.")
                    app.set_game(game_folder(value["path"]))
                elif path.path == "/api/install":
                    app.install()
                elif path.path == "/api/launch":
                    if running():
                        raise ValueError("Deadlock is already running.")
                    app.install()
                    steam = steam_root()
                    if steam is None:
                        raise ValueError("Steam was not found.")
                    subprocess.Popen([str(steam / "steam.exe"), "-applaunch", "1422450"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                elif path.path == "/api/shutdown":
                    self.respond({"ok": True})
                    app.stop.set()
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    return self.respond({"error": "Not found"}, 404)
                return self.respond(app.state())
            except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
                return self.respond({"error": friendly_error(exc)}, 400)
    return Handler


def existing_customiser(port: int) -> bool:
    from urllib.request import urlopen
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return json.load(r).get("app") == "switchboard"
    except Exception:
        return False


def run(args):
    data = args.data_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Switchboard"
    app = App(data, resolve_game(data, args.game_root), args.no_install)
    try:
        server = Server(("127.0.0.1", args.port), handler(app))
    except OSError:
        if not existing_customiser(args.port):
            raise SystemExit(f"The Windows customiser couldn't start: local port {args.port} is in use by another program.")
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}/")
        return
    threading.Thread(target=app.worker, daemon=True).start()
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever(poll_interval=.5)
    finally:
        app.stop.set()
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--game-root", type=Path)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    try:
        run(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            show_error(exc.code)
            raise SystemExit(1)
        raise
    except Exception as exc:
        show_error("The Windows customiser stopped: " + friendly_error(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

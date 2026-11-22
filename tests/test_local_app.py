import io
import hashlib
import json
import re
import shutil
import socket
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlencode
import zlib
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import launcher
from source2 import VPK, pack, png_texture
from settings import normalize


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def png(width=8, height=8, colour=6, depth=8, compression=0, interlace=0, pixels=None):
    if pixels is None:
        pixel = b"\xd8\xad\x70\x88" if colour == 6 else b"\xd8\xad\x70"
        pixels = zlib.compress((b"\0" + pixel * width) * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, compression, 0, interlace))
            + chunk(b"IDAT", pixels) + chunk(b"IEND", b""))


class AppFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.enterContext(patch('launcher.running', return_value=False))
        self.enterContext(patch.dict('os.environ', {'LOCALAPPDATA': str(Path(self.temp.name) / 'fake-appdata')}))
        self.app = launcher.App(Path(self.temp.name), None, no_install=True)
        self.server = ThreadingHTTPServer(("127.0.0.1",0), launcher.handler(self.app))
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02),daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def request(self,path,data=None,token=True,origin=None,headers=None):
        headers = dict(headers or {})
        if token: headers.setdefault("X-Switchboard-Token", self.app.token)
        if origin:headers["Origin"]=origin
        if isinstance(data,dict):data=json.dumps(data).encode()
        return urllib.request.urlopen(urllib.request.Request(self.url+path,data=data,headers=headers), timeout=5)

    def assert_http_error(self, code, path, data=None, **kwargs):
        try:
            response = self.request(path, data, **kwargs)
        except urllib.error.HTTPError as error:
            with error:
                self.assertEqual(error.code, code)
                return error.read()
        else:
            response.close()
            self.fail(f'{path.split("?", 1)[0]} unexpectedly returned {response.status}')

    def fake_game(self, name='fake-game', content=b'fixture original UI resource'):
        game = self.app.data / name
        citadel = game / 'game/citadel'
        (citadel / 'addons').mkdir(parents=True)
        pack({'panorama/layout/chat.vxml_c': content}, citadel / 'pak01_dir.vpk')
        (citadel / 'gameinfo.gi').write_bytes(
            b'"GameInfo"\n{ FileSystem { SearchPaths { Game citadel\nGame core\n} } }\n')
        return game

    def configure_install(self):
        self.app.game = self.fake_game()
        self.app.no_install = False
        self.app.game_running = False
        assets = self.app.data / 'fixture-assets'
        (assets / 'research').mkdir(parents=True)
        shutil.copytree(ROOT / 'src', assets / 'src')
        (assets / 'research/baseline.json').write_text(json.dumps({'resource_crcs': {
            'panorama/layout/chat.vxml_c': zlib.crc32(b'fixture original UI resource')}}), encoding='utf-8')
        self.enterContext(patch('launcher.ROOT', assets))
        return self.app.game / 'game/citadel'

    def own_vpk(self, path, mixed=False):
        launcher.build({'fontSize': 16}, self.app.token, output=path, verify=False)
        if mixed:
            original = VPK(path)
            files = {name: original.read(name) for name in original.entries}
            files['other-mod/preserved.txt'] = b'unrelated mod content'
            pack(files, path)
        return path

    def assert_refusal_preserves(self, paths, operation):
        before = {path: path.read_bytes() for path in paths}
        self.app.error = ''
        refused = False
        try:
            operation()
        except ValueError:
            refused = True
        after = {path: path.read_bytes() for path in paths}
        # Keep successive subtests independent even when a broken implementation mutates a fixture.
        for path, content in before.items():
            if after[path] != content:
                path.write_bytes(content)
        self.assertTrue(refused or self.app.error, 'Unsafe update was not refused')
        for path, content in before.items():
            self.assertTrue(after[path] == content, f'Refused update changed {path.name}')

    def raw_post(self, body, framing):
        headers = (f'POST /api/config HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                   f'X-Switchboard-Token: {self.app.token}\r\nConnection: close\r\n{framing}\r\n\r\n').encode('ascii')
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=5) as sock:
            sock.sendall(headers + body)
            sock.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                block = sock.recv(1024)
                if not block:
                    break
                response.extend(block)
            if b'\r\n' not in response:
                self.fail('Request closed without an HTTP response')
            return int(response.split(b' ', 2)[1])

class LocalAppTest(AppFixture):
    def test_preferences_persist_and_unknown_fields_are_discarded(self):
        with self.request('/api/config',{'preset':'league','fontSize':16,'unexpected':'discard'}) as response:
            self.assertEqual(json.load(response)['settings']['fontSize'],16)
        saved=json.loads((self.app.data/'settings.json').read_text())
        self.assertNotIn('unexpected',saved)
        again=launcher.App(self.app.data,None,no_install=True)
        self.assertEqual(again.settings['preset'],'league')

    def test_game_preference_sink_returns_a_valid_png(self):
        query=urlencode({'token':self.app.token,'settings':json.dumps({'fontSize':21})})
        with self.request('/sync.png?'+query) as response:
            self.assertEqual(response.headers['Content-Type'],'image/png')
            self.assertTrue(png_texture(response.read()))
        self.assertEqual(self.app.settings['fontSize'],21)

    def test_bad_origins_and_missing_tokens_cannot_change_preferences(self):
        for token,origin in [(False,None),(True,'https://example.com')]:
            self.assert_http_error(403, '/api/config', {'fontSize':28}, token=token, origin=origin)
        self.assertEqual(self.app.settings['fontSize'],18)

    def test_only_image_files_and_known_theme_values_are_accepted(self):
        self.assert_http_error(400, '/api/artwork', b'not a PNG')
        with self.request('/api/artwork',png()) as response:self.assertTrue(json.load(response)['artwork'])
        self.assert_http_error(400, '/api/config', {'font':'bad font'})
        self.assert_http_error(400, '/api/config', {'version': True})
        with self.assertRaises(ValueError): normalize({'version': True})
        texture=png_texture(png())
        self.assertTrue(texture.endswith(png()))

    def test_game_running_blocks_installation(self):
        self.app.no_install=False
        with patch('launcher.running',return_value=True):
            with self.assertRaisesRegex(ValueError,'Close Deadlock'):self.app.install()

    def test_vpk_roundtrip_retains_exact_bytes_and_checks_crcs(self):
        path=self.app.data/'test_dir.vpk'
        pack({'panorama/example.txt':b'hello','panorama/nested/other.bin':bytes(range(256))},path)
        package=VPK(path)
        self.assertEqual(package.read('panorama/nested/other.bin'),bytes(range(256)))
        broken=bytearray(path.read_bytes());broken[-1]^=1;path.write_bytes(broken)
        with self.assertRaisesRegex(ValueError,'CRC mismatch'):VPK(path).read('panorama/nested/other.bin')

    def test_installer_preserves_other_mods_and_backs_up_its_previous_vpk(self):
        citadel = self.configure_install()
        original = (citadel / 'gameinfo.gi').read_bytes()
        other = citadel / 'addons/pak01_dir.vpk'
        other.write_bytes(b'untouched other mod')
        self.app.install()
        target=self.app.installed[0]
        before=target.read_bytes();self.app.save({'fontSize':22});self.app.install()
        self.assertEqual(other.read_bytes(),b'untouched other mod')
        self.assertNotEqual(target.read_bytes(),before)
        self.assertTrue(any(p.read_bytes()==before for p in (self.app.data/'backups').glob('*.vpk')))
        updated=(citadel/'gameinfo.gi').read_text()
        self.assertEqual(updated.count('citadel/addons'),1)
        self.assertTrue(any(p.read_bytes()==original for p in (self.app.data/'backups').glob('*.gi')))

    def test_damaged_png_is_rejected(self):
        bad=bytearray(png());bad[-1]^=1
        with self.assertRaisesRegex(ValueError,'damaged chunk'):png_texture(bytes(bad))

    def test_png_rejects_invalid_headers_and_pixel_streams_before_saving(self):
        valid = png()
        with self.request('/api/artwork', valid) as response:
            response.read()
        malformed = {
            'short IHDR': b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR',
            'invalid compressed data': png(pixels=b'not a zlib stream'),
            'unsupported colour type': png(colour=255),
            'unsupported bit depth': png(depth=3),
            'unsupported compression': png(compression=1),
            'unsupported interlace': png(interlace=1),
            'inflated pixels exceed dimensions': png(1, 1, pixels=zlib.compress(b'\0' * 65536)),
            'too few pixels': png(8, 8, pixels=zlib.compress(b'\0' * 5)),
            'invalid row filter': png(1, 1, pixels=zlib.compress(b'\5\0\0\0\0')),
            'truncated deflate stream': png(pixels=zlib.compress(b'\0' * (8 * 33))[:-2]),
        }
        for name, value in malformed.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    png_texture(value)
                self.assert_http_error(400, '/api/artwork', value)
                self.assertEqual(self.app.artwork.read_bytes(), valid)
        self.assertTrue(png_texture(png(colour=2)))

    def test_foreign_duplicate_entries_are_recognized_without_owning_ambiguous_mods(self):
        content = b'preserved content'
        for name, owner in [('other-mod/kept.txt', 'other'), (launcher.OWN_ENTRY, 'mixed')]:
            with self.subTest(owner=owner):
                folder, filename = name.rsplit('/', 1)
                stem, ext = filename.rsplit('.', 1)
                entry = stem.encode() + b'\0' + struct.pack('<IHHIIH', zlib.crc32(content), 0, 0x7fff, 0, len(content), 0xffff)
                tree = ext.encode() + b'\0' + folder.encode() + b'\0' + entry * 2 + b'\0\0\0'
                path = self.app.data / 'repeated_dir.vpk'
                path.write_bytes(struct.pack('<III', 0x55aa1234, 1, len(tree)) + tree + content)
                with self.assertRaises(ValueError):
                    VPK(path)
                self.assertEqual(launcher.package_owner(path), owner)
                self.assertEqual(VPK(path, allow_duplicate_entries=True).read(name), content)

    def test_malformed_vpks_are_controlled_errors_and_do_not_block_startup(self):
        path = self.app.data / 'malformed_dir.vpk'
        pack({'panorama/example.txt': b'fixture'}, path)
        valid = path.read_bytes()
        malformed = {
            'short header': b'bad',
            'missing tree': struct.pack('<III', 0x55aa1234, 1, 100),
            'missing v2 header': struct.pack('<III', 0x55aa1234, 2, 1),
            'truncated entry': valid[:30],
        }
        for name, value in malformed.items():
            with self.subTest(name=name):
                path.write_bytes(value)
                with self.assertRaises(ValueError):
                    VPK(path)
                self.assertFalse(launcher.is_ours(path))
        game = self.fake_game()
        (game / 'game/citadel/addons/pak01_dir.vpk').write_bytes(b'bad')
        again = launcher.App(self.app.data / 'restart', game, no_install=True)
        self.assertEqual(again.installed, [])

    def test_huge_numeric_values_are_rejected_without_changing_settings(self):
        before = dict(self.app.settings)
        for value in [10 ** 400, -(10 ** 400), float('inf'), float('nan')]:
            with self.subTest(value_type=type(value).__name__, negative=value < 0):
                with self.assertRaises(ValueError):
                    normalize({'fontSize': value})
                self.assert_http_error(400, '/api/config', {'fontSize': value})
                query = urlencode({'token': self.app.token, 'settings': json.dumps({'fontSize': value})})
                self.assert_http_error(400, '/sync.png?' + query)
                self.assertEqual(self.app.settings, before)

    def test_invalid_persisted_tokens_regenerate_and_missing_tokens_stay_rejected(self):
        for invalid in ['', '   ', 'short', '\u2603', b'\xff']:
            with self.subTest(invalid=repr(invalid)):
                self.app.token_file.write_bytes(invalid if isinstance(invalid, bytes) else invalid.encode('utf-8'))
                restored = launcher.App(self.app.data, None, no_install=True)
                self.assertRegex(restored.token, r'^[A-Za-z0-9_-]{43}$')
                self.assertNotEqual(restored.token, invalid.strip())
                self.assertEqual(self.app.token_file.read_text(encoding='utf-8'), restored.token)
                self.app.token = restored.token
                self.assert_http_error(403, '/api/config', {'fontSize': 29}, token=False)
                query = urlencode({'settings': json.dumps({'fontSize': 29})})
                self.assert_http_error(403, '/sync.png?' + query, token=False)
                self.assertEqual(self.app.settings['fontSize'], 18)
        again = launcher.App(self.app.data, None, no_install=True)
        self.assertEqual(again.token, self.app.token, 'A valid persisted token should remain stable')

    def test_invalid_supplied_tokens_and_hosts_are_cleanly_rejected(self):
        for token in ['', 'wrong-token', '\u2603']:
            with self.subTest(token=repr(token)):
                self.assert_http_error(403, '/api/state?' + urlencode({'token': token}), token=False)
        self.assert_http_error(403, '/api/config', {'fontSize': 29},
                               headers={'X-Switchboard-Token': '\xe9'})
        self.assert_http_error(403, '/api/config', {'fontSize': 29},
                               headers={'Host': 'untrusted.invalid'})
        self.assertEqual(self.app.settings['fontSize'], 18)

    def test_cross_origin_image_sync_cannot_change_preferences(self):
        query = urlencode({'token': self.app.token, 'settings': json.dumps({'fontSize': 29})})
        for headers in [{'Origin': 'https://untrusted.invalid'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'null'}]:
            with self.subTest(headers=headers):
                self.app.save({})
                self.assert_http_error(403, '/sync.png?' + query, headers=headers)
                self.assertEqual(self.app.settings['fontSize'], 18)
        with self.request('/sync.png?' + query, origin=self.url,
                          headers={'Sec-Fetch-Site': 'same-origin'}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.app.settings['fontSize'], 29)

    def test_download_has_no_active_token_and_preserves_personalized_build(self):
        self.app.save({'fontSize': 23})
        self.app.rebuild()
        original = self.app.package.read_bytes()
        self.assertTrue(self.app.token.encode('ascii') in original, 'Local build should retain its save token')
        with self.request('/download/switchboard.zip') as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertIsNone(archive.testzip())
                exported = archive.read('switchboard_dir.vpk')
        self.assertFalse(self.app.token.encode('ascii') in exported, 'Downloaded mod exposes the local save token')
        self.assertTrue(self.app.package.read_bytes() == original, 'Export changed the personalized local build')
        path = self.app.data / 'downloaded_dir.vpk'
        path.write_bytes(exported)
        package = VPK(path)
        for name in package.entries:
            package.read(name)
        boot = package.read('panorama/scripts/switchboard_boot.vts_c')
        self.assertRegex(boot, rb'"token"\s*:\s*""')
        self.assertRegex(boot, rb'"fontSize"\s*:\s*23')

    def test_concurrent_exports_read_complete_token_free_packages_under_lock(self):
        self.app.rebuild()
        export = self.app.data / 'build/export/switchboard_dir.vpk'
        paused, resume, second_reached = threading.Event(), threading.Event(), threading.Event()
        actual_lock = self.app.lock
        count_lock = threading.Lock()
        entries = 0
        results, errors = [], []
        real_read = Path.read_bytes

        class ObservedLock:
            def __enter__(inner):
                nonlocal entries
                with count_lock:
                    entries += 1
                    if entries == 2:
                        second_reached.set()
                return actual_lock.__enter__()

            def __exit__(inner, *args):
                return actual_lock.__exit__(*args)

        def paused_read(path):
            if path == export and not paused.is_set():
                paused.set()
                if not resume.wait(5):
                    raise RuntimeError('Test did not release the export read')
            return real_read(path)

        def download():
            try:
                with self.request('/download/switchboard.zip') as response:
                    results.append(response.read())
            except Exception as error:
                errors.append(error)

        self.app.lock = ObservedLock()
        first = threading.Thread(target=download, daemon=True)
        second = threading.Thread(target=download, daemon=True)
        with patch.object(Path, 'read_bytes', paused_read):
            try:
                first.start()
                self.assertTrue(paused.wait(5), 'First export did not reach its read')
                second.start()
                self.assertTrue(second_reached.wait(5), 'Second export did not reach the lock')
                acquired = actual_lock.acquire(blocking=False)
                if acquired:
                    actual_lock.release()
                self.assertFalse(acquired, 'Export read occurred outside the app lock')
            finally:
                resume.set()
                first.join(5)
                if second.ident is not None:
                    second.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        for index, data in enumerate(results):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertIsNone(archive.testzip())
                exported = archive.read('switchboard_dir.vpk')
            self.assertNotIn(self.app.token.encode('ascii'), exported)
            path = self.app.data / f'concurrent-{index}_dir.vpk'
            path.write_bytes(exported)
            package = VPK(path)
            for name in package.entries:
                package.read(name)
            self.assertRegex(package.read('panorama/scripts/switchboard_boot.vts_c'), rb'"token"\s*:\s*""')

    def test_duplicate_enabled_copies_refuse_install_and_rebuild_without_writes(self):
        citadel = self.configure_install()
        first = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        second = self.own_vpk(citadel / 'addons/pak81_dir.vpk')
        cache = self.own_vpk(self.app.data / 'fake-appdata/dev.stormix.deadlock-mod-manager/mods/own/cached_dir.vpk')
        for operation in [self.app.install, self.app.rebuild]:
            with self.subTest(operation=operation.__name__):
                self.assert_refusal_preserves([first, second, cache, citadel / 'gameinfo.gi'], operation)

    def test_mixed_vpk_refuses_install_and_rebuild_without_overwriting_other_mod(self):
        citadel = self.configure_install()
        mixed = self.own_vpk(citadel / 'addons/pak80_dir.vpk', mixed=True)
        cache = self.own_vpk(self.app.data / 'fake-appdata/dev.stormix.deadlock-mod-manager/mods/own/cached_dir.vpk')
        for operation in [self.app.install, self.app.rebuild]:
            with self.subTest(operation=operation.__name__):
                self.assert_refusal_preserves([mixed, cache, citadel / 'gameinfo.gi'], operation)
                self.assertEqual(VPK(mixed).read('other-mod/preserved.txt'), b'unrelated mod content')

    def test_mixed_manager_cache_prevents_partial_updates_of_enabled_vpk(self):
        citadel = self.configure_install()
        enabled = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        mixed_cache = self.own_vpk(
            self.app.data / 'fake-appdata/dev.stormix.deadlock-mod-manager/mods/combined/cached_dir.vpk', mixed=True)
        for operation in [self.app.install, self.app.rebuild]:
            with self.subTest(operation=operation.__name__):
                self.assert_refusal_preserves([enabled, mixed_cache, citadel / 'gameinfo.gi'], operation)

    def test_replaced_owned_target_after_backup_is_not_overwritten(self):
        citadel = self.configure_install()
        enabled = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        cache = self.own_vpk(self.app.data / 'fake-appdata/dev.stormix.deadlock-mod-manager/mods/own/cached_dir.vpk')
        gi = citadel / 'gameinfo.gi'
        before_cache, before_gi = cache.read_bytes(), gi.read_bytes()
        foreign = self.app.data / 'foreign_dir.vpk'
        pack({'other-mod/content.txt': b'unrelated replacement'}, foreign)
        foreign_bytes = foreign.read_bytes()
        real_backup = self.app.backup_vpk
        replaced = False

        def replace_after_backup(target):
            nonlocal replaced
            real_backup(target)
            if target == enabled:
                enabled.write_bytes(foreign_bytes)
                replaced = True

        with patch.object(self.app, 'backup_vpk', side_effect=replace_after_backup):
            with self.assertRaises(ValueError):
                self.app.install()
        self.assertTrue(replaced, 'The replacement fixture did not run')
        self.assertEqual(enabled.read_bytes(), foreign_bytes)
        self.assertEqual(VPK(enabled).read('other-mod/content.txt'), b'unrelated replacement')
        self.assertEqual(cache.read_bytes(), before_cache)
        self.assertEqual(gi.read_bytes(), before_gi)

    def test_corrupt_existing_gameinfo_backup_refuses_before_updates(self):
        citadel = self.configure_install()
        enabled = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        cache = self.own_vpk(self.app.data / 'fake-appdata/dev.stormix.deadlock-mod-manager/mods/own/cached_dir.vpk')
        gi = citadel / 'gameinfo.gi'
        before = {path: path.read_bytes() for path in [enabled, cache, gi]}
        backup = self.app.data / 'backups' / (self.app.backup_group('gameinfo', gi) + '-original-'
                                              + hashlib.sha256(before[gi]).hexdigest()[:16] + '.gi')
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b'corrupt backup')
        with self.assertRaises(OSError):
            self.app.install()
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, f'Corrupt backup allowed a change to {path.name}')
        self.assertEqual(backup.read_bytes(), b'corrupt backup')

    def test_game_start_during_build_leaves_game_and_cache_unchanged(self):
        citadel = self.configure_install()
        enabled = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        cache = self.own_vpk(self.app.data / 'fake-appdata/dev.stormix.deadlock-mod-manager/mods/own/cached_dir.vpk')
        paths = [enabled, cache, citadel / 'gameinfo.gi']
        before = {path: path.read_bytes() for path in paths}
        now_running = False
        real_build = launcher.build

        def game_starts_during_build(*args, **kwargs):
            nonlocal now_running
            result = real_build(*args, **kwargs)
            now_running = True
            return result

        with patch('launcher.build', side_effect=game_starts_during_build), \
                patch('launcher.running', side_effect=lambda: now_running):
            with self.assertRaises(ValueError):
                self.app.install()
        for path, data in before.items():
            self.assertTrue(path.read_bytes() == data, f'Game started but {path.name} changed')

    def test_folder_change_during_build_cannot_redirect_unvalidated_writes(self):
        citadel = self.configure_install()
        self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        original_game = self.app.game
        other_game = self.fake_game('incompatible-game', content=b'different game resources')
        other_vpk = self.own_vpk(other_game / 'game/citadel/addons/pak80_dir.vpk')
        before = other_vpk.read_bytes()
        paused, resume, request_reached = threading.Event(), threading.Event(), threading.Event()
        outcomes = []
        actual_lock = self.app.lock

        class ObservedLock:
            def __enter__(inner):
                request_reached.set()
                return actual_lock.__enter__()

            def __exit__(inner, *args):
                return actual_lock.__exit__(*args)

        self.app.lock = ObservedLock()
        real_build = launcher.build

        def paused_build(*args, **kwargs):
            result = real_build(*args, **kwargs)
            paused.set()
            if not resume.wait(5):
                raise RuntimeError('Test did not release the paused build')
            return result

        def rebuilding():
            try:
                self.app.rebuild()
            except Exception as error:
                outcomes.append(error)

        def choose_folder():
            try:
                with self.request('/api/game-folder', {'path': str(other_game)}) as response:
                    outcomes.append(response.status)
            except Exception as error:
                outcomes.append(error)
            finally:
                request_reached.set()

        build_thread = threading.Thread(target=rebuilding, daemon=True)
        request_thread = threading.Thread(target=choose_folder, daemon=True)
        with patch('launcher.build', side_effect=paused_build):
            try:
                build_thread.start()
                self.assertTrue(paused.wait(5), 'Build did not reach the controlled pause')
                request_reached.clear()
                request_thread.start()
                self.assertTrue(request_reached.wait(5), 'Folder request did not reach the app')
                self.assertEqual(self.app.game, original_game, 'Folder changed during active rebuild')
            finally:
                resume.set()
                build_thread.join(5)
                if request_thread.ident is not None:
                    request_thread.join(5)
        self.assertFalse(build_thread.is_alive())
        self.assertFalse(request_thread.is_alive())
        self.assertEqual(outcomes, [200])
        self.assertEqual(self.app.game, other_game)
        self.assertTrue(other_vpk.read_bytes() == before, 'Folder switch redirected a write to an incompatible game')
        self.assertTrue(self.app.compatibility(), 'The redirected game fixture must be incompatible')

    def test_truncated_and_unsupported_http_bodies_do_not_change_settings(self):
        body = b'{"fontSize":29}'
        cases = [
            ('Content-Length: 100', body),
            ('Content-Length: invalid', body),
            ('Transfer-Encoding: chunked', f'{len(body):x}\r\n'.encode('ascii') + body + b'\r\n0\r\n\r\n'),
            ('Transfer-Encoding: chunked\r\nContent-Length: ' + str(len(body)), body),
        ]
        for framing, payload in cases:
            with self.subTest(framing=framing):
                self.app.save({})
                self.assertIn(self.raw_post(payload, framing), (400, 411, 413, 501))
                self.assertEqual(self.app.settings['fontSize'], 18)

    def test_gallery_serves_curated_assets_without_exposing_other_files(self):
        folder=self.app.data/'gallery';folder.mkdir()
        (folder/'index.html').write_text('<title>Screenshot gallery</title>')
        (folder/'cover-chat.png').write_bytes(png())
        (self.app.data/'private.json').write_text('{"private":true}')
        with patch('launcher.ROOT',self.app.data):
            with self.request('/gallery/',token=False) as response:
                self.assertIn(b'Screenshot gallery',response.read())
            with self.request('/gallery/cover-chat.png',token=False) as response:
                self.assertEqual(response.headers['Content-Type'],'image/png')
            for path in ['/gallery/../private.json','/gallery/%2e%2e/private.json','/gallery/missing.png']:
                self.assert_http_error(404, path, token=False)


LOCAL_ID = 'local-0dea1c2e-5b7a-4c1e-9a7e-3f2b1c0d9e8f'


def dmm_record(enabled, current, disabled, original):
    return {'enabled': enabled, 'compatibilityEnabled': False, 'compatibilityOptedOut': False,
            'order': None, 'shard': 0, 'currentVpks': current, 'disabledVpks': disabled,
            'originalVpkNames': original}


class ModManagerTest(AppFixture):
    """Deadlock Mod Manager keeps switched-off mods in addons under other names and records them in .dmm.json."""

    def write_dmm(self, addons, mods):
        (addons / '.dmm.json').write_text(json.dumps({'version': 3, 'mods': mods}), encoding='utf-8')

    def dmm_folder(self, chat_enabled):
        citadel = self.configure_install()
        addons = citadel / 'addons'
        other = addons / 'pak02_dir.vpk'
        pack({'other-mod/kept.txt': b'enabled other mod'}, other)
        pack({'other-mod/off.txt': b'disabled other mod'}, addons / '645484_pak42_dir.vpk')
        mods = {'645497': dmm_record(True, ['pak02_dir.vpk'], [], ['pak05_dir.vpk']),
                '645484': dmm_record(False, [], ['645484_pak42_dir.vpk'], ['pak42_dir.vpk'])}
        if chat_enabled:
            chat = self.own_vpk(addons / 'pak03_dir.vpk')
            mods[LOCAL_ID] = dmm_record(True, ['pak03_dir.vpk'], [], ['switchboard_dir.vpk'])
        else:
            chat = self.own_vpk(addons / f'{LOCAL_ID}_switchboard_dir.vpk')
            mods[LOCAL_ID] = dmm_record(False, [], [chat.name], ['switchboard_dir.vpk'])
        self.write_dmm(addons, mods)
        return citadel, chat, other

    def test_switched_off_copy_is_not_enabled_and_does_not_block_updates(self):
        citadel, disabled, other = self.dmm_folder(chat_enabled=False)
        enabled = self.own_vpk(citadel / 'addons/pak03_dir.vpk')
        mods = json.loads((citadel / 'addons/.dmm.json').read_text())['mods']
        mods['other-import'] = dmm_record(True, ['pak03_dir.vpk'], [], ['switchboard_dir.vpk'])
        self.write_dmm(citadel / 'addons', mods)
        before_disabled, before_gi = disabled.read_bytes(), (citadel / 'gameinfo.gi').read_bytes()
        self.app.refresh_installed()
        self.assertEqual(self.app.installed, [enabled])
        self.assertEqual(self.app.disabled_copies, [disabled])
        self.app.save({'fontSize': 25})
        self.assertIsNotNone(self.app.rebuild())
        self.assertEqual(self.app.error, '')
        self.assertRegex(VPK(enabled).read('panorama/scripts/switchboard_boot.vts_c'), rb'"fontSize"\s*:\s*25')
        self.assertEqual(disabled.read_bytes(), before_disabled, 'A switched-off copy was rewritten')
        self.assertEqual((citadel / 'gameinfo.gi').read_bytes(), before_gi)
        with self.request('/api/state') as response:
            state = json.load(response)
        self.assertEqual((state['installedCopies'], state['disabledCopies'], state['modManager']), (1, 1, True))

    def test_pak_names_listed_as_disabled_in_dmm_json_are_not_counted(self):
        citadel = self.configure_install()
        first = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        second = self.own_vpk(citadel / 'addons/pak81_dir.vpk')
        self.write_dmm(citadel / 'addons', {'a': dmm_record(True, ['pak80_dir.vpk'], [], ['x_dir.vpk']),
                                            'b': dmm_record(False, ['pak81_dir.vpk'], [], ['y_dir.vpk'])})
        self.app.refresh_installed()
        self.assertEqual(self.app.installed, [first])
        self.assertEqual(self.app.disabled_copies, [second])

    def test_unreadable_dmm_json_still_counts_only_pak_names(self):
        citadel = self.configure_install()
        (citadel / 'addons/.dmm.json').write_text('{not json', encoding='utf-8')
        enabled = self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        self.own_vpk(citadel / 'addons/switchboard_dir.vpk')
        self.app.refresh_installed()
        self.assertEqual(self.app.installed, [enabled])
        self.assertTrue(self.app.dmm)

    def test_install_with_mod_manager_and_no_enabled_copy_explains_and_writes_nothing(self):
        citadel, disabled, other = self.dmm_folder(chat_enabled=False)
        before = {p: p.read_bytes() for p in (citadel / 'addons').iterdir()}
        before_gi = (citadel / 'gameinfo.gi').read_bytes()
        with self.assertRaisesRegex(ValueError, 'turned off in Deadlock Mod Manager'):
            self.app.install()
        disabled.unlink()
        del before[disabled]
        with self.assertRaisesRegex(ValueError, 'Mod Manager'):
            self.app.install()
        self.assertEqual({p: p.read_bytes() for p in (citadel / 'addons').iterdir()}, before)
        self.assertEqual((citadel / 'gameinfo.gi').read_bytes(), before_gi)

    def test_install_with_mod_manager_connects_the_enabled_copy_only(self):
        citadel, chat, other = self.dmm_folder(chat_enabled=True)
        names = sorted(p.name for p in (citadel / 'addons').iterdir())
        before_gi, before_other = (citadel / 'gameinfo.gi').read_bytes(), other.read_bytes()
        self.app.save({'fontSize': 27})
        self.app.install()
        self.assertEqual(sorted(p.name for p in (citadel / 'addons').iterdir()), names)
        self.assertEqual((citadel / 'gameinfo.gi').read_bytes(), before_gi)
        self.assertEqual(other.read_bytes(), before_other)
        boot = VPK(chat).read('panorama/scripts/switchboard_boot.vts_c')
        self.assertIn(self.app.token.encode(), boot)
        self.assertRegex(boot, rb'"fontSize"\s*:\s*27')

    def test_state_notices_a_copy_turned_on_after_startup(self):
        citadel = self.configure_install()
        with self.request('/api/state') as response:
            self.assertFalse(json.load(response)['installed'])
        self.app.pending = False
        self.own_vpk(citadel / 'addons/pak80_dir.vpk')
        with self.request('/api/state') as response:
            state = json.load(response)
        self.assertTrue(state['installed'])
        self.assertTrue(state['pending'], 'A newly enabled copy should be brought up to date')


class GameInfoTest(unittest.TestCase):
    def test_commented_line_does_not_count_and_bom_is_kept(self):
        original = ('\ufeff"GameInfo"\r\n{\r\n  FileSystem\r\n  {\r\n    SearchPaths\r\n    {\r\n'
                    '      // Game citadel/addons\r\n      Game citadel\r\n    }\r\n  }\r\n}\r\n').encode('utf-8')
        updated = launcher.gameinfo_with_addons(original)
        self.assertTrue(updated.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\xef\xbb\xbf', updated[3:])
        lines = [l for l in updated.decode('utf-8-sig').split('\r\n') if 'citadel/addons' in l]
        self.assertEqual(len(lines), 2)
        self.assertIn('Game                citadel/addons', [l.strip() for l in lines])
        self.assertIn('// Game citadel/addons', [l.strip() for l in lines])
        self.assertIsNone(launcher.gameinfo_with_addons(updated))

    def test_no_bom_stays_without_bom(self):
        updated = launcher.gameinfo_with_addons(b'SearchPaths\n{\nGame citadel\n}\n')
        self.assertFalse(updated.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'citadel/addons', updated)

    def test_never_inserts_inside_the_mod_manager_block(self):
        vanilla = (f'"GameInfo"\n{{\nFileSystem\n{{\n{launcher.DMM_START}\nSearchPaths\n{{\nGame citadel\n}}\n'
                   f'{launcher.DMM_END}\n}}\n}}\n').encode()
        with self.assertRaisesRegex(ValueError, 'Mod Manager'):
            launcher.gameinfo_with_addons(vanilla)
        modded = vanilla.replace(b'Game citadel\n', b'Game citadel/addons\nGame citadel\n')
        self.assertIsNone(launcher.gameinfo_with_addons(modded))
        mixed = b'SearchPaths_Extra\n// SearchPaths {\n' + vanilla
        with self.assertRaises(ValueError):
            launcher.gameinfo_with_addons(mixed)


class HelperRobustnessTest(AppFixture):
    def test_second_server_cannot_share_the_port(self):
        first = launcher.Server(('127.0.0.1', 0), launcher.handler(self.app))
        try:
            with self.assertRaises(OSError):
                second = launcher.Server(('127.0.0.1', first.server_port), launcher.handler(self.app))
                second.server_close()
        finally:
            first.server_close()

    def test_second_launch_opens_the_running_customiser(self):
        args = type('Args', (), {'data_dir': self.app.data / 'second', 'game_root': None,
                                 'no_install': True, 'no_browser': False, 'port': self.server.server_port})()
        with patch('launcher.Server', side_effect=OSError('in use')), \
                patch('launcher.resolve_game', return_value=None), \
                patch('launcher.webbrowser.open') as opened:
            launcher.run(args)
        opened.assert_called_once_with(f'http://127.0.0.1:{self.server.server_port}/')

    def test_port_used_by_another_program_shows_a_message(self):
        args = ['launcher.py', '--no-browser', '--data-dir', str(self.app.data / 'x'), '--port', '9']
        with patch('sys.argv', args), patch('launcher.Server', side_effect=OSError('in use')), \
                patch('launcher.resolve_game', return_value=None), \
                patch('launcher.existing_customiser', return_value=False), \
                patch('launcher.show_error') as shown:
            with self.assertRaises(SystemExit):
                launcher.main()
        self.assertIn('port 9', shown.call_args[0][0])

    def test_windowed_errors_use_a_message_box(self):
        if launcher.os.name != 'nt':
            self.skipTest('Windows only')
        import ctypes
        with patch.object(launcher.sys, 'frozen', True, create=True), \
                patch.object(ctypes.windll.user32, 'MessageBoxW') as box, patch('sys.stderr', None):
            launcher.show_error('Port unavailable')
        self.assertEqual(box.call_args[0][1], 'Port unavailable')

    def test_failed_writes_keep_pending_retry_with_backoff_and_read_plainly(self):
        locked = PermissionError(13, 'Access is denied', str(self.app.data / 'game/addons/pak80_dir.vpk'))
        locked.winerror = 5
        self.app.pending = True
        with patch.object(self.app, 'rebuild', side_effect=locked):
            delays = [self.app.worker_step(2)]
            for _ in range(6):
                delays.append(self.app.worker_step(delays[-1]))
        self.assertEqual(delays[:3], [4, 8, 16])
        self.assertEqual(delays[-1], 60)
        self.assertTrue(self.app.pending)
        self.assertIn('pak80_dir.vpk', self.app.error)
        self.assertNotIn('WinError', self.app.error)
        self.assertEqual(self.app.worker_step(60), 2)
        self.assertFalse(self.app.pending)
        self.assertEqual(self.app.error, '')

    def test_backups_keep_the_original_and_the_last_three(self):
        target = self.app.data / 'game/pak80_dir.vpk'
        for index in range(7):
            self.app.backup('pak80_dir', target, b'version %d' % index, '.vpk')
        kept = sorted(p.read_bytes() for p in (self.app.data / 'backups').glob('*.vpk'))
        self.assertEqual(kept, [b'version 0', b'version 4', b'version 5', b'version 6'])
        original = [p for p in (self.app.data / 'backups').glob('*-original-*.vpk')]
        self.assertEqual([p.read_bytes() for p in original], [b'version 0'])
        # Re-backing up identical bytes reuses the file instead of adding one.
        self.app.backup('pak80_dir', target, b'version 6', '.vpk')
        self.assertEqual(len(list((self.app.data / 'backups').glob('*.vpk'))), 4)

    def test_legacy_backups_are_pruned_to_oldest_and_newest_three(self):
        folder = self.app.data / 'backups'
        folder.mkdir()
        for index in range(6):
            path = folder / f'pak99_dir-{index:016x}.vpk'
            path.write_bytes(b'old %d' % index)
            launcher.os.utime(path, ns=(index * 10 ** 9, index * 10 ** 9))
        launcher.App.prune_legacy_backups(folder)
        self.assertEqual(sorted(p.name[-6:-4] for p in folder.glob('*.vpk')), ['00', '03', '04', '05'])

    def test_artwork_without_an_image_saves_everything_else(self):
        query = urlencode({'token': self.app.token, 'settings': json.dumps({'fontSize': 24, 'artwork': True})})
        with self.request('/sync.png?' + query, token=False) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.app.settings['fontSize'], 24)
        self.assertFalse(self.app.settings['artwork'])
        with self.request('/api/config', {'fontSize': 26, 'artwork': True}) as response:
            state = json.load(response)
        self.assertEqual(state['settings']['fontSize'], 26)
        self.assertFalse(state['settings']['artwork'])
        self.assertIn('artwork', state['notice'].lower())
        with self.request('/api/config', {'fontSize': 26}) as response:
            self.assertEqual(json.load(response)['notice'], '')

    def test_download_needs_no_prior_build_and_uses_the_release_name(self):
        self.assertFalse(self.app.package.exists())
        with self.request('/download/switchboard.zip') as response:
            self.assertIn(launcher.artifact_name('Mod'), response.headers['Content-Disposition'])
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertIn('switchboard_dir.vpk', archive.namelist())
                self.assertIn('CHAT MOD', archive.read('README.txt').decode())

    def test_browser_requests_need_the_header_token_and_our_origin(self):
        self.assert_http_error(403, '/api/state?' + urlencode({'token': self.app.token}), token=False)
        self.assert_http_error(403, '/download/switchboard.zip?' + urlencode({'token': self.app.token}), token=False)
        self.assert_http_error(403, '/api/state', origin='https://untrusted.invalid')
        self.assert_http_error(403, '/download/switchboard.zip', origin='http://127.0.0.1:1')
        with self.request('/api/state', origin=self.url) as response:
            self.assertEqual(json.load(response)['version'], launcher.VERSION)

    def test_pasted_folder_paths_accept_quotes_and_subfolders(self):
        game = self.fake_game()
        for text in [str(game), f'"{game}"', f"  '{game}'  ", str(game / 'game' / 'citadel'),
                     str(game / 'game'), str(game / 'game/citadel/addons')]:
            with self.subTest(text=text):
                self.assertEqual(launcher.game_folder(text), game.resolve())
        with self.assertRaises(ValueError):
            launcher.game_folder(str(self.app.data))
        with self.request('/api/game-folder', {'path': f'"{game / "game" / "citadel"}"'}) as response:
            self.assertTrue(json.load(response)['gameFound'])
        self.assertEqual(self.app.game, game.resolve())

    def test_moved_game_folder_is_detected_again(self):
        game = self.fake_game()
        data = self.app.data / 'restart'
        data.mkdir()
        (data / 'installation.json').write_text(json.dumps({'game': str(self.app.data / 'moved-away')}))
        with patch('launcher.find_game', return_value=game):
            self.assertEqual(launcher.resolve_game(data), game)
        (data / 'installation.json').write_text(json.dumps({'game': str(game)}))
        with patch('launcher.find_game', return_value=None):
            self.assertEqual(launcher.resolve_game(data), game)


class CustomiserPageTest(unittest.TestCase):
    pages = [ROOT / 'web/index.html', ROOT / 'web/app.js', ROOT / 'web/style.css',
             ROOT / 'gallery/index.html', ROOT / 'gallery/app.js', ROOT / 'gallery/style.css']

    def test_no_version_literals_or_retired_wording(self):
        retired = ['Ready when you are', 'FIND YOUR FREQUENCY', 'ON THE AIR', 'CHAT WORKSHOP', 'DESIGN PREVIEW',
                   'Quit helper', 'customizer', 'Your own channel', 'THE CITY IS LISTENING', '↗', '↻', '↥']
        for page in self.pages:
            text = page.read_text(encoding='utf-8')
            with self.subTest(page=page.name):
                if page.suffix == '.html':
                    self.assertNotRegex(text, r'\b0\.\d+\.\d+\b')
                for phrase in retired:
                    self.assertNotIn(phrase, text)

    def test_no_text_smaller_than_12px(self):
        for page in [ROOT / 'web/style.css', ROOT / 'gallery/style.css']:
            sizes = [int(s) for s in re.findall(r'font-size:\s*(\d+)px', page.read_text(encoding='utf-8'))]
            with self.subTest(page=page.parent.name):
                self.assertTrue(sizes)
                self.assertGreaterEqual(min(sizes), 12)

    def test_tabs_are_accessible_and_motion_can_be_reduced(self):
        html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
        self.assertIn('role="tablist"', html)
        self.assertEqual(html.count('role="tab"'), html.count('role="tabpanel"'))
        self.assertIn('prefers-reduced-motion', (ROOT / 'web/style.css').read_text(encoding='utf-8'))
        script = (ROOT / 'web/app.js').read_text(encoding='utf-8')
        self.assertIn('ArrowRight', script)
        self.assertNotIn('token=', script, 'The browser UI must not put the token in URLs')

    def test_gallery_manifest_matches_the_release(self):
        manifest = json.loads((ROOT / 'gallery/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], launcher.VERSION)
        for item in manifest['items']:
            self.assertTrue((ROOT / 'gallery' / item['file']).is_file())


if __name__=='__main__':unittest.main()

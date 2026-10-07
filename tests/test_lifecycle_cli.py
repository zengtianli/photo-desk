"""`photodesk config | update | shortcuts | login | automation | cancel | start | quit`, end to end and off screen.

The command line is the Python engine; these eight words belong to the app bundle (the「配置与更新…」window's
settings, version and release channel, the saved shortcuts, the system login item, a running PhotoDesk's own
actions). So the engine forwards them to the compiled app executable, which answers in Sources/AgentCommands.swift
before any NSApplication exists. This test drives that chain as real processes:

1. the engine forwards the words unchanged and brings stdout, stderr and the exit code back unchanged;
2. the commands read and write the settings the window's configuration does (the preferences domain);
3. a running app follows what a command changed and never writes an old value back, including two commands back to
   back and an import while sync is on: the executable is started a second time as the app itself
   (`--lifecycle-follow-probe`: the real model and the production wiring, activation policy prohibited, the shared
   window built but never ordered in) and every verdict reads the stored value with a fresh process;
4. that running app answers `automation pause | resume` and `cancel`;
5. `start` really starts the throwaway bundle through the system, hidden and not activated (no window reaches the
   screen, the front app stays the front app), and `quit` ends it;
6. `update install` looks the release up and replaces nothing here, and `--permissions-probe` reads the system's
   grants without asking for any.

Everything is isolated: a copy of the executable inside a throwaway bundle with a test bundle identifier, a
PhotoDesk.Test.* preferences domain, temporary support and "cloud" directories, a private notification channel, a
marked synthetic library folder and a stand-in engine that only sleeps. No window is shown, nothing reaches the
Dock, no hotkey is registered, the login item is never changed, the owner's settings and photo library are never
opened, and no installed or running PhotoDesk is signalled. `update check` reads the public release record of the
product's GitHub repository (the same request the window's 检查更新 makes); PHOTODESK_TEST_OFFLINE=1 skips it.

PHOTODESK_NATIVE names the compiled app executable (scripts/test.sh builds it); PHOTODESK_APP names an assembled
PhotoDesk.app whose own frozen engine and executable are then driven in the same isolation (build.sh does, and it
can be pointed at the installed app).
"""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import desk_cli  # noqa: E402
from photocli import cli as photocli  # noqa: E402

NATIVE = os.environ.get('PHOTODESK_NATIVE')
ASSEMBLED = os.environ.get('PHOTODESK_APP')
BUNDLE = 'test.tianli.photodesk.lifecycle'
PRODUCT = 'cyou.tianli.PhotoDesk'
HEADQUARTERS = Path.home() / 'Dev/tools/dev/lib/tools/macapp/swift-shared/AppLifecycleCLI.swift'
OFF = 'iCloud 配置同步已关闭'
PREFERENCES = {'automatic': True, 'includeShared': True, 'recognizeContent': False, 'refreshSeconds': 60, 'batchSize': 12,
               'eventHours': 3, 'eventKilometers': 8, 'meetingMinutes': 90, 'petNames': '', 'preselectDuplicates': True,
               'thumbnailWidth': 180, 'appearance': 'light', 'initialTrack': '全部'}
KEY, SHORTCUTS = 'product.preferences.v1', 'shortcuts.v1'
CONTROL_OPTION = 4096 | 2048  # Carbon controlKey | optionKey


def chord(code, key, scope='application', modifiers=CONTROL_OPTION):
    return {'chord': {'code': code, 'modifiers': modifiers, 'key': key}, 'scope': scope}


def windows_on_screen(pid):
    """The window server's own list of what is ordered in, for one process (owner and bounds need no permission)."""
    import Quartz
    rows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    return [dict(row) for row in rows if row.get('kCGWindowOwnerPID') == pid]


def front_pid():
    """The process that has the keyboard, as fresh processes read it from the system; None when it cannot be told."""
    front = subprocess.run(['/usr/bin/lsappinfo', 'front'], capture_output=True, text=True, timeout=30).stdout.strip()
    if not front:
        return None
    told = subprocess.run(['/usr/bin/lsappinfo', 'info', '-only', 'pid', front], capture_output=True, text=True, timeout=30).stdout
    digits = ''.join(ch for ch in told.split('=')[-1] if ch.isdigit())
    return int(digits) if digits else None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Chain(unittest.TestCase):
    """One isolated place and the two ways in: `self.photodesk` (the engine) and `self.direct` (the app executable)."""
    binary: Path
    engine: list
    root: Path
    env: dict
    suite: str
    followers: list

    @classmethod
    def isolate(cls, prefix):
        cls.folder = tempfile.TemporaryDirectory(prefix=prefix)
        cls.root = Path(cls.folder.name).resolve()
        cls.suite = 'PhotoDesk.Test.Lifecycle.' + uuid.uuid4().hex
        cls.support, cls.cloud, cls.demo = cls.root / 'support', cls.root / 'cloud', cls.root / 'demo'
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith(('PHOTOCLI_', 'PHOTODESK_', 'APP_LIFECYCLE_'))}
        # Every process of this test, the engine included, gets the synthetic library folder and a temporary data root.
        cls.env.update(APP_LIFECYCLE_SUPPORT_DIR=str(cls.support), APP_LIFECYCLE_CLOUD_DIR=str(cls.cloud),
                       PHOTODESK_PREFERENCES_SUITE=cls.suite, PHOTODESK_DEMO_ROOT=str(cls.demo),
                       PHOTODESK_DATA_ROOT=str(cls.demo / 'state'))
        cls.followers = []

    @classmethod
    def tearDownClass(cls):
        for process in cls.followers:
            process.kill()
            process.wait(timeout=10)
        subprocess.run(['/usr/bin/defaults', 'delete', cls.suite], capture_output=True, timeout=30)
        # An emptied named domain leaves a 42-byte plist behind once the last process using it has gone.
        (Path.home() / 'Library/Preferences' / (cls.suite + '.plist')).unlink(missing_ok=True)
        cls.folder.cleanup()

    def setUp(self):
        """Every test starts from the same settings: sync off, the seeded preferences, no shortcuts."""
        subprocess.run(['/usr/bin/defaults', 'delete', self.suite], capture_output=True, timeout=30)
        self.store(KEY, PREFERENCES)
        for folder in (self.support, self.cloud):
            shutil.rmtree(folder, ignore_errors=True)

    # The preferences domain, written and read by `defaults` (a fresh process each time), never by the test process.
    def store(self, key, value):
        subprocess.run(['/usr/bin/defaults', 'write', self.suite, key, '-data', json.dumps(value, ensure_ascii=False).encode().hex()],
                       check=True, capture_output=True, timeout=30)

    def domain(self):
        done = subprocess.run(['/usr/bin/defaults', 'export', self.suite, '-'], capture_output=True, timeout=30)
        return plistlib.loads(done.stdout) if done.returncode == 0 and done.stdout else {}

    def stored(self, key):
        raw = self.domain().get(key)
        return json.loads(raw) if raw else None

    def photodesk(self, *words, env=None, cwd=None):
        return subprocess.run([*self.engine, *words], env=env or self.env, cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)

    def direct(self, *words, env=None):
        return subprocess.run([str(self.binary), *words], env=env or self.env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)

    def call(self, *words, expect=0, env=None):
        done = self.photodesk(*words, '--json', env=env)
        self.assertEqual(done.returncode, expect, (words, done.stdout, done.stderr))
        body = json.loads(done.stdout)
        self.assertIs(body['ok'], expect == 0, body)
        if expect:
            self.assertTrue(body['error']['code'] and body['error']['message'], body)
        return body

    def envelope(self, preferences, shortcuts=None):
        values = {'defaults.' + KEY: {'$data': __import__('base64').b64encode(json.dumps(preferences, ensure_ascii=False).encode()).decode()}}
        if shortcuts is not None:
            values['defaults.' + SHORTCUTS] = {'$data': __import__('base64').b64encode(json.dumps(shortcuts).encode()).decode()}
        return {'version': 1, 'product': PRODUCT, 'values': values}

    def mirrored(self):
        """The preferences as the isolated "cloud" copy holds them."""
        try:
            raw = json.loads((self.cloud / (PRODUCT + '.json')).read_text())['values']['defaults.' + KEY]['$data']
        except (OSError, ValueError, KeyError):
            return None
        return json.loads(__import__('base64').b64decode(raw))

    def start_app(self, *extra):
        """This executable as the running app: (process, live env, read state, wait until, state file)."""
        live = dict(self.env, APP_LIFECYCLE_FOLLOW_CHANNEL='test.' + uuid.uuid4().hex, PHOTODESK_BACKGROUND='1',
                    PHOTODESK_LIBRARY=str(self.demo))
        state = self.root / f'app-{uuid.uuid4().hex[:8]}.json'
        complaints = state.with_suffix('.err')
        with complaints.open('wb') as errors:
            process = subprocess.Popen([str(self.binary), '--lifecycle-follow-probe', str(state), *extra], env=live,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
        self.followers.append(process)
        deadline = time.monotonic() + 30
        while not state.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.05)
        self.assertTrue(state.exists(), complaints.read_text() or 'the app did not report')

        def seen():
            for _ in range(60):
                try:
                    return json.loads(state.read_text())
                except (OSError, ValueError):
                    time.sleep(0.02)
            raise AssertionError('app state unreadable')

        def reaches(test, seconds=8.0):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if test(seen()):
                    return True
                time.sleep(0.05)
            return False

        return process, live, seen, reaches, state

    def stop_app(self, process):
        process.terminate()
        process.wait(timeout=15)
        self.followers.remove(process)

    def follow(self):
        """A running app follows `config sync` and `config import` and never puts an old value back."""
        process, live, seen, reaches, _ = self.start_app()

        def holds(want, seconds=1.0):
            """The app's configuration, the window's switch and the stored switch (read by a fresh process) all stay put."""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                now = seen()
                if now['enabled'] is not want or now['window_switch'] is not want or self.call('config', 'status')['sync_enabled'] is not want:
                    return False
                time.sleep(0.05)
            return True

        def told_by_app(seconds=10.0):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                showing, told = seen()['status'], self.call('config', 'status', env=live)['sync_status']
                if told['live'] is True and told['from'] == 'app' and told['text'] == showing and told['at']:
                    return True
                time.sleep(0.1)
            return False

        first = seen()
        # The app is running as an app, and nothing of it is on screen.
        self.assertEqual((first['policy_prohibited'], first['windows_on_screen']), (True, 0))
        self.assertTrue(all(first['window_built'].values()), first['window_built'])  # the shared window, built as the menu item builds it
        self.assertEqual((first['enabled'], first['window_switch'], first['status']), (False, False, OFF))
        for attempt in range(3):
            on = self.call('config', 'sync', 'on', '--yes', env=live)
            self.assertTrue(on['changed'] and on['app_running'], on)  # the command saw the running app
            self.assertTrue(reaches(lambda s: s['enabled'] is True and s['window_switch'] is True and s['status'] != OFF), f'follows sync on ({attempt + 1})')
            self.assertTrue(holds(True), f'sync on is not written back ({attempt + 1})')
            if attempt == 0:
                # 开关下面那句话: while the app runs, `config status` tells the sentence the app itself is showing.
                self.assertTrue(told_by_app(), (seen()['status'], self.call('config', 'status', env=live)['sync_status']))
            self.call('config', 'sync', 'off', '--yes', env=live)
            self.assertTrue(reaches(lambda s: s['enabled'] is False and s['window_switch'] is False and s['status'] == OFF), f'follows sync off ({attempt + 1})')
            self.assertTrue(holds(False), f'sync off is not written back ({attempt + 1})')
        # Two commands back to back: whatever the app does about the first must not undo the second after it has returned.
        for attempt in range(3):
            self.call('config', 'sync', 'on', '--yes', env=live)
            self.call('config', 'sync', 'off', '--yes', env=live)
            self.assertTrue(reaches(lambda s: s['enabled'] is False and s['window_switch'] is False and s['status'] == OFF), f'settles off after on, off ({attempt + 1})')
            self.assertTrue(holds(False, 1.5), f'on, off back to back stays off ({attempt + 1})')
        self.call('config', 'sync', 'on', '--yes', env=live)
        self.call('config', 'sync', 'off', '--yes', env=live)
        self.call('config', 'sync', 'on', '--yes', env=live)
        self.assertTrue(reaches(lambda s: s['enabled'] is True and s['window_switch'] is True and s['status'] != OFF), 'settles on after on, off, on')
        self.assertTrue(holds(True, 1.5), 'on, off, on back to back stays on')

        def imports(preferences, shortcuts=None):
            path = self.root / f'in-{uuid.uuid4().hex[:8]}.json'
            path.write_text(json.dumps(self.envelope(preferences, shortcuts)))
            return self.call('config', 'import', str(path), '--yes', env=live)

        def stays(preferences, cloud, seconds=1.5):
            """From the command's return on: the stored preferences (a fresh process reads them) and, with sync on,
            the cloud copy keep the imported values. PhotoDesk's reload saves what it adopts, so this is where a
            reload that saved the settings it had in memory would show."""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if self.stored(KEY) != preferences or (cloud and self.mirrored() != preferences):
                    return False
                time.sleep(0.05)
            return True

        # Sync is on and the app is running: an import, then two imports back to back. The stored values and the cloud
        # copy stay the imported ones, the app re-reads them, and the switch stays on.
        wide = dict(PREFERENCES, thumbnailWidth=230, appearance='dark')
        before = seen()
        done = imports(wide, {'search': chord(3, 'F')})
        self.assertTrue(done['imported'] and done['sync']['completed'], done)
        self.assertTrue(stays(wide, cloud=True), 'an import while sync is on is not undone')
        self.assertTrue(reaches(lambda s: s['changes'] > before['changes'] and s['thumbnailWidth'] == 230 and s['appearance'] == 'dark'
                                and s['shortcuts'] == {'search': '⌃⌥F application'}), 'the app re-reads imported settings and shortcuts')
        self.assertTrue(stays(wide, cloud=True, seconds=1.0), 'the reload keeps the imported settings')
        narrow, middle = dict(PREFERENCES, thumbnailWidth=150), dict(PREFERENCES, thumbnailWidth=200, eventHours=5)
        imports(narrow)
        imports(middle)
        self.assertTrue(stays(middle, cloud=True), 'two imports back to back end on the second')
        self.assertTrue(reaches(lambda s: s['thumbnailWidth'] == 200 and s['shortcuts'] == {}), 'the app ends on the second import')
        self.assertTrue(stays(middle, cloud=True, seconds=1.0), 'and stays there')
        self.assertTrue(holds(True, 0.6), 'an import leaves the switch alone')
        self.call('config', 'sync', 'off', '--yes', env=live)
        self.assertTrue(reaches(lambda s: s['enabled'] is False and s['window_switch'] is False and s['status'] == OFF), 'back to off')
        # Sync off: an import still reaches the app and stays.
        imports(wide)
        self.assertTrue(stays(wide, cloud=False), 'an import while sync is off is not undone')
        self.assertTrue(reaches(lambda s: s['thumbnailWidth'] == 230), 'the app re-reads it')
        self.assertTrue(holds(False, 0.6), 'and the switch stays off')
        # While the app runs it owns the bindings: the command reads them and refuses to change them.
        self.store(SHORTCUTS, {'search': chord(3, 'F')})
        listed = self.call('shortcuts', env=live)
        self.assertTrue(listed['app_running'] and listed['bound'] == 1, listed)
        self.assertEqual(self.call('shortcuts', 'clear', '--all', expect=1, env=live)['error']['code'], 'app_running')
        self.assertEqual(self.call('shortcuts', 'set', 'pause', 'ctrl+opt+p', expect=1, env=live)['error']['code'], 'app_running')
        self.assertEqual(self.stored(SHORTCUTS), {'search': chord(3, 'F')})
        last = seen()
        self.assertEqual((last['policy_prohibited'], last['windows_on_screen']), (True, 0))
        self.assertGreater(last['tick'], first['tick'])
        self.stop_app(process)
        self.assertIs(self.call('config', 'status')['app_running'], False)


@unittest.skipUnless(NATIVE and Path(NATIVE).is_file(), 'set PHOTODESK_NATIVE to the compiled app executable (scripts/test.sh does)')
class LifecycleCommandTests(Chain):
    @classmethod
    def setUpClass(cls):
        cls.isolate('photodesk-lifecycle-')
        app = cls.root / 'PhotoDesk.app'
        (app / 'Contents/MacOS').mkdir(parents=True)
        cls.binary = app / 'Contents/MacOS/PhotoDesk'
        shutil.copy2(NATIVE, cls.binary)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': BUNDLE, 'CFBundleExecutable': 'PhotoDesk', 'CFBundlePackageType': 'APPL',
            'CFBundleShortVersionString': '1.2', 'CFBundleVersion': '7', 'LSUIElement': True}))
        # A stand-in for the bundled engine: it never answers, so a task the app starts stays in progress until cancelled.
        stand_in = app / 'Contents/Resources/Engine/photo-engine'
        stand_in.parent.mkdir(parents=True)
        stand_in.write_text('#!/bin/sh\nexec /bin/sleep 90\n')
        stand_in.chmod(0o755)
        (cls.demo / 'state').mkdir(parents=True)
        (cls.demo / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1', 'photos': []}))
        # The command as an agent types it: the engine from source, which forwards to the executable named by PHOTODESK_NATIVE.
        cls.engine = [sys.executable, str(ROOT / 'backend/bridge.py')]
        cls.env['PHOTODESK_NATIVE'] = str(cls.binary)

    def test_help_lines_are_the_shared_layers_own_and_reach_the_top_level_help(self):
        shared = self.direct('config', '--help')
        self.assertEqual(shared.returncode, 0)
        top = self.photodesk('--help').stdout
        for line in photocli.LIFECYCLE_READS + photocli.LIFECYCLE_WRITES:
            self.assertIn(line + '\n', shared.stdout)       # the engine's copy of the line is the shared layer's line
            self.assertIn('\n  ' + line + '\n', top)         # and it is listed in `photodesk --help`
        self.assertIn('仅在窗口中：' + photocli.LIFECYCLE_WINDOW_ONLY + '\n', shared.stdout)
        # The upgrade and the sentence under the switch have commands now (update install, config status), and the one
        # item left without a command, 导入验收测试图…, is a boundary the product drew long before this table: it sits
        # under 仅在窗口中 and says so. Neither help keeps a 暂无命令 heading.
        self.assertNotIn('暂无命令', shared.stdout)
        self.assertNotIn('暂无命令', top)
        self.assertTrue(any(line.startswith('  update install ') for line in photocli.LIFECYCLE_WRITES))
        self.assertIn('同步状态', photocli.LIFECYCLE_READS[0])
        window_only = top.split('仅在窗口中：')[1].split('\n\nOptions:')[0]   # the list itself, not the command summaries after it
        self.assertIn(photocli.LIFECYCLE_WINDOW_ONLY, window_only)
        self.assertNotIn('升级到新版', window_only)
        boundary = [line for line in window_only.splitlines() if '导入验收测试图' in line]
        self.assertEqual(len(boundary), 1, window_only)
        self.assertTrue(boundary[0].strip().startswith('导入验收测试图…（产品边界：'), boundary[0])   # click indents the help body
        self.assertIn('退出码', shared.stdout)
        for verb in desk_cli.APP_VERBS:
            ours, theirs = self.photodesk(verb, '--help'), self.direct(verb, '--help')
            self.assertEqual((ours.returncode, ours.stdout, ours.stderr), (0, theirs.stdout, ''), verb)
            self.assertIn('photodesk ' + verb, ours.stdout.split('\n「')[0].split('\n设置窗口')[0].split('\n运行中')[0].split('\n取消运行')[0])  # in the usage block
            self.assertIn('退出码', ours.stdout)
            self.assertIn('--json', ours.stdout)
            self.assertRegex(top, rf'(?m)^  {verb}\s')   # listed under Commands
        # The help names no setting, so it is answered even where a command would be refused.
        bare = {k: v for k, v in self.env.items() if k != 'APP_LIFECYCLE_SUPPORT_DIR'}
        self.assertEqual(self.photodesk('config', '--help', env=bare).stdout, shared.stdout)

    def test_words_output_and_exit_code_pass_through_unchanged(self):
        cases = ((('config', 'status', '--json'), 0), (('config', 'status'), 0), (('config', '--json'), 0),
                 (('config', 'bogus', '--json'), 2), (('config', 'status', '--no-such', '--json'), 2), (('config', 'bogus'), 2),
                 (('update', '--json'), 2), (('config', 'export', '--json'), 2), (('config', 'sync', 'maybe', '--json'), 2),
                 (('config', 'sync', 'on', '--json'), 2), (('config', 'import', str(self.root / 'absent.json'), '--yes', '--json'), 1),
                 (('shortcuts', '--json'), 0), (('shortcuts',), 0), (('shortcuts', 'list', '--json'), 0),
                 (('shortcuts', 'bogus', '--json'), 2), (('shortcuts', '--no-such', '--json'), 2), (('shortcuts', 'bogus'), 2),
                 (('shortcuts', 'scope', 'pause', '--json'), 2), (('shortcuts', 'clear', '--json'), 2),
                 (('shortcuts', 'scope', 'nosuch', 'global', '--json'), 2), (('shortcuts', 'scope', 'pause', 'global', '--json'), 1),
                 (('login', '--json'), 0), (('login', 'status'), 0), (('login', 'maybe', '--json'), 2),
                 (('login', 'on', '--dry-run', '--json'), 0), (('login', 'on', '--json'), 2), (('login', 'on', '--yes', '--json'), 1),
                 (('login', 'status', '--no-such', '--json'), 2),
                 (('automation', '--json'), 0), (('automation', 'status'), 0), (('automation', 'stop', '--json'), 2),
                 (('automation', 'pause', '--json'), 1), (('automation', 'resume'), 1),
                 (('cancel', '--json'), 0), (('cancel',), 0), (('cancel', 'now', '--json'), 2), (('cancel', '--no-such'), 2),
                 # `update install`: a wrong word is a usage error before anything is looked up.
                 (('update', 'install', '--no-such', '--json'), 2), (('update', 'install', 'extra', '--json'), 2),
                 (('shortcuts', 'set', '--json'), 2), (('shortcuts', 'set', 'pause', '--json'), 2),
                 (('shortcuts', 'set', 'nosuch', 'ctrl+opt+p', '--json'), 2), (('shortcuts', 'set', 'pause', 'hyper+p', '--json'), 2),
                 (('shortcuts', 'set', 'pause', 'ctrl+opt+p', 'everywhere', '--json'), 2), (('shortcuts', 'set', 'pause', 'p', '--json'), 1),
                 (('shortcuts', 'set', 'search', 'ctrl+opt+f', 'global'), 1),
                 # No app is running and this run is not the complete isolated one: `start` refuses, `quit` has nothing to end.
                 (('start', '--json'), 1), (('start',), 1), (('start', 'now', '--json'), 2), (('start', '--no-such'), 2),
                 (('quit', '--json'), 0), (('quit',), 0), (('quit', 'now', '--json'), 2), (('quit', '--no-such'), 2))
        for words, code in cases:
            ours, theirs = self.photodesk(*words), self.direct(*words)
            self.assertEqual((ours.returncode, ours.stdout, ours.stderr), (theirs.returncode, theirs.stdout, theirs.stderr), words)
            self.assertEqual(ours.returncode, code, (words, ours.stdout, ours.stderr))
            if '--json' in words:
                body = json.loads(ours.stdout)
                self.assertIs(body['ok'], code == 0)
                self.assertEqual(body['command'].split()[0], words[0])
                if code:
                    self.assertTrue(body['error']['code'] and body['error']['message'])
            elif code:
                self.assertEqual(ours.stdout, '')  # text-mode errors go to stderr
                self.assertTrue(ours.stderr.strip())
        for words, code in ((('config', 'bogus'), 'usage'), (('config', 'status', '--no-such'), 'usage'),
                            (('config', 'sync', 'on'), 'confirmation_required'), (('shortcuts', '--no-such'), 'usage'),
                            (('login', 'on'), 'confirmation_required'), (('cancel', 'now'), 'usage'),
                            (('update', 'install', '--no-such'), 'usage'), (('shortcuts', 'set', 'pause', 'hyper+p'), 'usage'),
                            (('start', 'now'), 'usage'), (('quit', 'now'), 'usage')):
            self.assertEqual(self.call(*words, expect=2)['error']['code'], code, words)
        self.assertEqual(self.call('shortcuts', 'set', 'pause', 'p', expect=1)['error']['code'], 'rejected')
        self.assertEqual(self.call('start', expect=1)['error']['code'], 'isolation_incomplete')
        nothing = self.call('quit')
        self.assertEqual((nothing['command'], nothing['quit'], nothing['app_running']), ('quit', False, False))
        # The login item is the system's: an isolated run reads it and never changes it.
        self.assertEqual(self.call('login', 'on', '--yes', expect=1)['error']['code'], 'isolated_run')
        dry = self.call('login', 'on', '--dry-run')
        self.assertEqual((dry['dry_run'], dry['would_change'], dry['enabled']), (True, True, False))
        self.assertIn(self.call('login')['state'], ('not_registered', 'not_found'))
        # No app is running here: nothing to pause, nothing to cancel, and the stored launch setting is still told.
        idle = self.call('automation')
        self.assertEqual((idle['command'], idle['app_running'], idle['automatic_setting']), ('automation status', False, True))
        self.assertEqual(self.call('automation', 'pause', expect=1)['error']['code'], 'app_not_running')
        self.assertEqual((self.call('cancel')['cancelled'], self.call('cancel')['app_running']), (False, False))
        # A relative path is resolved where the command was typed, not where the app executable lives.
        done = self.photodesk('config', 'export', '-o', 'here.json', '--json', cwd=self.root)
        self.assertEqual((done.returncode, json.loads(done.stdout)['path']), (0, str(self.root / 'here.json')))

    def test_the_command_reads_and_writes_the_windows_own_settings(self):
        status = self.call('config', 'status')
        self.assertEqual((status['command'], status['has_settings'], status['sync_enabled'], status['problem']), ('config status', True, False, None))
        self.assertEqual(status['keys'], ['defaults.' + KEY])
        # 开关下面那句话: nothing has synced and no app is running, so it is what a window would open with.
        self.assertEqual(status['sync_status'], {'text': OFF, 'at': None, 'from': 'derived', 'live': False})
        self.assertIn('同步状态：' + OFF, self.photodesk('config', 'status').stdout)
        self.assertFalse(self.support.exists() or self.cloud.exists())  # reading writes nothing
        self.store(SHORTCUTS, {'pause': chord(35, 'P')})
        self.assertEqual(self.call('config', 'status')['keys'], ['defaults.' + KEY, 'defaults.' + SHORTCUTS])
        exported = self.root / 'out.json'
        exported.unlink(missing_ok=True)
        first = self.call('config', 'export', '-o', str(exported))
        envelope = json.loads(exported.read_text())
        self.assertEqual((envelope['product'], first['bytes']), (PRODUCT, exported.stat().st_size))
        self.assertEqual(envelope['values'], self.envelope(PREFERENCES, {'pause': chord(35, 'P')})['values'])
        self.assertEqual(self.call('config', 'export', '-o', str(exported), expect=2)['error']['code'], 'file_exists')
        self.assertEqual(json.loads(self.photodesk('config', 'export', '-o', '-').stdout)['values'], envelope['values'])

        changed = dict(PREFERENCES, thumbnailWidth=220, petNames='大白')
        incoming = self.root / 'in.json'
        incoming.write_text(json.dumps(self.envelope(changed)))
        self.assertEqual(self.call('config', 'import', str(incoming), expect=2)['error']['code'], 'confirmation_required')
        self.assertEqual(self.stored(KEY), PREFERENCES)
        foreign = self.root / 'foreign.json'
        foreign.write_text(json.dumps(dict(self.envelope(changed), product='someone.else')))
        self.assertEqual(self.call('config', 'import', str(foreign), '--yes', expect=1)['error']['code'], 'import_rejected')
        self.assertEqual((self.stored(KEY), self.stored(SHORTCUTS)), (PREFERENCES, {'pause': chord(35, 'P')}))

        imported = self.call('config', 'import', str(incoming), '--yes')
        self.assertTrue(imported['imported'] and 'sync' not in imported)
        # The file names every portable key: what it leaves out is removed, as in the window.
        self.assertEqual((self.stored(KEY), self.stored(SHORTCUTS)), (changed, None))
        # The engine reads the imported settings the way the app will.
        shown = json.loads(self.photodesk('settings', '--json').stdout)
        self.assertEqual((shown['preferences']['thumbnailWidth'], shown['preferences']['petNames']), (220.0, '大白'))
        self.assertEqual(len(list((self.support / PRODUCT / 'Backups').iterdir())), 1)
        self.assertFalse(self.cloud.exists())  # sync is off: nothing leaves the machine

        dry = self.call('config', 'sync', 'on', '--dry-run')
        self.assertTrue(dry['dry_run'] and dry['would_change'] and not self.call('config', 'status')['sync_enabled'])
        on = self.call('config', 'sync', 'on', '--yes')
        self.assertEqual((on['changed'], on['sync_enabled'], on['check_with'], self.mirrored()), (True, True, 'photodesk config status', changed))
        self.assertTrue(self.call('config', 'status')['sync_enabled'])
        # No app is running: the sentence is the one this command's own sync pass left behind, with its time.
        left = self.call('config', 'status')['sync_status']
        self.assertEqual((left['from'], left['live'], left['text']), ('record', False, on['status']))
        self.assertTrue(left['at'] and left['text'] != OFF, left)
        self.assertIs(self.call('config', 'sync', 'on', '--yes')['changed'], False)
        self.assertIs(self.call('config', 'sync', 'off', '--yes')['sync_enabled'], False)
        closed = self.call('config', 'status')['sync_status']
        self.assertEqual((closed['text'], closed['live']), (OFF, False))

    @unittest.skipIf(os.environ.get('PHOTODESK_TEST_OFFLINE') == '1', 'PHOTODESK_TEST_OFFLINE=1')
    def test_update_check_asks_the_public_release_record_and_installs_nothing(self):
        """One request, the one the window's 检查更新 makes. Either answer has the documented shape; nothing is written."""
        done = self.photodesk('update', 'check', '--json')
        body = json.loads(done.stdout)
        self.assertEqual((body['command'], body['current'], body['source']),
                         ('update check', {'version': '1.2', 'build': '7'}, {'kind': 'github', 'repository': 'zengtianli/photo-desk'}))
        if done.returncode == 0:
            self.assertIn(body['state'], ('update_available', 'up_to_date', 'ahead_of_channel'))
            self.assertEqual(body['update_available'], body['state'] == 'update_available')
            self.assertIn('how', body['upgrade'])
            if body['update_available']:
                self.assertIn('配置与更新…', body['upgrade']['how'])
        else:
            self.assertEqual((done.returncode, body['ok'], body['error']['code']), (1, False, 'check_incomplete'))
        self.assertFalse(self.support.exists() or self.cloud.exists())

    def test_shortcuts_are_the_settings_pages_bindings_and_rules(self):
        self.assertEqual((self.call('shortcuts')['bound'], self.call('shortcuts')['app_running']), (0, False))
        # pause and search share one chord; next is stored global though only three actions may be global.
        saved = {'pause': chord(35, 'P'), 'search': chord(35, 'P'), 'next': chord(45, 'N', scope='global')}
        self.store(SHORTCUTS, saved)
        before = self.domain()
        listed = self.call('shortcuts')
        rows = {row['action']: row for row in listed['shortcuts']}
        self.assertEqual((listed['command'], listed['bound'], listed['load_error'], listed['domain']), ('shortcuts', 3, None, self.suite))
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows['pause']['binding'], {'label': '⌃⌥P', 'key': 'P', 'code': 35, 'modifiers': CONTROL_OPTION, 'scope': 'application'})
        self.assertEqual((rows['pause']['allows_global'], rows['search']['allows_global']), (True, False))
        self.assertIn('聚焦搜索', rows['pause']['conflict'])
        self.assertIn('暂停 / 恢复自动整理', rows['search']['conflict'])
        self.assertIn('只能在 PhotoDesk 窗口内', rows['next']['conflict'])
        self.assertEqual((rows['refresh']['binding'], rows['refresh']['conflict'], rows['refresh']['status']), (None, None, '未设置'))
        self.assertEqual(self.domain(), before)  # reading stores nothing
        text = self.photodesk('shortcuts').stdout
        self.assertIn('pause · 暂停 / 恢复自动整理 · ⌃⌥P', text)

        # The rules are the window's: a chord in use elsewhere cannot go global, an unbound action has no scope to change.
        self.assertEqual(self.call('shortcuts', 'scope', 'pause', 'global', expect=1)['error']['code'], 'rejected')
        self.assertEqual(self.call('shortcuts', 'scope', 'refresh', 'global', expect=1)['error']['code'], 'not_bound')
        self.assertEqual(self.stored(SHORTCUTS), saved)
        cleared = self.call('shortcuts', 'clear', 'search')
        self.assertEqual((cleared['command'], cleared['changed'], cleared['cleared'], cleared['bound']), ('shortcuts clear', True, 1, 2))
        moved = self.call('shortcuts', 'scope', 'pause', 'global')
        self.assertEqual((moved['command'], moved['changed'], moved['scope']), ('shortcuts scope', True, 'global'))
        self.assertEqual(self.stored(SHORTCUTS), {'pause': chord(35, 'P', scope='global'), 'next': chord(45, 'N', scope='global')})
        rows = {row['action']: row for row in self.call('shortcuts')['shortcuts']}
        self.assertEqual((rows['pause']['binding']['scope'], rows['pause']['conflict'], rows['pause']['status']), ('global', None, '已保存 · 全局'))
        self.assertIs(self.call('shortcuts', 'scope', 'pause', 'global')['changed'], False)
        self.assertEqual(self.call('shortcuts', 'scope', 'next', 'application')['scope'], 'application')
        self.assertEqual(self.call('shortcuts', 'scope', 'next', 'global', expect=1)['error']['code'], 'rejected')
        self.assertIs(self.call('shortcuts', 'clear', 'search')['changed'], False)
        everything = self.call('shortcuts', 'clear', '--all')
        self.assertEqual((everything['cleared'], everything['bound']), (2, 0))
        self.assertNotIn(SHORTCUTS, self.domain())
        self.assertEqual(self.stored(KEY), PREFERENCES)  # the other settings are not touched
        # A stored value the app could not read is reported, not replaced.
        subprocess.run(['/usr/bin/defaults', 'write', self.suite, SHORTCUTS, '-data', b'not json'.hex()], check=True, capture_output=True, timeout=30)
        self.assertIn('无法读取', self.call('shortcuts')['load_error'])

    @unittest.skipIf(os.environ.get('PHOTODESK_TEST_OFFLINE') == '1', 'PHOTODESK_TEST_OFFLINE=1')
    def test_update_install_looks_the_release_up_and_replaces_nothing_here(self):
        """`update install` is the window's 升级到新版… / 下载新版…. The throwaway bundle (1.2 build 7) is ahead of the
        public record: nothing to install, with --yes as without. An older throwaway bundle sees the newer public
        release; PhotoDesk carries no developer identity, so the window's button there is 下载新版… and the command says
        the same (manual_install, with the package address). Nothing is downloaded or replaced in either case."""
        def tree(app):
            return sorted((str(f.relative_to(app)), f.stat().st_size, f.stat().st_mtime_ns) for f in app.rglob('*') if f.is_file())

        app = self.binary.parents[2]
        before = tree(app)
        current, source = {'version': '1.2', 'build': '7'}, {'kind': 'github', 'repository': 'zengtianli/photo-desk'}
        for words in (('--yes',), ('--dry-run',), ()):
            done = self.photodesk('update', 'install', *words, '--json')
            body = json.loads(done.stdout)
            self.assertEqual((body['command'], body['current'], body['source']), ('update install', current, source))
            if done.returncode:
                # The release record could not be read (no network, or the public API's hourly limit): said as such.
                self.assertEqual((done.returncode, body['ok'], body['error']['code']), (1, False, 'check_incomplete'))
                self.assertEqual(tree(app), before)
                self.skipTest('the public release record could not be read: ' + body['error']['message'])
            self.assertEqual((body['ok'], body['installed'], body['app_running']), (True, False, False), words)
            self.assertIn(body['state'], ('ahead_of_channel', 'up_to_date'))
            self.assertTrue(body['message'] and body['latest']['version'])
            self.assertNotIn('dry_run', body)   # there is no plan to show: nothing is newer
        self.assertIn('不需要升级', self.photodesk('update', 'install', '--yes').stdout)
        self.assertEqual(tree(app), before)

        older = self.root / 'older/PhotoDesk.app'
        shutil.rmtree(older.parent, ignore_errors=True)
        (older / 'Contents/MacOS').mkdir(parents=True)
        shutil.copy2(self.binary, older / 'Contents/MacOS/PhotoDesk')
        (older / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': BUNDLE, 'CFBundleExecutable': 'PhotoDesk', 'CFBundlePackageType': 'APPL',
            'CFBundleShortVersionString': '0.9', 'CFBundleVersion': '1', 'LSUIElement': True}))
        was = tree(older)
        there = dict(self.env, PHOTODESK_NATIVE=str(older / 'Contents/MacOS/PhotoDesk'))
        check = self.call('update', 'check', env=there)
        self.assertEqual((check['current'], check['state'], check['update_available']), ({'version': '0.9', 'build': '1'}, 'update_available', True))
        # No developer identity on this bundle (nor on the installed PhotoDesk): not replaceable from the public channel.
        self.assertEqual((check['upgrade']['in_app'], check['upgrade']['command']), (False, None))
        self.assertIn(check['upgrade']['button'], ('下载新版…', None))
        for words in (('--dry-run',), (), ('--yes',)):
            refused = self.call('update', 'install', *words, expect=1, env=there)
            self.assertEqual((refused['command'], refused['error']['code'], refused['current']), ('update install', 'manual_install', {'version': '0.9', 'build': '1'}), words)
            self.assertTrue((refused['download_url'] or refused['release_url'] or '').startswith('https://'), refused)
            self.assertEqual(refused['latest']['version'], check['latest']['version'])
            self.assertNotIn('installed', refused)
        self.assertEqual((tree(older), tree(app)), (was, before))
        self.assertEqual(sorted(path.name for path in older.parent.iterdir()), ['PhotoDesk.app'])  # no backup, no second bundle
        self.assertFalse(self.support.exists() or self.cloud.exists())

    def test_shortcuts_set_stores_what_recording_the_same_keys_would(self):
        """给动作设一个组合键, written out instead of pressed: PhotoShortcuts.set decides, and what is stored is what the
        window's recorder stores (key code, Carbon modifiers, key name). Nothing is registered with the system."""
        done = self.call('shortcuts', 'set', 'pause', 'ctrl+opt+p')
        self.assertEqual((done['command'], done['action'], done['label'], done['scope'], done['changed']),
                         ('shortcuts set', 'pause', '⌃⌥P', 'application', True))
        saved = self.stored(SHORTCUTS)
        code = saved['pause']['chord']['code']   # the P key of this Mac's keyboard layout (35 on ANSI layouts)
        self.assertTrue(0 <= code < 128, saved)
        self.assertEqual(saved, {'pause': chord(code, 'P')})
        rows = {row['action']: row for row in self.call('shortcuts')['shortcuts']}
        self.assertEqual((rows['pause']['binding']['label'], rows['pause']['status'], rows['pause']['conflict']), ('⌃⌥P', '已保存 · 仅 PhotoDesk 内', None))
        self.assertIn('pause · 暂停 / 恢复自动整理 · ⌃⌥P', self.photodesk('shortcuts').stdout)
        # The same again changes nothing. The symbols the window shows are read too; a scope moves the binding, and a
        # later set that names no scope keeps the one the binding has.
        self.assertIs(self.call('shortcuts', 'set', 'pause', 'ctrl+opt+p')['changed'], False)
        moved = self.call('shortcuts', 'set', 'pause', '⌃⌥P', 'global')
        self.assertEqual((moved['scope'], moved['changed'], self.stored(SHORTCUTS)), ('global', True, {'pause': chord(code, 'P', scope='global')}))
        kept = self.call('shortcuts', 'set', 'pause', 'control+option+shift+p')
        self.assertEqual((kept['label'], kept['scope'], kept['changed']), ('⌃⌥⇧P', 'global', True))
        # Named keys carry the key code the recorder stores for them, whatever the keyboard layout.
        self.assertEqual(self.call('shortcuts', 'set', 'preview', 'opt+space')['label'], '⌥Space')
        self.assertEqual(self.call('shortcuts', 'set', 'next', 'ctrl+right')['label'], '⌃→')
        saved = self.stored(SHORTCUTS)
        self.assertEqual((saved['preview'], saved['next']), (chord(49, 'Space', modifiers=2048), chord(124, '→', modifiers=4096)))
        self.assertEqual(self.call('shortcuts')['bound'], 3)
        # The window's rules decide, and a refusal leaves what was stored.
        for words, reason in ((('search', 'f'), '至少包含'), (('search', 'shift+f'), '至少包含'), (('search', 'cmd+c'), '标准菜单'),
                              (('search', 'ctrl+opt+shift+p'), '暂停 / 恢复自动整理'), (('search', 'ctrl+opt+f', 'global'), '只能在 PhotoDesk 窗口内')):
            refused = self.call('shortcuts', 'set', *words, expect=1)
            self.assertEqual(refused['error']['code'], 'rejected', words)
            self.assertIn(reason, refused['error']['message'])
            self.assertIn('原绑定保留', refused['error']['message'])
        for words in (('pause',), ('nosuch', 'ctrl+opt+p'), ('pause', 'hyper+p'), ('pause', 'ctrl+opt+'), ('pause', 'ctrl+opt+pp'),
                      ('pause', 'ctrl+opt+p', 'everywhere'), ('pause', 'ctrl+opt+p', 'global', 'extra')):
            self.assertEqual(self.call('shortcuts', 'set', *words, expect=2)['error']['code'], 'usage', words)
        self.assertEqual(self.stored(SHORTCUTS), saved)
        self.assertEqual(self.stored(KEY), PREFERENCES)  # the other settings are not touched
        # scope on an action without a binding now says how to give it one.
        self.assertIn('photodesk shortcuts set refresh', self.call('shortcuts', 'scope', 'refresh', 'global', expect=1)['error']['message'])

    def test_the_permissions_probe_reads_the_grants_with_preflights_only(self):
        """What `photodesk doctor` asks the app executable for: PhotoDesk's own 照片 grant and the caller's 自动化 grant
        toward “照片”, as one JSON line. Checked here: the shape, that a reading told as PhotoDesk's own really was read
        by this executable as its own responsible program, that it returns without waiting on anything, and that the
        source keeps to the two calls that cannot ask (the status read, and the Apple-event preflight told not to)."""
        began = time.monotonic()
        done = self.direct('--permissions-probe')
        took = time.monotonic() - began
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        body = json.loads(done.stdout)
        self.assertEqual(set(body), {'photos', 'automation'})
        photos, caller = body['photos'], body['automation']['caller']
        self.assertEqual(set(photos), {'status', 'granted', 'own_identity', 'from'})
        self.assertIn(photos['status'], ('authorized', 'limited', 'denied', 'restricted', 'not_determined', 'unknown'))
        self.assertIn(photos['from'], ('probe', 'app', None))
        if photos['from'] == 'probe':
            self.assertIs(photos['own_identity'], True, photos)
            self.assertEqual(photos['granted'], photos['status'] in ('authorized', 'limited'))
        self.assertIn(caller['state'], ('allowed', 'denied', 'not_asked', 'target_not_running', 'unknown', 'no_answer'))
        self.assertLess(took, 60)
        access = (ROOT / 'Sources/AgentCommands.swift').read_text().split('enum PhotoAccess {')[1].split('\nenum PhotoChord {')[0]
        self.assertNotIn('requestAuthorization', access)
        self.assertIn('PHPhotoLibrary.authorizationStatus(for: .readWrite)', access)
        self.assertIn('AEDeterminePermissionToAutomateTarget(&target, typeWildCard, typeWildCard, false)', access)
        # doctor tells that reading row by row, and a reading that is missing or not PhotoDesk's own is never a pass.
        rows = dict((name, (ok, detail)) for name, ok, detail in desk_cli.permission_checks(body))
        if photos['from'] == 'probe' and photos['status'] in desk_cli.PHOTOS_ACCESS:
            self.assertIs(rows['photos_access'][0], desk_cli.PHOTOS_ACCESS[photos['status']][0])
        else:
            self.assertIsNone(rows['photos_access'][0])
        self.assertIn(rows['photos_automation'][0], (True, False, None))

    def test_start_launches_hidden_and_quit_ends_it(self):
        """`photodesk start` really starts this throwaway bundle through the system (a test bundle identifier, no Dock
        icon, the marked synthetic library, the stand-in engine): it comes up hidden and not activated, none of its
        windows reaches the screen, the front app is not it, and the commands that need a running app find it. `quit`
        ends it the way ⌘Q does and waits until the process has gone."""
        live = dict(self.env, PHOTODESK_BACKGROUND='1', PHOTODESK_LIBRARY=str(self.demo))
        self.assertIs(self.call('quit', env=live)['quit'], False)   # nothing is running yet
        started = self.call('start', env=live)
        pid = started['pid']
        self.addCleanup(lambda: alive(pid) and os.kill(pid, signal.SIGKILL))
        self.assertEqual((started['command'], started['started'], started['app_running'], started['hidden'], started['active']),
                         ('start', True, True, True, False), started)
        self.assertEqual(Path(started['app_path']).resolve(), self.binary.parents[2])
        self.assertEqual(started['check_with'], 'photodesk automation status')
        self.assertEqual(windows_on_screen(pid), [])
        self.assertNotEqual(front_pid(), pid)
        status = self.call('automation', env=live)
        self.assertEqual((status['app_running'], status['pid'], status['hidden'], status['active']), (True, pid, True, False))
        # Already running: not started again, its window is not touched.
        again = self.call('start', env=live)
        self.assertEqual((again['started'], again['app_running'], again['pid'], again['hidden']), (False, True, pid, True))
        self.assertIn('已在运行', self.photodesk('start', env=live).stdout)
        # While it runs it owns the bindings.
        self.assertEqual(self.call('shortcuts', 'set', 'pause', 'ctrl+opt+p', expect=1, env=live)['error']['code'], 'app_running')
        self.assertEqual(windows_on_screen(pid), [])
        self.assertNotEqual(front_pid(), pid)
        done = self.call('quit', env=live)
        self.assertEqual((done['command'], done['quit'], done['app_running'], done['pid']), ('quit', True, False, pid), done)
        self.assertNotIn('quit_accepted', done)   # the app's word to the command, not part of the result
        self.assertFalse(alive(pid))
        self.assertIs(self.call('automation', env=live)['app_running'], False)
        self.assertIs(self.call('quit', env=live)['quit'], False)
        # And with the app gone the binding can be set.
        self.assertIs(self.call('shortcuts', 'set', 'pause', 'ctrl+opt+p', env=live)['changed'], True)

    def test_a_running_app_follows_the_command_and_never_writes_the_old_value_back(self):
        self.follow()

    def test_a_running_app_pauses_resumes_and_cancels_on_command(self):
        process, live, seen, reaches, state = self.start_app()
        first = self.call('automation', env=live)
        self.assertEqual((first['app_running'], first['automatic_enabled'], first['busy'], first['pid']), (True, False, False, process.pid))
        # 继续自动整理: the app starts its background pass (the stand-in engine never finishes it).
        resumed = self.call('automation', 'resume', env=live)
        self.assertEqual((resumed['command'], resumed['changed'], resumed['automatic_enabled'], resumed['check_with']),
                         ('automation resume', True, True, 'photodesk automation status'))
        self.assertTrue(reaches(lambda s: s['automatic_enabled'] is True and s['organizing'] is True), 'the app is organizing')
        self.assertTrue(self.call('automation', env=live)['organizing'])
        # 暂停自动整理.
        paused = self.call('automation', 'pause', env=live)
        self.assertEqual((paused['changed'], paused['automatic_enabled'], paused['organizing']), (True, False, False))
        self.assertIn('已暂停', paused['organization_status'])
        self.assertTrue(reaches(lambda s: s['automatic_enabled'] is False and s['organizing'] is False), 'the app paused')
        self.assertIs(self.call('automation', 'pause', env=live)['changed'], False)
        # Back to back: the later command is the state the app ends in and stays in.
        self.call('automation', 'resume', env=live)
        self.assertIs(self.call('automation', 'pause', env=live)['automatic_enabled'], False)
        # The state file is the app's report every 50 ms: wait for the one written after the reply, then watch it.
        self.assertTrue(reaches(lambda s: s['automatic_enabled'] is False and '已暂停' in s['organization_status']), 'settles paused after resume, pause')
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            self.assertIs(seen()['automatic_enabled'], False, 'resume, pause back to back stays paused')
            self.assertIs(self.call('automation', env=live)['automatic_enabled'], False)  # a fresh process asks the app
            time.sleep(0.05)
        # Nothing in progress: nothing to cancel, and that is not a failure.
        nothing = self.call('cancel', env=live)
        self.assertEqual((nothing['cancelled'], nothing['app_running'], nothing['busy']), (False, True, False))
        # The window's ⌘R starts a task that stays in progress; the command cancels it and waits until it has ended.
        Path(str(state) + '.refresh').write_text('')
        self.assertTrue(reaches(lambda s: s['busy'] is True), 'a task is in progress')
        self.assertTrue(self.call('automation', env=live)['busy'])
        cancelled = self.call('cancel', env=live)
        self.assertEqual((cancelled['command'], cancelled['cancelled'], cancelled['busy'], cancelled['applying']), ('cancel', True, False, False))
        self.assertIn('已取消', cancelled['task_status'])
        self.assertTrue(reaches(lambda s: s['busy'] is False and '已取消' in s['task_status']), 'the task ended')
        # With 打开 PhotoDesk 后自动整理 switched off in the settings, resume says so instead of pretending.
        self.call('automation', 'pause', env=live)
        off = self.root / 'automatic-off.json'
        off.write_text(json.dumps(self.envelope(dict(PREFERENCES, automatic=False))))
        self.call('config', 'import', str(off), '--yes', env=live)
        self.assertTrue(reaches(lambda s: s['automatic'] is False), 'the app re-read the setting')
        refused = self.call('automation', 'resume', expect=1, env=live)
        self.assertEqual((refused['error']['code'], refused['automatic_enabled'], refused['automatic_setting']), ('automatic_off', False, False))
        last = seen()
        self.assertEqual((last['policy_prohibited'], last['windows_on_screen']), (True, 0))
        # An app that is already running is found, not started again; `quit` ends it by its own ⌘Q path.
        found = self.call('start', env=live)
        self.assertEqual((found['started'], found['app_running'], found['pid']), (False, True, process.pid))
        ended = self.call('quit', env=live)
        self.assertEqual((ended['quit'], ended['app_running'], ended['pid']), (True, False, process.pid))
        self.assertEqual(process.wait(timeout=15), 0)
        self.followers.remove(process)
        gone = self.call('automation', env=live)
        self.assertEqual((gone['app_running'], gone['automatic_setting']), (False, False))
        self.assertEqual(self.call('automation', 'resume', expect=1, env=live)['error']['code'], 'app_not_running')

    def test_refusals(self):
        # A run that does not say which settings it means is refused before anything is read.
        partial = {k: v for k, v in self.env.items() if k != 'PHOTODESK_PREFERENCES_SUITE'}
        self.assertEqual(self.call('config', 'status', expect=1, env=partial)['error']['code'], 'isolation_incomplete')
        real = dict(self.env, PHOTODESK_PREFERENCES_SUITE=PRODUCT)
        self.assertEqual(self.call('config', 'status', expect=1, env=real)['error']['code'], 'isolation_incomplete')
        mixed = {k: v for k, v in self.env.items() if not k.startswith('APP_LIFECYCLE_')}  # a test domain with the real support folder
        self.assertEqual(self.call('config', 'sync', 'on', '--yes', expect=1, env=mixed)['error']['code'], 'isolation_incomplete')
        self.assertEqual(self.call('update', 'check', expect=1, env=mixed)['error']['code'], 'isolation_incomplete')
        self.assertEqual(self.stored(KEY), PREFERENCES)
        # The probe exists for this test only: outside an isolated run the executable exits at once, before any NSApplication.
        outside = {k: v for k, v in self.env.items() if not k.startswith(('APP_LIFECYCLE_', 'PHOTODESK_'))}
        probe = subprocess.run([str(self.binary), '--lifecycle-follow-probe', str(self.root / 'never.json')], env=outside,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual((probe.returncode, (self.root / 'never.json').exists()), (64, False))
        # From source with no app executable to forward to, the command says so in the same shape.
        alone = {k: v for k, v in self.env.items() if k != 'PHOTODESK_NATIVE'}
        for verb in desk_cli.APP_VERBS:
            self.assertEqual(self.call(verb, expect=1, env=alone)['error']['code'], 'app_missing', verb)
        text = self.photodesk('update', 'check', env=alone)
        self.assertEqual((text.returncode, text.stdout), (1, ''))
        self.assertIn('App 可执行文件', text.stderr)

    @unittest.skipUnless(HEADQUARTERS.is_file(), 'shared source not on this machine')
    def test_the_command_layer_is_the_shared_source_byte_for_byte(self):
        self.assertTrue((ROOT / 'Sources/Shared/AppLifecycleCLI.swift').read_bytes() == HEADQUARTERS.read_bytes(),
                        f'Sources/Shared/AppLifecycleCLI.swift differs from the shared source; copy {HEADQUARTERS} over it and build again')


@unittest.skipUnless(ASSEMBLED, 'set PHOTODESK_APP to an assembled PhotoDesk.app (build.sh does after assembly)')
class AssembledBundleTests(Chain):
    """The shipped chain: the frozen engine inside the bundle forwards to the bundle's own app executable, and that
    executable, started as the app, follows the commands and runs the real bundled engine on the product's own
    synthetic acceptance pictures. Throwaway preferences and directories; the bundle's real settings are not opened."""

    @classmethod
    def setUpClass(cls):
        cls.isolate('photodesk-lifecycle-app-')
        cls.app = Path(ASSEMBLED).resolve()
        cls.binary = cls.app / 'Contents/MacOS/PhotoDesk'
        cls.engine = [str(cls.app / 'Contents/Resources/bin/photodesk')]
        cls.env['PHOTODESK_NATIVE'] = str(cls.root / 'ignored-by-the-frozen-engine')
        spec = importlib.util.spec_from_file_location('prepare_lifecycle_demo', ROOT / 'scripts/prepare_demo.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.OUT = cls.demo
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
        (cls.demo / 'state').mkdir(exist_ok=True)

    def test_the_frozen_engine_forwards_to_its_own_bundle(self):
        info = plistlib.loads((self.app / 'Contents/Info.plist').read_bytes())
        for words, code in ((('config', 'status', '--json'), 0), (('shortcuts', '--json'), 0), (('login', 'status', '--json'), 0),
                            (('automation', 'status', '--json'), 0), (('cancel', '--json'), 0),
                            (('config', 'status', '--no-such', '--json'), 2), (('shortcuts', 'bogus', '--json'), 2),
                            (('login', 'on', '--json', '--dry-run'), 0), (('config', '--help'), 0), (('cancel', '--help'), 0),
                            (('update', 'install', '--no-such', '--json'), 2), (('shortcuts', 'set', 'pause', '--json'), 2),
                            (('start', 'now', '--json'), 2), (('start', '--json'), 1), (('quit', 'now', '--json'), 2),
                            (('start', '--help'), 0), (('quit', '--help'), 0), (('update', '--help'), 0)):
            ours, theirs = self.photodesk(*words), self.direct(*words)
            self.assertEqual((ours.returncode, ours.stdout, ours.stderr), (theirs.returncode, theirs.stdout, theirs.stderr), words)
            self.assertEqual(ours.returncode, code, (words, ours.stdout, ours.stderr))
        status = self.call('config', 'status')
        self.assertEqual((status['sync_enabled'], status['keys']), (False, ['defaults.' + KEY]))
        self.assertEqual(status['sync_status'], {'text': OFF, 'at': None, 'from': 'derived', 'live': False})
        self.assertEqual(self.call('config', 'status', '--no-such', expect=2)['error']['code'], 'usage')
        self.assertEqual(self.call('update', 'install', '--no-such', expect=2)['error']['code'], 'usage')
        # `start` never launches from a run that names isolation variables without being the complete isolated one,
        # and `shortcuts set` writes the test domain through the frozen engine.
        self.assertEqual(self.call('start', expect=1)['error']['code'], 'isolation_incomplete')
        self.assertEqual(self.call('shortcuts', 'set', 'pause', 'ctrl+opt+p')['label'], '⌃⌥P')
        self.assertEqual(self.call('shortcuts')['bound'], 1)
        # doctor asks the bundle's own executable for the system's grants; whatever it reads, the two rows are there.
        doctor = json.loads(self.photodesk('doctor', '--json').stdout)
        self.assertEqual(set(doctor['permissions']), {'photos_access', 'photos_automation'})
        self.assertTrue({'photos_access', 'photos_automation'} <= {check['name'] for check in doctor['checks']})
        self.assertEqual(self.call('login', 'on', '--yes', expect=1)['error']['code'], 'isolated_run')
        self.assertEqual(self.call('shortcuts')['domain'], self.suite)
        top = self.photodesk('--help').stdout
        for line in photocli.LIFECYCLE_READS + photocli.LIFECYCLE_WRITES:
            self.assertIn('\n  ' + line + '\n', top)
        self.assertIn(info['CFBundleShortVersionString'], self.photodesk('--version').stdout)
        self.assertFalse(self.support.exists() or self.cloud.exists())

    def test_the_bundled_app_follows_the_command_and_never_writes_the_old_value_back(self):
        self.follow()

    def test_the_bundled_app_pauses_and_resumes_the_real_engine_on_the_synthetic_library(self):
        process, live, seen, reaches, _ = self.start_app()
        self.assertEqual((self.call('automation', env=live)['automatic_enabled'], seen()['windows_on_screen']), (False, 0))
        resumed = self.call('automation', 'resume', env=live)
        self.assertTrue(resumed['changed'] and resumed['automatic_enabled'], resumed)
        # The bundled engine really ran: the app reports the ten synthetic pictures gathered.
        self.assertTrue(reaches(lambda s: s['automatic_enabled'] is True and '内容识别已关闭' in s['organization_status'], 90), seen())
        self.assertTrue((self.demo / 'state/journey').is_dir())
        paused = self.call('automation', 'pause', env=live)
        self.assertEqual((paused['changed'], paused['automatic_enabled']), (True, False))
        self.assertTrue(reaches(lambda s: s['automatic_enabled'] is False and '已暂停' in s['organization_status']), 'the app paused')
        self.assertIs(self.call('cancel', env=live)['cancelled'], False)
        last = seen()
        self.assertEqual((last['policy_prohibited'], last['windows_on_screen']), (True, 0))
        self.stop_app(process)
        self.assertIs(self.call('automation', env=live)['app_running'], False)


if __name__ == '__main__':
    unittest.main()

"""photodesk agent commands: the app's functions through the same engine, on synthetic data only.

Nothing here opens the real Photos library or the real app settings: subprocess runs use the
synthetic demo library, an isolated data root and a never-written preferences domain; in-process
runs replace the preferences store with a dictionary.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import bridge  # noqa: E402
import desk_cli  # noqa: E402
import preferences  # noqa: E402
from click.testing import CliRunner  # noqa: E402
from photocli.cli import cli  # noqa: E402

SWIFT = (ROOT / 'Sources/ProductControls.swift').read_text()


class FakeStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, domain):
        return self.values.get((domain, key))

    def set(self, key, value, domain):
        if value is None:
            self.values.pop((domain, key), None)
        else:
            self.values[(domain, key)] = value


class PreferencesMatchSwift(unittest.TestCase):
    """The Python copy of PhotoPreferences must follow the Swift source."""

    def test_defaults_clamps_and_choices_follow_the_settings_window(self):
        self.assertIn(f'storageKey = "{preferences.STORAGE_KEY}"', SWIFT)
        swift_defaults = dict(re.findall(r'^    var (\w+) = (.+)$', SWIFT.split('static func load')[0], re.M))
        self.assertEqual(set(swift_defaults), set(preferences.DEFAULTS))
        for key, value in preferences.DEFAULTS.items():
            self.assertEqual(json.loads(swift_defaults[key]), value, key)
        clamps = {k: (int(a), int(b)) for k, a, b in re.findall(r'value\.(\w+) = max\((\d+), min\((\d+), value\.\w+\)\)', SWIFT)}
        self.assertEqual(clamps, preferences.CLAMPS)
        for key in ('refreshSeconds', 'batchSize'):
            block = re.search(rf'selection: \$model\.preferences\.{key}\) \{{(.*?)\n\s*\}}', SWIFT, re.S).group(1)
            self.assertEqual(tuple(map(int, re.findall(r'\.tag\((\d+)\)', block))), preferences.CHOICES[key])
        appearance = re.search(r'selection: \$model\.preferences\.appearance\) \{(.*?)\n\s*\}', SWIFT, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'\.tag\("(\w+)"\)', appearance)), preferences.CHOICES['appearance'])
        tracks = re.search(r'selection: \$model\.preferences\.initialTrack\) \{\s*ForEach\(\[(.*?)\]', SWIFT, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', tracks)), preferences.CHOICES['initialTrack'])
        for key, (low, high, step) in preferences.STEPS.items():
            control = re.search(rf'\$model\.preferences\.{key}, in: (\d+)\.\.\.(\d+)(?:, step: (\d+))?', SWIFT)
            self.assertEqual((int(control.group(1)), int(control.group(2)), int(control.group(3) or 1)), (low, high, step), key)
        options = re.search(r'var engineOptions.*?\[(.*?)\]\n', SWIFT, re.S).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)":', options)), set(preferences.engine_options(preferences.DEFAULTS)))


class PreferencesStore(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        patcher = patch.dict(os.environ, {'PHOTODESK_PREFERENCES_SUITE': 'PhotoDesk.Test.Unit'})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('PHOTODESK_DEMO_ROOT', 'PHOTODESK_LIBRARY'):
            os.environ.pop(name, None)

    def saved(self):
        return json.loads(self.store.values[('PhotoDesk.Test.Unit', preferences.STORAGE_KEY)])

    def test_fresh_partial_and_clamped_values_load_like_swift(self):
        self.assertEqual(preferences.load(self.store), (preferences.DEFAULTS, False))
        self.store.set(preferences.STORAGE_KEY, json.dumps({'automatic': False}).encode(), 'PhotoDesk.Test.Unit')
        self.assertEqual(preferences.load(self.store), (preferences.DEFAULTS, False))
        self.store.set(preferences.STORAGE_KEY, json.dumps(dict(preferences.DEFAULTS, batchSize=99, eventHours=0)).encode(),
                       'PhotoDesk.Test.Unit')
        values, saved = preferences.load(self.store)
        self.assertTrue(saved)
        self.assertEqual((values['batchSize'], values['eventHours']), (24, 1))

    def test_set_writes_every_field_and_refuses_while_the_app_runs(self):
        with patch.object(preferences, 'app_running', return_value=False):
            preferences.save('eventHours', preferences.parse('eventHours', '4'), self.store)
            preferences.save('petNames', preferences.parse('petNames', ' Example，Other '), self.store)
        self.assertEqual(set(self.saved()), set(preferences.DEFAULTS))
        self.assertEqual(self.saved()['eventHours'], 4)
        self.assertEqual(preferences.engine_options(preferences.load(self.store)[0])['pet_names'], ['Example', 'Other'])
        with patch.object(preferences, 'app_running', return_value=True):
            with self.assertRaisesRegex(ValueError, '正在运行'):
                preferences.save('eventHours', 5, self.store)
        self.assertEqual(self.saved()['eventHours'], 4)

    def test_values_are_limited_to_what_the_window_offers(self):
        for key, text in (('batchSize', '7'), ('refreshSeconds', '120'), ('meetingMinutes', '100'),
                          ('thumbnailWidth', '145'), ('eventHours', '13'), ('appearance', 'blue'),
                          ('automatic', 'maybe'), ('nonsense', '1'), ('library', '/nonexistent/X.photoslibrary')):
            with self.assertRaises(ValueError, msg=key):
                preferences.parse(key, text)
        self.assertEqual(preferences.parse('meetingMinutes', '45'), 45)
        self.assertEqual(preferences.parse('thumbnailWidth', '230'), 230.0)
        self.assertIs(preferences.parse('automatic', 'off'), False)
        self.assertEqual(preferences.parse('library', ''), '')

    def test_library_follows_env_then_saved_choice_then_system(self):
        self.assertEqual(preferences.library(self.store), ('', 'system'))
        with tempfile.TemporaryDirectory() as scratch:
            chosen = Path(scratch) / 'Other.photoslibrary'
            chosen.mkdir()
            with patch.object(preferences, 'app_running', return_value=False):
                preferences.save('library', preferences.parse('library', str(chosen)), self.store)
            self.assertEqual(preferences.library(self.store), (str(chosen.resolve()), 'saved'))
            with patch.dict(os.environ, {'PHOTODESK_LIBRARY': '/env/Choice.photoslibrary'}):
                self.assertEqual(preferences.library(self.store)[1], 'env')
            with patch.object(preferences, 'app_running', return_value=False):
                preferences.save('library', '', self.store)
            self.assertEqual(preferences.library(self.store), ('', 'system'))


class Selection(unittest.TestCase):
    plan = {'rows': [
        {'id': '0', 'group': 'A'}, {'id': '1', 'group': 'A', 'read_only': True},
        {'id': '2', 'group': 'B', 'recommended': True}, {'id': '3', 'group': 'B'}]}

    def test_bulk_selection_skips_read_only_rows_like_the_window(self):
        self.assertEqual(desk_cli.choose(self.plan, groups=['A']), ['0'])
        self.assertEqual(desk_cli.choose(self.plan, everything=True), ['0', '2', '3'])
        self.assertEqual(desk_cli.choose(self.plan, recommended=True), ['2'])
        self.assertEqual(desk_cli.choose(self.plan, ids=['3,0', '3']), ['3', '0'])

    def test_unknown_or_empty_selection_is_an_error(self):
        for kwargs in ({}, {'ids': ['9']}, {'groups': ['C']}):
            with self.assertRaises(ValueError):
                desk_cli.choose(self.plan, **kwargs)


class EnginePlans(unittest.TestCase):
    def photo(self, uuid, title=''):
        return SimpleNamespace(uuid=uuid, cloud_guid='guid-' + uuid, original_filename=uuid + '.png', title=title,
                               date=dt.datetime(2026, 9, 1, 10), persons=[], labels=[], place=None, path='',
                               path_derivatives=[], ismovie=False, shared=False, shared_library=False,
                               syndicated=False, favorite=False, keywords=[], album_info=[], albums=[])

    def test_title_plan_only_fills_empty_titles_and_browsing_saves_nothing(self):
        photos = [self.photo('a'), self.photo('b', title='用户写的标题')]
        db = SimpleNamespace(photos=lambda: photos, library_path='/fake.photoslibrary')
        with tempfile.TemporaryDirectory() as scratch, patch.object(bridge, 'ROOT', Path(scratch)), \
             patch.object(bridge, 'load_db', return_value=db):
            titles = bridge.build_plan({'kind': 'title'}, bridge.config({}))
            self.assertEqual([r['local_uuid'] for r in titles['rows']], ['a'])
            before = sorted(Path(scratch).rglob('*'))
            browse = bridge.build_plan({'kind': 'library', 'persist': False}, bridge.config({}))
            self.assertEqual(len(browse['rows']), 2)
            self.assertEqual(sorted(Path(scratch).rglob('*')), before)

    def test_triage_never_targets_a_delete_album(self):
        buckets = []
        photo = self.photo('a')
        photo.uti = 'public.png'
        db = SimpleNamespace(photos=lambda: [photo], library_path='/fake.photoslibrary')
        for bucket in ('junk', 'receipt', 'unsure'):
            with tempfile.TemporaryDirectory() as scratch, patch.object(bridge, 'ROOT', Path(scratch)), \
                 patch.object(bridge, 'load_db', return_value=db), \
                 patch.object(bridge.lib, 'load_db', return_value=db), \
                 patch.object(bridge.triage, '_classify', return_value=(bucket, 'fixture')):
                buckets += [r['target'] for r in bridge.build_plan({'kind': 'triage'}, bridge.config({}))['rows']]
        self.assertEqual(len(buckets), 3)
        self.assertFalse(any('删除' in t or 'DELETE' in t for t in buckets), buckets)


class CliOnlyTools(unittest.TestCase):
    """reconcile and dedup-export on a fake library: the same numbers in text and --json."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='PhotoDesk-cli-only-')
        self.addCleanup(self.scratch.cleanup)
        now = dt.datetime.now().astimezone()
        trashed = [SimpleNamespace(date_trashed=now - dt.timedelta(days=2)),
                   SimpleNamespace(date_trashed=now - dt.timedelta(days=60))]
        keep = SimpleNamespace(cloud_guid='guid-keep', original_filename='keep.png')
        fav = SimpleNamespace(cloud_guid='guid-fav', original_filename='fav.png')
        albums = [SimpleNamespace(title='_TO_DELETE_BATCH_1', photos=[keep, fav]),
                  SimpleNamespace(title='Trip', photos=[keep])]
        self.db = SimpleNamespace(library_path='/fake/Test.photoslibrary', album_info=albums,
                                  photos=lambda intrash=False: trashed if intrash else [keep, fav, keep])
        out = Path(self.scratch.name)
        self.cfg = SimpleNamespace(library=None, section=lambda name: {}, path=lambda key: out / key)
        from photocli import dedup
        for target, value in (('load_db', lambda library: self.db), ('load_config', lambda path: self.cfg),
                              ('is_protected', lambda p, cfg: '收藏' if p is fav else None)):
            patcher = patch.object(dedup, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(desk_cli, 'API', bridge)
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, *args):
        return CliRunner().invoke(cli, list(args), obj={}, catch_exceptions=False)

    def test_reconcile_json_matches_the_text(self):
        data = json.loads(self.invoke('reconcile', '--json').stdout)
        self.assertEqual((data['ok'], data['total'], data['in_trash'], data['trashed_last_30_days']), (True, 3, 2, 1))
        self.assertEqual(data['pending_albums'], [{'album': '_TO_DELETE_BATCH_1', 'photos': 2}])
        text = self.invoke('reconcile').stdout
        self.assertIn('本地图库总数: 3', text)
        self.assertIn('_TO_DELETE_BATCH_1: 2 张', text)

    def test_dedup_export_json_and_missing_album(self):
        result = self.invoke('dedup-export', '--album', '_TO_DELETE_BATCH_1', '--json')
        data = json.loads(result.stdout)
        self.assertEqual((data['exported'], data['protected'], data['protected_reasons']), (1, 1, {'收藏': 1}))
        self.assertEqual(Path(data['path']).read_text(), 'guid-keep\n')
        missing = self.invoke('dedup-export', '--album', 'nope', '--json')
        self.assertEqual((missing.exit_code, json.loads(missing.stdout)['ok']), (1, False))


class TimelineCacheLibrary(unittest.TestCase):
    """Following the system library, the timeline shown is the cache of the library Photos opened last."""

    def setUp(self):
        import journey
        self.scratch = tempfile.TemporaryDirectory(prefix='PhotoDesk-timeline-cache-')
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.libraries = {}
        for name in ('A', 'B'):
            library = root / f'{name}.photoslibrary'
            library.mkdir()
            self.libraries[name] = str(library)
        self.api = SimpleNamespace(ROOT=root / 'state')
        self.journey = journey
        for patcher in (patch.object(desk_cli, 'API', self.api), patch.dict(os.environ, {}, clear=False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop('PHOTODESK_DEMO_ROOT', None)

    def cache(self, name, generated):
        # journey.run keys the folder by the path osxphotos reports, which may differ from resolve().
        folder = self.journey.cache_folder(self.api, self.libraries[name])
        folder.mkdir(parents=True)
        (folder / 'latest.json').write_text(json.dumps({'library': self.libraries[name], 'generated': generated}))

    def last(self, name):
        return patch.object(preferences, 'photos_last_library', return_value=self.libraries.get(name))

    def test_single_cache_from_another_library_is_refused(self):
        self.cache('B', '2026-09-20')
        with self.last('A'), self.assertRaisesRegex(ValueError, '其他图库.*photodesk refresh'):
            desk_cli.timeline_cache('')

    def test_picks_the_last_opened_library_among_several(self):
        self.cache('A', '2026-09-01')
        self.cache('B', '2026-09-20')
        with self.last('A'):
            self.assertEqual(desk_cli.timeline_cache('')[0]['library'], self.libraries['A'])
        with self.last('B'):
            self.assertEqual(desk_cli.timeline_cache('')[0]['library'], self.libraries['B'])

    def test_explicit_library_and_unknown_last_library(self):
        self.cache('A', '2026-09-01')
        self.cache('B', '2026-09-20')
        with self.last('A'):
            self.assertEqual(desk_cli.timeline_cache(self.libraries['B'])[0]['library'], self.libraries['B'])
        with self.last(None):  # Photos has no last-opened library on record: the newest cache
            self.assertEqual(desk_cli.timeline_cache('')[0]['library'], self.libraries['B'])
        with self.assertRaisesRegex(ValueError, '还没有这个图库'):
            desk_cli.timeline_cache(str(Path(self.scratch.name) / 'C.photoslibrary'))

    def test_last_library_reader_agrees_with_osxphotos(self):
        # A synthetic Photos preferences file in a temporary home: both readers resolve its bookmark.
        import CoreFoundation as CF
        import plistlib
        from osxphotos import utils
        home = Path(self.scratch.name) / 'home'
        plist = home / 'Library/Containers/com.apple.Photos/Data/Library/Preferences/com.apple.Photos.plist'
        plist.parent.mkdir(parents=True)
        with patch.object(preferences, 'PHOTOS_PLIST', plist), patch('pathlib.Path.home', return_value=home):
            self.assertIsNone(preferences.photos_last_library())
            self.assertIsNone(utils.get_last_library_path())
            url = CF.CFURLCreateWithFileSystemPath(None, self.libraries['A'], CF.kCFURLPOSIXPathStyle, True)
            bookmark, error = CF.CFURLCreateBookmarkData(None, url, 0, None, None, None)
            self.assertIsNone(error)
            plist.write_bytes(plistlib.dumps({'IPXDefaultLibraryURLBookmark': bytes(bookmark)}, fmt=plistlib.FMT_BINARY))
            ours = preferences.photos_last_library()
            self.assertEqual(ours, utils.get_last_library_path())
            self.assertEqual(Path(ours).resolve(), Path(self.libraries['A']).resolve())


class AgentCommands(unittest.TestCase):
    """End to end through bridge.py on the synthetic demo library, as an agent would call it."""

    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix='PhotoDesk-desk-cli-')
        root = Path(cls.scratch.name)
        rows = []
        for i, name in enumerate(('a', 'b', 'c')):
            (root / f'{name}.png').write_bytes(b'same synthetic bytes' if name != 'c' else b'other synthetic bytes')
            rows.append(dict(uuid=f'00000000-0000-0000-0000-00000000000{i}', file=f'{name}.png',
                             date='2026-09-09T10:00:00+08:00', albums=['猫咪'], title=''))
        (root / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1', 'photos': rows}))
        cls.root = root
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith(('PHOTOCLI_', 'PHOTODESK_'))}
        cls.env.update(PHOTODESK_DEMO_ROOT=str(root), PHOTODESK_DATA_ROOT=str(root / 'state'),
                       PHOTODESK_PREFERENCES_SUITE=f'PhotoDesk.Test.DeskCLI.{os.getpid()}')
        # The app's own commands (desk_cli.APP_VERBS) are answered by the compiled app executable; scripts/test.sh
        # builds it and names it here. tests/test_lifecycle_cli.py covers them.
        cls.native = os.environ.get('PHOTODESK_NATIVE')
        if cls.native:
            cls.env['PHOTODESK_NATIVE'] = cls.native

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'backend/bridge.py'), *args], text=True,
                                capture_output=True, env=self.env, timeout=60)
        return result

    def json_cli(self, *args, ok=True):
        result = self.run_cli(*args, '--json')
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['ok'], ok, data)
        return data

    def test_01_every_command_has_help(self):
        commands = set(re.findall(r'^  ([a-z][a-z-]*)\s', self.run_cli('--help').stdout, re.M))
        self.assertLessEqual(set(desk_cli.APP_VERBS), commands)
        for command in sorted(commands):
            if command in desk_cli.APP_VERBS and not self.native:
                continue  # from source they need the compiled app executable to answer, --help included
            self.assertEqual(self.run_cli(command, '--help').returncode, 0, command)
        self.assertEqual(self.run_cli('settings', 'set', '--help').returncode, 0)

    def test_02_timeline_needs_a_refresh_first(self):
        self.assertIn('photodesk refresh', self.json_cli('timeline', ok=False)['error'])

    def test_03_refresh_then_read_the_same_state(self):
        state = self.root / 'state'
        built = self.json_cli('refresh')
        self.assertEqual((built['total'], built['pending'], built['unchanged']), (3, 3, False))
        latest = next(state.glob('journey/*/latest.json'))
        stamp = latest.stat().st_mtime_ns
        again = self.json_cli('refresh')
        self.assertTrue(again['unchanged'])
        self.assertEqual(latest.stat().st_mtime_ns, stamp)
        view = self.json_cli('timeline')
        self.assertEqual((view['total'], view['event_count'], view['plan_id']), (3, built['event_count'], built['plan_id']))
        event = view['events'][0]
        members = self.json_cli('timeline', '--event', event['id'])
        self.assertEqual(members['row_count'], event['count'])
        self.assertEqual(self.json_cli('timeline', '--track', '猫时间线')['matched'], view['matched'])
        duplicates = self.json_cli('duplicates')
        self.assertEqual((duplicates['row_count'], len(duplicates['recommended'])), (2, 1))
        self.assertEqual(duplicates['plan_id'], built['duplicates_plan_id'])

    def test_04_browsing_saves_nothing_but_plan_library_does(self):
        state = self.root / 'state'
        before = sorted(p.name for p in (state / 'plans').glob('*')) if (state / 'plans').exists() else []
        photos = self.json_cli('photos', '--limit', '2')
        self.assertEqual((photos['total'], len(photos['rows']), photos['plan_id']), (3, 2, None))
        after = sorted(p.name for p in (state / 'plans').glob('*')) if (state / 'plans').exists() else []
        self.assertEqual(before, after)
        plan = self.json_cli('plan', 'library')
        self.assertEqual(self.json_cli('plans')['entries'][0]['id'], plan['id'])
        shown = self.json_cli('plan-show', plan['id'], '--limit', '1', '--csv-out', str(self.root / 'export.csv'))
        self.assertEqual((shown['row_count'], len(shown['rows'])), (3, 1))
        self.assertEqual(len((self.root / 'export.csv').read_text().splitlines()), 4)

    def test_05_failures_are_json_with_exit_one(self):
        self.assertEqual(self.json_cli('plan-show', 'not-a-uuid', ok=False)['error'], '计划标识无效。')
        self.assertIn('进度记录', self.json_cli('progress', 'missing', ok=False)['error'])
        text = self.run_cli('plan-show', 'not-a-uuid')
        self.assertEqual((text.returncode, text.stdout), (1, ''))
        self.assertIn('计划标识无效', text.stderr)

    def test_06_reads_and_diagnostics(self):
        self.assertEqual(self.json_cli('audit')['total'], 3)
        self.assertEqual(self.json_cli('records')['records'], [])
        settings = self.json_cli('settings')
        self.assertEqual(settings['saved'], False)
        self.assertEqual(set(settings['preferences']), set(preferences.DEFAULTS))
        doctor = self.json_cli('doctor')
        self.assertTrue(all(c['ok'] for c in doctor['checks'] if c['required']))
        rows = {c['name']: c for c in doctor['checks']}
        # app_running only tells; the two grants are read from the system by the app executable (never a prompt),
        # and where they could not be read they say so instead of passing. None of the three decides `ok`.
        self.assertIsNone(rows['app_running']['ok'])
        for name in ('photos_access', 'photos_automation'):
            self.assertIn(rows[name]['ok'], (True, False, None), rows[name])
            self.assertTrue(rows[name]['detail'])
            if rows[name]['ok'] is None:
                self.assertIn('未检查', rows[name]['detail'])
        self.assertFalse(any(rows[name]['required'] for name in ('app_running', 'photos_access', 'photos_automation')))
        self.assertEqual(set(doctor['permissions']), {'photos_access', 'photos_automation'})
        self.assertEqual({c['name'] for c in doctor['checks'] if c['ok'] is None} - {'photos_access', 'photos_automation'}, {'app_running'})
        self.assertIsInstance(doctor['app_running'], bool)

    def test_07_cli_only_tools_speak_json(self):
        shared = self.json_cli('shared-list')
        self.assertEqual((shared['command'], shared['shared_photos'], shared['duplicate_groups']), ('shared-list', 0, 0))
        self.assertTrue(Path(shared['report']).is_relative_to(self.root / 'state'))
        # Failures inside a CLI-only tool are the same JSON object with exit 1.
        failed = self.json_cli('reconcile', ok=False)
        self.assertEqual(failed['command'], 'reconcile')

    def test_08_failures_before_a_command_runs_are_json_too(self):
        usage = self.run_cli('timeline', '--json', '--bogus')
        self.assertEqual(usage.returncode, 1)
        data = json.loads(usage.stdout)
        self.assertEqual((data['ok'], data['command']), (False, 'timeline'))
        self.assertIn('--bogus', data['error'])
        self.assertEqual(self.run_cli('timeline', '--bogus').stdout, '')

    def test_09_reads_survive_an_unwritable_data_folder(self):
        locked = self.root / 'locked'
        locked.mkdir(mode=0o700)
        locked.chmod(0o500)  # no new files or folders; the read-only commands must still answer
        self.addCleanup(locked.chmod, 0o700)
        env = self.env | {'PHOTODESK_DATA_ROOT': str(locked)}
        run = lambda *args: subprocess.run([sys.executable, str(ROOT / 'backend/bridge.py'), *args, '--json'],
                                           text=True, capture_output=True, env=env, timeout=60)
        plans = run('plans')
        self.assertEqual(plans.returncode, 0, plans.stderr)
        self.assertEqual(json.loads(plans.stdout)['entries'], [])
        written = run('plan', 'library')
        self.assertEqual(written.returncode, 1)
        self.assertEqual(json.loads(written.stdout)['ok'], False)

    def test_10_top_level_help_is_the_agent_contract(self):
        """Reads and writes, the --json shape, exit codes and the window-only items are in --help,
        and sop.agent_cli in project.yaml only names commands that help lists."""
        import yaml
        text = self.run_cli('--help').stdout
        for heading in ('读命令', '写命令', '--json 输出', '退出码', '仅在窗口中'):
            self.assertIn(heading, text)
        listed = set(re.findall(r'^  ([a-z][a-z-]*)\s', text, re.M))
        spec = yaml.safe_load((ROOT / 'project.yaml').read_text())['sop']['agent_cli']
        self.assertEqual(spec['readback'], 'photodesk doctor')
        self.assertIn('doctor', listed)
        names = [feature['name'] for feature in spec['features']]
        self.assertEqual(len(names), len(set(names)))
        for feature in spec['features']:
            kinds = {'command', 'human', 'missing'} & set(feature)
            self.assertEqual(len(kinds), 1, feature)
            if 'command' in feature:
                main, sub = feature['command'].split()[:2]
                self.assertEqual(main, 'photodesk', feature)
                self.assertIn(sub, listed, feature)
            if 'human' in feature:  # every window-only item is told to the agent in --help
                self.assertIn(feature['name'], text, feature)

    def test_11_readback_is_read_only_json(self):
        state = self.root / 'state'
        before = sorted((str(f.relative_to(state)), f.stat().st_mtime_ns) for f in state.rglob('*') if f.is_file())
        data = json.loads(self.run_cli('doctor', '--json').stdout)
        self.assertEqual(data['command'], 'doctor')
        self.assertIn('engine', [check['name'] for check in data['checks']])
        after = sorted((str(f.relative_to(state)), f.stat().st_mtime_ns) for f in state.rglob('*') if f.is_file())
        self.assertEqual(before, after)


class SettingsCommand(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        patches = [patch.object(preferences, 'STORE', self.store), patch.object(desk_cli, 'API', bridge),
                   patch.dict(os.environ, {'PHOTODESK_PREFERENCES_SUITE': 'PhotoDesk.Test.Unit'})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop('PHOTODESK_DEMO_ROOT', None)
        os.environ.pop('PHOTODESK_LIBRARY', None)
        desk_cli.install(cli, bridge)

    def invoke(self, *args):
        return CliRunner().invoke(cli, list(args), obj={}, catch_exceptions=False)

    def test_set_and_read_back_or_refuse(self):
        with patch.object(preferences, 'app_running', return_value=False):
            result = self.invoke('settings', 'set', 'batchSize', '24', '--json')
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)['value'], 24)
            shown = json.loads(self.invoke('settings', '--json').stdout)
            self.assertEqual((shown['saved'], shown['preferences']['batchSize']), (True, 24))
            bad = self.invoke('settings', 'set', 'batchSize', '7', '--json')
            self.assertEqual((bad.exit_code, json.loads(bad.stdout)['ok']), (1, False))
        with patch.object(preferences, 'app_running', return_value=True):
            refused = self.invoke('settings', 'set', 'batchSize', '6', '--json')
            self.assertEqual(refused.exit_code, 1)
            self.assertIn('正在运行', json.loads(refused.stdout)['error'])
        self.assertEqual(preferences.load(self.store)[0]['batchSize'], 24)


class PermissionChecks(unittest.TestCase):
    """doctor's two grant rows from what the app executable read: a grant passes only when the system says so, a
    reading that is missing or not PhotoDesk's own is told as unread, never as a pass."""

    def rows(self, grants):
        return {name: (ok, detail) for name, ok, detail in desk_cli.permission_checks(grants)}

    def grants(self, status, own=True, automation='allowed'):
        return {'photos': {'status': status, 'granted': status in ('authorized', 'limited'), 'own_identity': own, 'from': 'probe'},
                'automation': {'caller': {'state': automation, 'code': 0}, 'app': None}}

    def test_each_reading_is_told_as_it_is(self):
        for status, ok in (('authorized', True), ('limited', True), ('denied', False), ('restricted', False), ('not_determined', False)):
            self.assertIs(self.rows(self.grants(status))['photos_access'][0], ok, status)
        for state, ok in (('allowed', True), ('denied', False), ('not_asked', False), ('target_not_running', None), ('no_answer', None)):
            row = self.rows(self.grants('authorized', automation=state))['photos_automation']
            self.assertIs(row[0], ok, state)
            self.assertEqual('未检查' in row[1], ok is None, row)

    def test_an_unread_or_foreign_reading_never_passes(self):
        for grants in (None, {}, {'photos': {'status': 'unknown'}}, self.grants('authorized', own=False), self.grants('authorized', own=None)):
            ok, detail = self.rows(grants)['photos_access']
            self.assertIsNone(ok, grants)
            self.assertIn('未检查', detail)
        self.assertIsNone(self.rows(None)['photos_automation'][0])

    def test_no_app_executable_means_unread(self):
        with patch.object(desk_cli, 'app_binary', return_value=None):
            self.assertIsNone(desk_cli.app_permissions())


if __name__ == '__main__':
    unittest.main()

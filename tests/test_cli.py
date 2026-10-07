"""CLI dispatch, product configuration and synthetic safety without real Photos access."""
import datetime as dt
import importlib.util
import io
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
from photocli import lib, title
from photocli.cli import cli

COMMANDS = {
    'apply', 'audit', 'delete-check', 'doctor', 'duplicates', 'photos', 'plan', 'plan-show', 'plans',
    'progress', 'records', 'refresh', 'settings', 'timeline',
    'classify-plan', 'classify-apply', 'title-plan', 'title-apply', 'triage', 'ocr-scan',
    'backup', 'ocr-extract', 'shared-list', 'dedup-export', 'reconcile',
    # Answered by the app executable; the engine forwards them (desk_cli.APP_VERBS)
    'config', 'update', 'shortcuts', 'login', 'automation', 'cancel',
}


class CLITests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='PhotoDesk-cli-unit-')
        self.root = Path(self.scratch.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('PHOTOCLI_', 'PHOTODESK_'))}
        self.env['PHOTODESK_DATA_ROOT'] = str(self.root / 'state')
        # A never-written preferences domain: commands read app settings, never the real ones.
        self.env['PHOTODESK_PREFERENCES_SUITE'] = f'PhotoDesk.Test.CLI.{os.getpid()}.{id(self)}'

    def tearDown(self):
        self.scratch.cleanup()

    def run_bridge(self, *args, data=None, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'backend/bridge.py'), *args],
                              input=data, text=True, capture_output=True, env=env or self.env, timeout=30)

    def test_arguments_select_cli_and_list_every_command(self):
        result = self.run_bridge('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Usage: photodesk', result.stdout)
        self.assertIn('PhotoDesk', result.stdout.splitlines()[2])
        listed = set(re.findall(r'^  ([a-z][a-z-]*)\s', result.stdout, re.M))
        self.assertEqual(listed, COMMANDS)
        # The legacy-only tools stay in the photocli group; the rest come from desk_cli.
        self.assertEqual(set(cli.commands), {'backup', 'ocr-extract', 'shared-list', 'dedup-export', 'reconcile'})

    def test_pipe_without_arguments_preserves_json_contract(self):
        result = self.run_bridge(data='{"command":"history"}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'ok': True, 'data': {'entries': []}})

    def test_terminal_without_arguments_dispatches_help_without_reading(self):
        spec = importlib.util.spec_from_file_location('cli_test_bridge', ROOT / 'backend/bridge.py')
        bridge = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, self.env, clear=True):
            spec.loader.exec_module(bridge)
        terminal = SimpleNamespace(isatty=lambda: True)
        with patch('photocli.cli.run', return_value=0) as run, patch.object(bridge, 'main') as json_main:
            self.assertEqual(bridge.dispatch([], terminal), 0)
            run.assert_called_once_with(['--help'])
            json_main.assert_not_called()

    def test_pet_subject_and_gui_settings_use_configured_names(self):
        photo = SimpleNamespace(cloud_guid='fixture', persons=['Example Cat'], labels=[],
                                date=dt.datetime(2026, 1, 2), place=None)
        cfg = lib.Config({'classify': {'pet_faces': ['Example Cat']}})
        self.assertEqual(title._make_title(photo, cfg), '2026-01 · 猫·Example Cat')
        self.assertEqual(title._make_title(photo, lib.Config({})), '2026-01 · Example Cat')
        spec = importlib.util.spec_from_file_location('cli_config_bridge', ROOT / 'backend/bridge.py')
        bridge = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, self.env, clear=True):
            spec.loader.exec_module(bridge)
        self.assertEqual(bridge.config({'settings': {'pet_names': ['Example Cat']}}).section('classify')['pet_faces'], ['Example Cat'])

    def test_private_config_precedence_and_cli_output_isolation(self):
        # The private YAML drives the legacy tools; the app-function commands only take a
        # library from it when --config is passed explicitly (never from the ambient file).
        state = self.root / 'state'
        state.mkdir()
        (state / 'cli-config.yaml').write_text('invalid: [yaml')
        broken = self.run_bridge('reconcile')
        self.assertEqual(broken.returncode, 1)
        self.assertEqual(len(broken.stderr.splitlines()), 1)
        self.assertIn('合法 YAML', broken.stderr)
        explicit = self.root / 'explicit.yaml'
        explicit.write_text('library: /nonexistent/Explicit.photoslibrary\n')
        good_env = self.env | {'PHOTOCLI_CONFIG': str(explicit)}
        overridden = self.run_bridge('reconcile', env=good_env)
        self.assertEqual(overridden.returncode, 1)
        self.assertIn('照片库不存在', overridden.stderr)
        self.assertNotIn('Traceback', overridden.stderr)
        audit = self.run_bridge('--config', str(explicit), 'audit', '--json')
        self.assertEqual(audit.returncode, 1)
        self.assertEqual(audit.stderr, '')
        self.assertEqual(json.loads(audit.stdout)['ok'], False)
        self.assertIn('photoslibrary', json.loads(audit.stdout)['error'])
        self.assertEqual((state / 'cli').stat().st_mode & 0o777, 0o700)
        with patch.dict(os.environ, {'PHOTODESK_CLI': '1'}), patch.object(lib, 'REPO_ROOT', state / 'cli'):
            self.assertEqual(lib.Config({'paths': {'plans': '/outside'}}).path('plans'), state / 'cli/plans')

    def test_demo_write_commands_are_rejected_before_touching_photos(self):
        for command in ('classify-apply', 'title-apply', 'ocr-scan', 'triage'):
            result = self.run_bridge(command, '--apply', env=self.env | {'PHOTODESK_DEMO_ROOT': str(self.root)})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertIn('演示模式禁止', result.stderr)
        # The new names go through the engine's own guard, not a string match on --apply.
        demo = self.env | {'PHOTODESK_DEMO_ROOT': str(self.root), 'PHOTODESK_DATA_ROOT': str(self.root / 'state')}
        plan_id = '00000000-0000-4000-8000-000000000000'
        for args in (('apply', plan_id, '--select', '0', '--confirm'), ('delete-check', plan_id, '--select', '0'),
                     ('plan', 'classify')):
            result = self.run_bridge(*args, '--json', env=demo)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('合成演示图库只用于', json.loads(result.stdout)['error'])

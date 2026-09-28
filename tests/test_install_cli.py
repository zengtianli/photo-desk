"""Installer link ownership and CLI-process safety, in temporary directories."""
import importlib.util
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('install_app', Path(__file__).resolve().parents[1] / 'scripts/install_app.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallCLITests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.source = self.root / 'build/PhotoDesk.app'
        resources = self.source / 'Contents/Resources'
        (resources / 'Engine').mkdir(parents=True)
        (resources / 'bin').mkdir()
        engine = resources / 'Engine/photo-engine'
        engine.write_text('#!/bin/sh\nexit 0\n')
        engine.chmod(0o755)
        (resources / 'bin/photodesk').symlink_to('../Engine/photo-engine')
        (self.source / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'cyou.tianli.PhotoDesk'}))
        self.apps = self.root / 'Applications'
        self.apps.mkdir()
        self.bin = self.root / 'bin'

    def install(self):
        def run(command, **kwargs):
            if command[0].endswith('ditto'):
                shutil.copytree(command[1], command[2], symlinks=True)
        with patch.object(installer.subprocess, 'run', side_effect=run), \
             patch.object(installer.subprocess, 'check_output', return_value=''):
            return installer.install(self.source, 'PhotoDesk', 'PhotoDesk · 照片台', 'cyou.tianli.PhotoDesk',
                                     self.apps, self.root / 'Trash', self.bin)

    def test_install_and_repeat_preserve_two_level_link(self):
        installed = self.install()
        self.assertEqual((self.bin / 'photodesk').resolve(), installed / 'Contents/Resources/Engine/photo-engine')
        self.install()
        self.assertTrue((self.bin / 'photodesk').is_file())
        self.assertEqual(len(list((self.root / 'Trash').glob('*/PhotoDesk.app'))), 1)

    def test_foreign_command_file_is_preserved(self):
        self.bin.mkdir()
        command = self.bin / 'photodesk'
        command.write_text('user-owned')
        with self.assertRaisesRegex(RuntimeError, '非软链'):
            self.install()
        self.assertEqual(command.read_text(), 'user-owned')
        self.assertFalse((self.apps / 'PhotoDesk.app').exists())

    def test_running_cli_through_two_links_refuses_replacement(self):
        installed = self.install()
        with patch.object(installer.subprocess, 'check_output', return_value=f'123 {self.bin / "photodesk"}\n'):
            with self.assertRaisesRegex(RuntimeError, '正在运行'):
                installer.check_running([installed])

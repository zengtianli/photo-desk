"""Error contracts of the vendored engine, without opening any real library."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import click

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
from photocli import lib


class VendorLibTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='PhotoDesk-lib-test-')
        self.root = Path(self.scratch.name)
        lib.load_config.cache_clear()
        lib.load_db.cache_clear()

    def tearDown(self):
        lib.load_config.cache_clear()
        lib.load_db.cache_clear()
        self.scratch.cleanup()

    def test_config_errors_do_not_replace_cached_success_or_prevent_recovery(self):
        good_path = self.root / 'good.yaml'
        good_path.write_text('library: synthetic.photoslibrary\n')
        good = lib.load_config(str(good_path))
        broken = self.root / 'broken.yaml'
        cases = (
            (None, '配置文件不存在'),
            ('paths: [unterminated', '配置文件不是合法 YAML'),
            ('- not-a-mapping\n', '配置文件顶层须为映射'),
            ('scalar-value\n', '配置文件顶层须为映射'),
        )
        for contents, message in cases:
            with self.subTest(message=message, contents=contents):
                if contents is not None:
                    broken.write_text(contents)
                with self.assertRaises(click.ClickException) as caught:
                    lib.load_config(str(broken))
                self.assertIn(message, str(caught.exception))
                self.assertIn(str(broken), str(caught.exception))
                self.assertEqual(caught.exception.exit_code, 1)
                self.assertIs(lib.load_config(str(good_path)), good)
        broken.write_text('library: recovered.photoslibrary\n')
        recovered = lib.load_config(str(broken))
        self.assertEqual(recovered.library, 'recovered.photoslibrary')
        self.assertIs(lib.load_config(str(broken)), recovered)

    def test_empty_config_still_supports_defaults(self):
        path = self.root / 'empty.yaml'
        path.write_text('')
        config = lib.load_config(str(path))
        self.assertEqual(config.raw, {})
        self.assertIsNone(config.library)
        self.assertTrue(config.personal_only)

    def test_library_failures_are_actionable_and_do_not_poison_success_cache(self):
        cases = (
            (FileNotFoundError('raw missing detail'), '照片库不存在', 'config.yaml'),
            (PermissionError('raw permission detail'), '无权读取照片库', '完全磁盘访问权限'),
            (sqlite3.DatabaseError('raw database detail'), '照片库数据库读不了', 'DatabaseError'),
            (ValueError('raw unexpected detail'), '照片库解析失败', 'ValueError'),
        )
        good_path = str(self.root / 'Good.photoslibrary')
        bad_path = str(self.root / 'Broken.photoslibrary')
        for failure, message, hint in cases:
            with self.subTest(error=type(failure).__name__):
                lib.load_db.cache_clear()
                good, recovered = object(), object()
                factory = Mock(side_effect=[good, failure, recovered])
                # Replacing the module prevents import or initialization of the
                # actual osxphotos PhotosDB, even if a default path is requested.
                with patch.dict(sys.modules, {'osxphotos': types.SimpleNamespace(PhotosDB=factory)}):
                    self.assertIs(lib.load_db(good_path), good)
                    with self.assertRaises(click.ClickException) as caught:
                        lib.load_db(bad_path)
                    text = str(caught.exception)
                    self.assertIn(message, text)
                    self.assertIn(hint, text)
                    self.assertIn(bad_path, text)
                    self.assertNotIn(str(failure), text)
                    self.assertEqual(caught.exception.exit_code, 1)
                    self.assertIs(lib.load_db(good_path), good)
                    self.assertIs(lib.load_db(bad_path), recovered)
                    self.assertIs(lib.load_db(bad_path), recovered)
                    self.assertEqual(factory.call_count, 3)

    def test_default_library_keeps_no_argument_call_and_identifies_failure(self):
        factory = Mock(side_effect=FileNotFoundError())
        with patch.dict(sys.modules, {'osxphotos': types.SimpleNamespace(PhotosDB=factory)}):
            with self.assertRaisesRegex(click.ClickException, '照片库不存在: 系统默认图库'):
                lib.load_db()
        factory.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()

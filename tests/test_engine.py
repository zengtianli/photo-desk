import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import copy
from types import SimpleNamespace as Photo
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge', ROOT / 'backend/bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
cfg = bridge.config({})

def photo(**overrides):
    data = dict(cloud_guid='guid', uuid='uuid', original_filename='fixture.png', date=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
                favorite=False, persons=[], keywords=[], shared=False, shared_library=False, syndicated=False,
                title='', uti='public.png', labels=[], albums=[], album_info=[])
    data.update(overrides)
    return Photo(**data)

def row(**overrides):
    data = dict(id='0', cloud_guid='guid', action='add-album', target='2026/2026-08', original_title='')
    data.update(overrides)
    return data

class SafetyTests(unittest.TestCase):
    def test_missing_ocr_is_unknown(self):
        bucket, _ = bridge.triage._classify(photo(), '', cfg, dt.date(2026, 3, 1), [])
        self.assertEqual(bucket, 'unsure')

    def test_old_receipt_not_inferred_reimbursed(self):
        with patch.object(bridge.triage, '_is_receipt', return_value=True), patch.object(bridge.triage, '_latest_date', return_value=dt.date(2020, 1, 1)):
            self.assertEqual(bridge.triage._classify(photo(), 'invoice', cfg, dt.date(2026, 3, 1), [])[0], 'receipt')

    def test_favorites_excluded_from_cleanup(self):
        with patch.object(bridge.classify, 'iter_photos', return_value=[photo(favorite=True)]):
            rows = bridge.classify._build_rows(cfg)
        self.assertFalse(any(r.target == '待清理候选' for r in rows))
        self.assertTrue(any(r.target == '2026/2026-08' for r in rows))

    def test_exact_selection(self):
        plan = {'rows': [row(), row(id='1', target='另一个相册')]}
        selected, _ = bridge.validate_selection(plan, ['1'], [photo()], cfg)
        self.assertEqual([r['id'] for r in selected], ['1'])

    def test_stale_missing_and_shared_abort(self):
        for photos in ([], [photo(shared=True)], [photo(shared_library=True)]):
            with self.assertRaises(ValueError): bridge.validate_selection({'rows': [row()]}, ['0'], photos, cfg)

    def test_modified_title_abort(self):
        with self.assertRaises(ValueError):
            bridge.validate_selection({'rows': [row(action='set-title')]}, ['0'], [photo(title='用户刚写的标题')], cfg)

    def test_unknown_selection_abort(self):
        with self.assertRaises(ValueError): bridge.validate_selection({'rows': [row()]}, ['99'], [photo()], cfg)

    def test_read_only_duplicate_cannot_apply(self):
        with self.assertRaises(ValueError): bridge.validate_selection({'rows': [row(action='review')]}, ['0'], [photo()], cfg)

    def test_newly_protected_cleanup_abort(self):
        with self.assertRaises(ValueError):
            bridge.validate_selection({'rows': [row(target='待清理候选')]}, ['0'], [photo(favorite=True)], cfg)

    def test_apply_writes_only_reviewed_rows_and_checks_readback(self):
        import photoscript
        import osxphotos.photosalbum
        import osxphotos.utils
        plan = {'id': 'fixture', 'library': '/fake.photoslibrary', 'rows': [
            row(), row(id='1', action='set-title', target='测试标题'),
            row(id='2', action='add-keyword', target='测试标签'), row(id='3', target='未勾选相册')]}
        live = photo()
        live.keywords = ['原有标签']
        membership = []
        album = MagicMock()
        album.album.add.side_effect = lambda photos: membership.extend(photos)
        album.photos.side_effect = lambda: membership
        receipts = []
        with patch.object(bridge, 'load_plan', return_value=plan), \
             patch.object(bridge.lib, 'load_db', return_value=Photo(photos=lambda: [photo()])), \
             patch.object(osxphotos.utils, 'get_last_library_path', return_value='/fake.photoslibrary'), \
             patch.object(photoscript, 'Photo', return_value=live), \
             patch.object(osxphotos.photosalbum, 'PhotosAlbum', return_value=album) as create, \
             patch.object(bridge, 'atomic_json', side_effect=lambda path, data: receipts.append(copy.deepcopy(data))):
            result = bridge.apply_plan({'plan_id': 'fixture', 'selected': ['0', '1', '2'], 'confirmed': True}, cfg)
        self.assertEqual(result['changed'], 3)
        self.assertEqual(live.title, '测试标题')
        self.assertEqual(set(live.keywords), {'原有标签', '测试标签'})
        create.assert_called_once_with('2026/2026-08', split_folder='/')
        self.assertEqual(receipts[-1]['state'], 'complete')
        self.assertEqual(set(receipts[-1]['completed']), {'0', '1', '2'})

    def test_partial_write_is_never_reported_as_success(self):
        import photoscript
        import osxphotos.photosalbum
        import osxphotos.utils
        plan = {'id': 'fixture', 'library': '/fake.photoslibrary', 'rows': [row()]}
        album = MagicMock(); album.photos.return_value = []
        receipts = []
        with patch.object(bridge, 'load_plan', return_value=plan), \
             patch.object(bridge.lib, 'load_db', return_value=Photo(photos=lambda: [photo()])), \
             patch.object(osxphotos.utils, 'get_last_library_path', return_value='/fake.photoslibrary'), \
             patch.object(photoscript, 'Photo', return_value=photo()), \
             patch.object(osxphotos.photosalbum, 'PhotosAlbum', return_value=album), \
             patch.object(bridge, 'atomic_json', side_effect=lambda path, data: receipts.append(copy.deepcopy(data))):
            with self.assertRaisesRegex(RuntimeError, '写入中止'):
                bridge.apply_plan({'plan_id': 'fixture', 'selected': ['0'], 'confirmed': True}, cfg)
        self.assertEqual(receipts[-1]['state'], 'partial_or_failed')

if __name__ == '__main__': unittest.main()

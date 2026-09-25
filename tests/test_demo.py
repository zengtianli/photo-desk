import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import bridge
import demo
import journey


class DemoIsolation(unittest.TestCase):
    def test_production_grouping_and_hashes_without_photosdb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'a.png').write_bytes(b'clearly synthetic input')
            (root / 'b.png').write_bytes(b'clearly synthetic input')
            rows = [dict(uuid=f'00000000-0000-0000-0000-00000000000{i}', file=f'{name}.png',
                         date='2026-09-09T10:00:00+08:00', albums=['猫咪'], title='')
                    for i, name in enumerate(('a', 'b'))]
            (root / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1', 'photos': rows}))
            with patch.dict(os.environ, {'PHOTODESK_DEMO_ROOT': str(root)}), \
                 patch.object(bridge, 'ROOT', root / 'state'), \
                 patch.object(bridge.lib, 'load_db', side_effect=AssertionError('Real PhotosDB accessed')):
                request = {'command': 'journey-snapshot', 'options': {'recognize_content': False}}
                result = journey.run(request, bridge.config(request), bridge)
                self.assertEqual(result['total'], 2)
                self.assertEqual(sum(e['count'] for e in result['events']), 2)
                self.assertIn('猫时间线', result['tracks'])
                self.assertEqual(len(result['duplicates']['rows']), 2)
                self.assertEqual(sum(r['recommended'] for r in result['duplicates']['rows']), 1)
            with patch.dict(os.environ, {'PHOTODESK_DEMO_ROOT': str(root)}), patch.object(bridge, 'ROOT', root.parent):
                with self.assertRaisesRegex(ValueError, '独立数据目录'):
                    bridge.load_db()

    def test_unchanged_result_is_not_resent_or_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'a.png').write_bytes(b'first synthetic input')
            rows = [dict(uuid='00000000-0000-0000-0000-000000000001', file='a.png',
                         date='2026-09-09T10:00:00+08:00', albums=['猫咪'], title='')]
            def write_input(title):
                rows[0]['title'] = title
                (root / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1', 'photos': rows}))
            write_input('')
            with patch.dict(os.environ, {'PHOTODESK_DEMO_ROOT': str(root)}), patch.object(bridge, 'ROOT', root / 'state'):
                def run(previous='', options=None):
                    request = {'command': 'journey-snapshot', 'previous_digest': previous,
                               'options': options or {'recognize_content': False}}
                    return journey.run(request, bridge.config(request), bridge)
                first = run()
                files = [bridge.plan_path(first['plan']['id']), bridge.plan_path(first['duplicates']['id']),
                         next((root / 'state' / 'journey').glob('*/latest.json'))]
                stamps = [f.stat().st_mtime_ns for f in files]
                again = run(first['digest'])
                self.assertEqual(again, {'unchanged': True, 'digest': first['digest']})
                self.assertEqual([f.stat().st_mtime_ns for f in files], stamps, 'unchanged runs must not rewrite files')
                # Timestamps alone never count as a change.
                self.assertEqual(run()['digest'], first['digest'])
                # Content, options and missing files all force a full reply.
                write_input('新的标题')
                changed = run(first['digest'])
                self.assertNotEqual(changed.get('digest'), first['digest'])
                self.assertIn('events', changed)
                self.assertIn('events', run(changed['digest'], {'recognize_content': False, 'event_hours': 1}))
                files[0].unlink()
                self.assertIn('events', run(changed['digest']))
                self.assertTrue(files[0].is_file())

    def test_same_second_photos_keep_their_order_between_runs(self):
        # osxphotos lists photos in a per-process order; the result must not depend on it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for i in range(4):
                (root / f'{i}.png').write_bytes(f'synthetic {i}'.encode())
                rows.append(dict(uuid=f'00000000-0000-0000-0000-00000000000{i}', file=f'{i}.png',
                                 date='2026-09-09T10:00:00+08:00', albums=[], title=''))
            digests = []
            for order in (rows, rows[::-1], rows[1:] + rows[:1]):
                (root / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1', 'photos': order}))
                with patch.dict(os.environ, {'PHOTODESK_DEMO_ROOT': str(root)}), patch.object(bridge, 'ROOT', root / 'state'):
                    request = {'command': 'journey-snapshot', 'options': {'recognize_content': False}}
                    result = journey.run(request, bridge.config(request), bridge)
                    digests.append((result['digest'], [r['local_uuid'] for r in result['plan']['rows']]))
            self.assertEqual(len(set(d for d, _ in digests)), 1, digests)

    def test_fixture_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1',
                'photos': [{'file': '../outside.png', 'date': '2026-09-09T10:00:00+08:00'}]}))
            with self.assertRaisesRegex(ValueError, '独立演示目录'):
                demo.Library(root)


if __name__ == '__main__':
    unittest.main()

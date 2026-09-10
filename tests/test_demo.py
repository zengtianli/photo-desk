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

    def test_fixture_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'demo-input.json').write_text(json.dumps({'format': 'photodesk-synthetic-input-v1',
                'photos': [{'file': '../outside.png', 'date': '2026-09-09T10:00:00+08:00'}]}))
            with self.assertRaisesRegex(ValueError, '独立演示目录'):
                demo.Library(root)


if __name__ == '__main__':
    unittest.main()

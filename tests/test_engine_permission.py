"""Keep App-specific permission recovery after the shared loader wraps errors."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_engine import bridge


class EnginePermissionTests(unittest.TestCase):
    def test_wrapped_library_permission_error_targets_photodesk(self):
        bridge.lib.load_db.cache_clear()
        self.addCleanup(bridge.lib.load_db.cache_clear)
        with tempfile.TemporaryDirectory(prefix='PhotoDesk-permission-test-') as scratch:
            root = Path(scratch)
            library = root / 'Denied.photoslibrary'
            library.mkdir()
            output = io.StringIO()
            with patch.object(bridge, 'ROOT', root / 'data'), \
                 patch.object(bridge.sys, 'stdin', io.StringIO(json.dumps({'command': 'audit', 'library': str(library)}))), \
                 patch('osxphotos.PhotosDB', side_effect=PermissionError('synthetic denial')), \
                 patch.dict(bridge.os.environ, {'PHOTODESK_DEMO_ROOT': ''}), \
                 contextlib.redirect_stdout(output):
                bridge.main()
            result = json.loads(output.getvalue())
            self.assertFalse(result['ok'])
            self.assertIn('完全磁盘访问权限中启用 PhotoDesk', result['error'])
            self.assertNotIn('终端', result['error'])
            self.assertEqual(bridge.lib.load_db.cache_info().currsize, 0)

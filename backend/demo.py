"""Synthetic input adapter: production analysis and views, no Apple Photos access."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        data = json.loads((self.root / 'demo-input.json').read_text())
        if data.get('format') != 'photodesk-synthetic-input-v1':
            raise ValueError('演示输入格式无效；未访问系统照片图库。')
        self.library_path = str(self.root)
        self._photos = []
        for row in data['photos']:
            path = (self.root / row['file']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError('演示照片必须位于独立演示目录。')
            date = dt.datetime.fromisoformat(row['date'])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            photo = SimpleNamespace(uuid=row['uuid'], cloud_guid='', path=str(path), path_derivatives=[],
                fingerprint=digest, original_filename=path.name, original_filesize=path.stat().st_size,
                date=date, date_modified=date, persons=[], albums=row.get('albums', []),
                keywords=[], title=row.get('title', ''), description='', place=None, location=(None, None),
                shared=False, shared_library=False, syndicated=False, saved_to_library=True,
                isphoto=True, ismovie=False, live_photo=False, hasadjustments=False, hidden=False,
                favorite=False, labels=[], uti='public.png', screenshot=False)
            self._photos.append(photo)
        self.albums = sorted({a for p in self._photos for a in p.albums})

    def photos(self):
        return self._photos

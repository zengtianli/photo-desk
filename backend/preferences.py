"""The app's saved settings, read and written the way the app does.

Source of truth is Swift: PhotoPreferences in Sources/ProductControls.swift (13 fields stored as
one JSON blob under product.preferences.v1) and PhotoDeskModel.library in Sources/ViewModel.swift
(the `library` key; empty means "follow the library Photos last opened"). Both live in the
UserDefaults domain cyou.tianli.PhotoDesk, or in PHOTODESK_PREFERENCES_SUITE when the app is
launched with it for isolated tests. tests/test_desk_cli.py compares the ranges below with the
Swift source so the two cannot drift.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

APP_DOMAIN = 'cyou.tianli.PhotoDesk'
STORAGE_KEY = 'product.preferences.v1'
LIBRARY_KEY = 'library'

DEFAULTS = {
    'automatic': True, 'includeShared': True, 'recognizeContent': True, 'refreshSeconds': 60,
    'batchSize': 12, 'eventHours': 3, 'eventKilometers': 8, 'meetingMinutes': 90, 'petNames': '',
    'preselectDuplicates': True, 'thumbnailWidth': 180.0, 'appearance': 'system', 'initialTrack': '全部',
}
# PhotoPreferences.load clamps every saved value into these ranges.
CLAMPS = {'refreshSeconds': (30, 3600), 'batchSize': (1, 24), 'eventHours': (1, 12),
          'eventKilometers': (1, 100), 'meetingMinutes': (15, 180), 'thumbnailWidth': (140, 280)}
# What the Settings window can produce; `settings set` accepts exactly these, so the app never
# opens with a picker that shows no selection.
CHOICES = {'refreshSeconds': (60, 300, 900), 'batchSize': (6, 12, 24),
           'appearance': ('system', 'light', 'dark'),
           'initialTrack': ('全部', '个人时间线', '猫时间线', '会议与工作', '资料与截图')}
STEPS = {'eventHours': (1, 12, 1), 'eventKilometers': (1, 100, 1), 'meetingMinutes': (15, 180, 15),
         'thumbnailWidth': (140, 280, 10)}
FLAGS = ('automatic', 'includeShared', 'recognizeContent', 'preselectDuplicates')
TRUE, FALSE = ('true', '1', 'yes', 'on'), ('false', '0', 'no', 'off')


class Store:
    """UserDefaults through CFPreferences (cfprefsd), the same store the app reads."""

    def get(self, key, domain):
        import CoreFoundation as CF
        value = CF.CFPreferencesCopyAppValue(key, domain)
        if value is None:
            return None
        return bytes(value) if key == STORAGE_KEY else str(value)

    def set(self, key, value, domain):
        import CoreFoundation as CF
        from Foundation import NSData
        if isinstance(value, bytes):
            value = NSData.dataWithBytes_length_(value, len(value))
        CF.CFPreferencesSetAppValue(key, value, domain)
        if not CF.CFPreferencesAppSynchronize(domain):
            raise OSError('系统未能保存 PhotoDesk 设置。')


STORE = Store()


def domain():
    return os.environ.get('PHOTODESK_PREFERENCES_SUITE') or APP_DOMAIN


def load(store=None):
    """(values, saved): PhotoPreferences.load, including its fallback to fresh defaults."""
    store = store or STORE
    raw = store.get(STORAGE_KEY, domain())
    values = dict(DEFAULTS)
    saved = False
    if raw:
        try:
            decoded = json.loads(raw)
        except ValueError:
            decoded = None
        # Swift's synthesized decoder needs every field; anything less means fresh defaults.
        if isinstance(decoded, dict) and all(k in decoded for k in DEFAULTS):
            values = {k: decoded[k] for k in DEFAULTS}
            saved = True
    if not saved and os.environ.get('PHOTODESK_DEMO_ROOT'):
        values['appearance'] = 'light'
    for key, (low, high) in CLAMPS.items():
        values[key] = max(low, min(high, values[key]))
    values['thumbnailWidth'] = float(values['thumbnailWidth'])  # a Double in Swift
    return values, saved


def library(store=None):
    """(path, source) exactly as the app picks it: PHOTODESK_LIBRARY, the saved choice, else ''."""
    if os.environ.get('PHOTODESK_LIBRARY'):
        return os.environ['PHOTODESK_LIBRARY'], 'env'
    saved = (store or STORE).get(LIBRARY_KEY, domain())
    return (saved, 'saved') if saved else ('', 'system')


PHOTOS_PLIST = Path.home() / 'Library/Containers/com.apple.Photos/Data/Library/Preferences/com.apple.Photos.plist'


def photos_last_library():
    """The library Photos opened last, or None: the library the engine reads when `library` is ''.

    Same plist key and bookmark resolution as osxphotos.utils.get_last_library_path (which the
    engine's PhotosDB() uses), without importing osxphotos, so reading a cached timeline stays
    light. tests/test_desk_cli.py checks the two agree.
    """
    import plistlib
    import urllib.parse
    try:
        with open(PHOTOS_PLIST, 'rb') as handle:
            bookmark = plistlib.load(handle).get('IPXDefaultLibraryURLBookmark')
    except FileNotFoundError:
        return None
    if bookmark is None:
        return None
    import CoreFoundation as CF
    url = CF.CFURLCreateByResolvingBookmarkData(CF.kCFAllocatorDefault, bookmark, 0, None, None, None, None)
    text = url[0].absoluteString() if url[0] else None
    return os.path.normpath(urllib.parse.unquote(urllib.parse.urlparse(text).path)) if text else None


def pet_names(text):
    parts = text.replace('，', ',').replace('、', ',').replace('\n', ',').split(',')
    return [p.strip(' \t') for p in parts if p.strip(' \t')]


def engine_options(values):
    """PhotoPreferences.engineOptions: what the app sends with every engine request."""
    return {'include_shared': values['includeShared'], 'recognize_content': values['recognizeContent'],
            'event_hours': values['eventHours'], 'event_kilometers': values['eventKilometers'],
            'meeting_minutes': values['meetingMinutes'], 'pet_names': pet_names(values['petNames'])}


def app_running():
    """Any PhotoDesk process: it keeps settings in memory and saves over outside changes."""
    return subprocess.run(['/usr/bin/pgrep', '-x', 'PhotoDesk'], capture_output=True).returncode == 0


def parse(key, text):
    """Validate one `settings set` value like the Settings window would allow it."""
    if key == LIBRARY_KEY:
        if not text.strip():
            return ''
        path = Path(text).expanduser().resolve()
        if path.suffix != '.photoslibrary' or not path.is_dir():
            raise ValueError('请选择一个存在的 .photoslibrary 图库；传空字符串则跟随“照片”最近打开的图库。')
        return str(path)
    if key not in DEFAULTS:
        raise ValueError(f'未知设置：{key}。可用：{", ".join([*DEFAULTS, LIBRARY_KEY])}')
    if key in FLAGS:
        lowered = text.strip().lower()
        if lowered in TRUE or lowered in FALSE:
            return lowered in TRUE
        raise ValueError(f'{key} 只接受 true 或 false。')
    if key == 'petNames':
        return text.strip()
    if key in ('appearance', 'initialTrack'):
        if text not in CHOICES[key]:
            raise ValueError(f'{key} 只接受：{"、".join(CHOICES[key])}。')
        return text
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f'{key} 需要数字。') from None
    if key in CHOICES:
        if number not in CHOICES[key]:
            raise ValueError(f'{key} 只接受：{"、".join(map(str, CHOICES[key]))}（与设置窗口的选项一致）。')
        return int(number)
    low, high, step = STEPS[key]
    if not low <= number <= high or (number - low) % step:
        raise ValueError(f'{key} 范围 {low}–{high}，步长 {step}。')
    return float(number) if key == 'thumbnailWidth' else int(number)


def save(key, value, store=None):
    """Write one setting; refuses while PhotoDesk runs (it would overwrite the change)."""
    store = store or STORE
    if os.environ.get('PHOTODESK_DEMO_ROOT') and key == LIBRARY_KEY:
        raise ValueError('当前为独立合成演示图库；退出演示后再连接自己的图库。')
    if app_running():
        raise ValueError('PhotoDesk 正在运行：设置保存在运行中的 App 里，会覆盖外部修改。'
                         '请在 App 的设置窗口（⌘,）修改，或退出 PhotoDesk 后重试。')
    if key == LIBRARY_KEY:
        store.set(LIBRARY_KEY, value or None, domain())
        return
    values, _ = load(store)
    values[key] = value
    store.set(STORAGE_KEY, json.dumps(values, ensure_ascii=False).encode(), domain())

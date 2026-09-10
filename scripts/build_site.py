"""Build a complete, allowlisted site from a verified release and real media."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ['timeline.png', 'preview.png', 'timeline.mp4', 'review.mp4', 'timeline-poster.jpg', 'review-poster.jpg']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(preview=False):
    source, output = ROOT / 'site', ROOT / 'build/site'
    manifest_file = ROOT / 'dist/release.json'
    if manifest_file.is_file():
        release = json.loads(manifest_file.read_text())
        archive = ROOT / 'dist' / release['filename']
        if digest(archive) != release['sha256'] or archive.stat().st_size != release['bytes']:
            raise SystemExit('Release archive does not match its manifest.')
    elif preview:
        info = plistlib.loads((ROOT / 'Info.plist').read_bytes())
        release = {'version': info['CFBundleShortVersionString'], 'build': '预览',
                   'bytes': 0, 'filename': 'not-released.zip', 'sha256': '发行包完成后自动生成', 'minimum_macos': '15.0'}
    else:
        raise SystemExit('Missing dist/release.json. Run scripts/release.py first.')
    if not preview and release.get('source_dirty'):
        raise SystemExit('Release source was not committed; rebuild from the reviewed commit before publishing.')
    media_root = ROOT / 'docs/demo'
    evidence_file = media_root / 'evidence.json'
    evidence = json.loads(evidence_file.read_text()) if evidence_file.is_file() else {}
    if not preview:
        if not (evidence.get('privacy_reviewed') is True and evidence.get('synthetic_inputs') is True):
            raise SystemExit('Real recordings and privacy review are required; preview placeholders cannot be published.')
        if evidence.get('recorded_version') != release['version']:
            raise SystemExit('The real media version differs from the release; inspect and recapture affected scenes.')
        expected = {f['path']: f['sha256'] for f in evidence.get('files', [])}
        for name in MEDIA:
            path = media_root / name
            if not path.is_file() or expected.get(name) != digest(path):
                raise SystemExit(f'Missing or unreviewed media: {name}')
            if path.suffix == '.mp4':
                result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_name,width,height,duration', '-of', 'json', str(path)],
                    check=True, text=True, capture_output=True)
                streams = json.loads(result.stdout).get('streams', [])
                if not streams or streams[0].get('codec_name') != 'h264' or float(streams[0].get('duration', 0)) <= 0:
                    raise SystemExit(f'Media is not a playable H.264 recording: {name}')
    if output.exists():
        shutil.rmtree(output)  # Generated site only; not source, raw media or release archive.
    (output / 'images').mkdir(parents=True)
    (output / 'media').mkdir()
    (output / 'downloads').mkdir()
    iconset = ROOT / 'build/site-icon.iconset'
    if iconset.exists():
        shutil.rmtree(iconset)
    subprocess.run(['iconutil', '-c', 'iconset', str(ROOT / 'icon/AppIcon.icns'), '-o', str(iconset)], check=True)
    shutil.copyfile(iconset / 'icon_256x256.png', output / 'images/app-icon.png')
    assets = {}
    for name in MEDIA:
        path = media_root / name
        if path.is_file():
            destination = ('images/' if path.suffix == '.png' else 'media/') + name
            shutil.copyfile(path, output / destination)
            assets[name] = destination
    def image(name, alt):
        return f'<img src="{assets[name]}" alt="{alt}" loading="lazy">' if name in assets else '<div class="media-pending">真实应用截图待采集 · 仅限本地预览</div>'
    def video(name, poster):
        if name not in assets or poster not in assets:
            return '<div class="media-pending">原生窗口操作录像待采集 · 仅限本地预览</div>'
        return f'<video controls playsinline preload="metadata" poster="{assets[poster]}"><source src="{assets[name]}" type="video/mp4">请下载视频后播放。</video>'
    values = {'VERSION': release['version'], 'BUILD': str(release['build']),
              'SIZE': f'{release["bytes"] / 1024 / 1024:.1f} MB' if release['bytes'] else '体积待发行构建',
              'MIN_MACOS': release['minimum_macos'], 'FILENAME': release['filename'], 'SHA256': release['sha256'],
              'DOWNLOAD_URL': 'downloads/' + release['filename'] if manifest_file.is_file() else '#download',
              'TIMELINE_IMAGE': image('timeline.png', 'PhotoDesk 我的时间线原生窗口，合成样例按拍摄时间和已有相册归集'),
              'PREVIEW_IMAGE': image('preview.png', 'PhotoDesk 原生图片预览窗口，显示明确标记的合成输入图像'),
              'TIMELINE_VIDEO': video('timeline.mp4', 'timeline-poster.jpg'),
              'REVIEW_VIDEO': video('review.mp4', 'review-poster.jpg'),
              'MEDIA_CAPTION': html.escape(evidence.get('caption', '真实录像尚未采集，本页只供版式预览。'))}
    for path in sorted(source.iterdir()):
        if path.suffix not in ('.html', '.css'):
            continue
        text = path.read_text()
        for key, value in values.items():
            text = text.replace('{{' + key + '}}', value)
        if re.search(r'\{\{[A-Z_]+\}\}', text):
            raise SystemExit(f'Unresolved placeholder in {path.name}')
        if preview and path.suffix == '.html':
            text = text.replace('<body>', '<body><div class="preview-banner">本地预览 · 未完成真实媒体与发布验收，不可作为正式官网发布</div>', 1)
        (output / path.name).write_text(text)
    if manifest_file.is_file():
        # Source commit is public-safe, but never expose local source paths or staging locations.
        public = {k: release[k] for k in ('product','version','build','architecture','minimum_macos','filename','sha256','bytes','signing','notarized','created_at')}
        (output / 'release.json').write_text(json.dumps(public, indent=2) + '\n')
        shutil.copyfile(archive, output / 'downloads' / archive.name)
        shutil.copyfile(ROOT / 'dist' / (archive.name + '.sha256'), output / 'downloads' / (archive.name + '.sha256'))
    notices = ROOT / 'build/THIRD_PARTY_NOTICES.txt'
    if notices.exists():
        shutil.copyfile(notices, output / 'third-party-notices.txt')
    elif not preview:
        raise SystemExit('Missing third-party notices.')
    manifest = {'schema': 1, 'product': 'PhotoDesk', 'domain': 'app-mac-photodesk.tianli.cyou',
                'preview': preview, 'version': release['version'], 'files': [
                    {'path': p.relative_to(output).as_posix(), 'sha256': digest(p), 'bytes': p.stat().st_size}
                    for p in sorted(output.rglob('*')) if p.is_file()]}
    (output / 'site-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'{"Preview" if preview else "Release site"}: {output}; {len(manifest["files"])} public files.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true')
    build(parser.parse_args().preview)

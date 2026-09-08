"""PhotoDesk's bundled engine. JSON stdin/stdout; local data never leaves the Mac."""
from __future__ import annotations

import collections
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

BASE = Path(__file__).resolve().parent
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(BASE.parent / 'vendor'))
ROOT = Path(os.environ.get('PHOTODESK_DATA_ROOT', Path.home() / 'Library/Application Support/PhotoDesk'))
os.environ['PHOTOCLI_DATA_ROOT'] = str(ROOT)
os.environ['PHOTOCLI_DOCS_DB'] = str(ROOT / 'optional-documents.db')

import yaml
from photocli import classify, lib, ocr, title, triage


def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(path)


def progress(request, text, done=0, total=0):
    token = request.get('request_id', '')
    if re.fullmatch(r'[A-Za-z0-9-]{1,64}', token):
        atomic_json(ROOT / 'progress' / f'{token}.json', {'message': text, 'done': done, 'total': total})


def config(request):
    cfg = yaml.safe_load((BASE / 'defaults.yaml').read_text())
    library = request.get('library', '').strip()
    if library:
        path = Path(library).expanduser().resolve()
        if path.suffix != '.photoslibrary' or not path.is_dir():
            raise ValueError('请选择一个存在的 .photoslibrary 图库。')
        cfg['library'] = str(path)
    return lib.Config(cfg)


def editable(photo):
    return not (photo.shared or getattr(photo, 'shared_library', False)
                or (getattr(photo, 'syndicated', False) and not getattr(photo, 'saved_to_library', False)))


def preview_path(photo):
    paths = getattr(photo, 'path_derivatives', []) or []
    # A thumbnail is for visual review only, never OCR or duplicate classification.
    for p in paths:
        if Path(p).is_file():
            return p
    p = getattr(photo, 'path', None)
    return p if p and Path(p).is_file() else ''


def item(row, photo, number, cfg):
    return dict(id=str(number), cloud_guid=row.cloud_guid, filename=row.filename,
                local_uuid=photo.uuid,
                date=row.date, action=row.action, target=row.target, note=row.note,
                preview_path=preview_path(photo), original_path=getattr(photo, 'path', None) or '', is_movie=bool(getattr(photo, 'ismovie', False)), original_title=photo.title or '',
                protected=lib.is_protected(photo, cfg) or '',
                group=row.target if row.action != 'set-title' else '标题建议')


def audit(request, cfg):
    progress(request, '正在读取图库…')
    db = lib.load_db(cfg.library)
    photos = db.photos()
    personal = [p for p in photos if editable(p)]
    years = collections.Counter(str(p.date.year) if p.date else '未知' for p in personal)
    albums = collections.Counter(a for p in personal for a in (p.albums or []))
    return dict(library=db.library_path, total=len(personal), photos=sum(p.isphoto for p in personal),
                movies=sum(p.ismovie for p in personal), favorites=sum(p.favorite for p in personal),
                live=sum(p.live_photo for p in personal), shared=len(photos)-len(personal),
                local=sum(bool(p.path and Path(p.path).is_file()) for p in personal),
                by_year=dict(sorted(years.items())), albums=dict(albums.most_common()), generated=now(),
                message=('当前系统未提供可读取的场景标签，场景分类可能不完整。' if not any(p.labels for p in personal)
                         else '个人图库已载入；共享相册及共享图库仅作只读统计。'))


def cached_ocr(photo, request, position, count):
    progress(request, f'本地识别 {position} / {count}', position, count)
    path = getattr(photo, 'path', None)
    if not path or not Path(path).is_file():
        return None, '原片未下载，未识别'
    stat = Path(path).stat()
    key = hashlib.sha256(f'{photo.cloud_guid}|{stat.st_size}|{stat.st_mtime_ns}|vision-v1'.encode()).hexdigest()
    dest = ROOT / 'ocr' / f'{key}.json'
    if dest.exists():
        return json.loads(dest.read_text())['text'], ''
    try:
        text = ocr._ocr_vision(path)
        atomic_json(dest, {'text': text, 'generated': now()})
        return text, ''
    except Exception as exc:
        # Do not expose full OCR data or image paths in logs.
        return None, f'OCR 失败（{type(exc).__name__}），需人工查看'


def build_plan(request, cfg):
    kind = request['kind']
    progress(request, '正在读取图库，生成整理建议…')
    db = lib.load_db(cfg.library)
    if kind == 'library':
        members = [p for p in db.photos() if editable(p)]
        members.sort(key=lambda p: p.date.timestamp() if p.date else 0, reverse=True)
        records = []
        for i, p in enumerate(members):
            month = p.date.strftime('%Y-%m') if p.date else '日期未知'
            row = lib.PlanRow(p.cloud_guid or '', p.original_filename or '', lib.photo_date(p),
                              'review', month, '视频' if p.ismovie else '照片')
            records.append(item(row, p, i, cfg))
        return persist_plan(kind, db.library_path, records, len(members), ['按拍摄月份浏览个人图库；可放大预览、勾选并删除。共享内容不参与删除。'])
    photos = [p for p in db.photos() if editable(p) and p.cloud_guid]
    index = {p.cloud_guid: p for p in photos}
    rows = []
    warnings = []
    examined = len(photos)
    if kind == 'classify':
        rows = [r for r in classify._build_rows(cfg) if r.cloud_guid in index]
        warnings = ['按年月、人物和场景生成建议；可以逐项取消勾选。']
    elif kind == 'title':
        # Preserve non-empty user titles; use existing generator without an external knowledge DB.
        rows = [lib.PlanRow(p.cloud_guid, p.original_filename or '', lib.photo_date(p),
                            'set-title', title._make_title(p, {}), '仅补充空标题')
                for p in photos if not p.title and title._make_title(p, {})]
        warnings = ['只为没有标题的照片补充建议，已有标题不覆盖。']
    elif kind in ('sensitive', 'triage'):
        sec = cfg.section('ocr')
        if kind == 'triage':
            candidates, _ = triage._select_candidates(cfg)
            candidates = [p for p in candidates if p.cloud_guid in index]
        else:
            candidates = [p for p in photos if ocr._is_candidate(p, set(sec['candidate_labels']), set(sec['candidate_uti']))]
        limit = int(request.get('limit', 100))
        if limit < 0 or limit > 100000:
            raise ValueError('识别数量范围无效。')
        candidates.sort(key=lambda p: p.date.timestamp() if p.date else 0, reverse=True)
        candidates = candidates[:limit] if limit else candidates
        examined = len(candidates)
        missing = errors = 0
        bucket_names = {'junk': 'PhotoDesk/文字较少·待核对', 'receipt': 'PhotoDesk/票据·保留',
                        'reimbursed': 'PhotoDesk/票据·保留', 'unsure': 'PhotoDesk/截图·待核对'}
        patterns = {name: re.compile(rx) for name, rx in sec['patterns'].items()}
        for i, p in enumerate(candidates, 1):
            text, error = cached_ocr(p, request, i, len(candidates))
            if error:
                missing += '未下载' in error
                errors += '失败' in error
            if kind == 'sensitive':
                if text is None:
                    continue
                hits = [name for name, rx in patterns.items() if rx.search(text)]
                if hits:
                    for action, target in [('add-album', '🔒敏感档案'), ('add-keyword', '🔒敏感')]:
                        rows.append(lib.PlanRow(p.cloud_guid, p.original_filename or '', lib.photo_date(p), action, target, '识别类型：' + '、'.join(hits)))
            else:
                bucket, reason = triage._classify(p, text or '', cfg, triage._months_ago(6), cfg.section('triage')['guide_keywords'])
                rows.append(lib.PlanRow(p.cloud_guid, p.original_filename or '', lib.photo_date(p),
                                        'add-album', bucket_names[bucket], error or reason))
        warnings = [f'本次检查 {examined} 项；原片未下载 {missing} 项，识别失败 {errors} 项。',
                    '识别在本机完成；缺少原片的照片不会被判断为垃圾。票据日期不能证明报销状态。']
    elif kind == 'duplicates':
        groups = collections.defaultdict(list)
        for p in photos:
            fingerprint = getattr(p, 'fingerprint', None)
            if fingerprint:
                # Original fingerprints don't describe edits or Live Photo paired videos.
                groups[(fingerprint, p.ismovie, p.live_photo)].append(p)
        for members in groups.values():
            if len(members) < 2:
                continue
            group = '相同原片指纹 · ' + str(len({r.target for r in rows}) + 1)
            for p in members:
                note = '相同原片指纹；编辑效果及 Live Photo 动态部分需人工核对'
                rows.append(lib.PlanRow(p.cloud_guid, p.original_filename or '', lib.photo_date(p), 'review', group, note))
        warnings = ['按相同原片指纹分组，不是相似照片检测。请放大核对后手动勾选删除，编辑效果及 Live Photo 动态部分可能不同。']
    else:
        raise ValueError('未知整理类型。')

    if kind in ('classify', 'sensitive', 'triage', 'title') and not any(p.labels for p in photos):
        warnings.append('当前系统的场景标签不可读：人物与年月分类可用；OCR 候选目前主要覆盖 PNG 截图。')

    # Remove existing assignments without relying on leaf album names.
    filtered = []
    for row in rows:
        p = index[row.cloud_guid]
        if row.action == 'add-keyword' and row.target in (p.keywords or []):
            continue
        if row.action == 'add-album':
            full_paths = {'/'.join([*(a.folder_names or []), a.title]) for a in (p.album_info or [])}
            if row.target in full_paths:
                continue
        filtered.append(row)
    plan = persist_plan(kind, db.library_path, [item(r, index[r.cloud_guid], i, cfg) for i, r in enumerate(filtered)], examined, warnings)
    progress(request, f'建议已生成：{len(filtered)} 项')
    return plan


def persist_plan(kind, library, records, examined, warnings, token=None):
    token = token or str(uuid.uuid4())
    path = ROOT / 'plans' / f'{token}.json'
    csv_path = path.with_suffix('.csv')
    fields = ('cloud_guid', 'filename', 'date', 'action', 'target', 'note')
    lib.write_plan([lib.PlanRow(**{k: r[k] for k in fields}) for r in records], csv_path)
    plan = dict(id=token, kind=kind, library=str(Path(library).resolve()), created=now(),
                examined=examined, warnings=warnings, csv_path=str(csv_path), rows=records)
    atomic_json(path, plan)
    return plan


def resolve_deletion_rows(plan, selected, photos, cfg):
    selected = set(selected)
    if not selected or not selected <= {r['id'] for r in plan['rows']}:
        raise ValueError('请选择当前列表中的照片。')
    cloud_index = collections.defaultdict(list)
    for p in photos:
        if p.cloud_guid:
            cloud_index[p.cloud_guid].append(p)
    local_index = {p.uuid: p for p in photos}
    result = {}
    for row in plan['rows']:
        if row['id'] not in selected:
            continue
        # Duplicate assets can share a Cloud GUID. Deletion must target the exact
        # local asset shown in the selected row, never whichever duplicate the
        # database happens to enumerate last. A missing asset cannot be replaced.
        if row.get('local_uuid'):
            p = local_index.get(row['local_uuid'])
            if p is not None and row['cloud_guid'] and p.cloud_guid != row['cloud_guid']:
                raise ValueError('所选照片标识已变化，请刷新列表后重新选择。')
        else:
            candidates = cloud_index.get(row['cloud_guid'], [])
            if len(candidates) > 1:
                raise ValueError('旧清单无法区分重复副本，请重新分析后选择。')
            p = candidates[0] if candidates else None
        if p is None or not editable(p):
            raise ValueError('部分照片已移除或变成共享内容，请刷新列表后重试。')
        result[p.uuid] = dict(uuid=p.uuid, cloud_guid=p.cloud_guid or '',
                              filename=p.original_filename or '', protected=lib.is_protected(p, cfg) or '')
    return list(result.values())


def deletion_preview(request, cfg):
    from osxphotos.utils import get_system_library_path
    plan = load_plan(request['plan_id'])
    system = get_system_library_path()
    # New macOS versions may omit the legacy SystemLibraryPath preference.
    # Native PhotoKit must still resolve EVERY exact asset UUID before showing
    # confirmation and again before deletion; missing preferences are not proof
    # that this is a different library.
    if system and str(Path(system).resolve()) != plan['library']:
        raise ValueError('App 内删除仅支持系统照片图库。其他图库请在“照片”中手动处理。')
    if cfg.library and str(Path(cfg.library).resolve()) != plan['library']:
        raise ValueError('当前图库与所选计划不一致，请刷新后重试。')
    photos = lib.load_db(plan['library']).photos()
    items = resolve_deletion_rows(plan, request['selected'], photos, cfg)
    return dict(plan_id=plan['id'], library=plan['library'], items=items)


def load_plan(token):
    if str(uuid.UUID(token)) != token:
        raise ValueError('计划标识无效。')
    return json.loads((ROOT / 'plans' / f'{token}.json').read_text())


def validate_selection(plan, selected, photos, cfg):
    selected = set(selected)
    known = {r['id'] for r in plan['rows']}
    if not selected or not selected <= known:
        raise ValueError('请选择当前计划中的有效项目。')
    index = {p.cloud_guid: p for p in photos if editable(p) and p.cloud_guid}
    chosen = [r for r in plan['rows'] if r['id'] in selected]
    for row in chosen:
        if row['action'] not in ('add-album', 'add-keyword', 'set-title'):
            raise ValueError('此清单只支持查看，不能写入。')
        p = index.get(row['cloud_guid'])
        if p is None:
            raise ValueError('照片已移除或共享状态已改变，请重新生成计划。')
        if row['action'] == 'set-title' and (p.title or '') != row['original_title']:
            raise ValueError('照片标题已被修改，请重新生成计划。')
        if row['target'] == '待清理候选' and lib.is_protected(p, cfg):
            raise ValueError('照片现在已受保护，请重新生成计划。')
    return chosen, index


def apply_plan(request, cfg):
    from osxphotos.utils import get_last_library_path
    plan = load_plan(request['plan_id'])
    if cfg.library and str(Path(cfg.library).resolve()) != plan['library']:
        raise ValueError('当前选择的图库与计划不一致，请重新生成。')
    actual = get_last_library_path()
    if not actual or str(Path(actual).resolve()) != plan['library']:
        raise ValueError('请先在“照片”中打开生成计划时的图库，再重试。')
    photos = lib.load_db(plan['library']).photos()
    rows, index = validate_selection(plan, request['selected'], photos, cfg)
    if not request.get('confirmed', False):
        return {'message': f'预检通过：{len(rows)} 项，未写入图库。', 'changed': 0, 'checked': len(rows)}
    receipt_id = str(uuid.uuid4())
    receipt_path = ROOT / 'history' / f'{receipt_id}.json'
    receipt = {'id': receipt_id, 'plan_id': plan['id'], 'created': now(), 'state': 'running',
               'library': plan['library'], 'completed': [], 'selected': rows}
    atomic_json(receipt_path, receipt)
    try:
        from photoscript import Photo
        from osxphotos.photosalbum import PhotosAlbum
        groups = collections.defaultdict(list)
        for row in rows:
            groups[(row['action'], row['target'])].append(row)
        done = 0
        for (action, target), members in groups.items():
            progress(request, f'正在写入 {done} / {len(rows)}', done, len(rows))
            if action == 'add-album':
                album = PhotosAlbum(target, split_folder='/')
                before = {p.uuid for p in album.photos()}
                todo = [r for r in members if index[r['cloud_guid']].uuid not in before]
                # Avoid PhotosAlbum.update's catch-and-skip behavior.
                live = [Photo(index[r['cloud_guid']].uuid) for r in todo]
                for offset in range(0, len(live), 20):
                    album.album.add(live[offset:offset + 20])
                after = {p.uuid for p in album.photos()}
                if not all(index[r['cloud_guid']].uuid in after for r in members):
                    raise RuntimeError('相册写入后的核对未通过，部分项目可能已完成。')
            else:
                for row in members:
                    photo = Photo(index[row['cloud_guid']].uuid)
                    if action == 'set-title':
                        # Recheck live value immediately before changing it.
                        if (photo.title or '') != row['original_title']:
                            raise ValueError('照片标题在预检后发生变化，已停止。')
                        photo.title = target
                        if photo.title != target:
                            raise RuntimeError('标题写入后核对失败。')
                    else:
                        photo.keywords = sorted(set(photo.keywords or []) | {target})
                        if target not in (photo.keywords or []):
                            raise RuntimeError('关键词写入后核对失败。')
                    receipt['completed'].append(row['id'])
                    atomic_json(receipt_path, receipt)
            if action == 'add-album':
                receipt['completed'].extend(r['id'] for r in members)
            done += len(members)
            atomic_json(receipt_path, receipt)
        receipt['state'] = 'complete'
        atomic_json(receipt_path, receipt)
        return {'message': f'已完成并核对 {done} 项整理操作。', 'changed': done, 'receipt_path': str(receipt_path)}
    except Exception as exc:
        receipt['state'] = 'partial_or_failed'
        receipt['error'] = str(exc)
        atomic_json(receipt_path, receipt)
        raise RuntimeError(f'写入中止，可能已有部分完成。记录：{receipt_path}\n{exc}') from exc


def main():
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            command = request.get('command', 'ping')
            if command == 'ping':
                import osxphotos
                data = {'message': '引擎就绪', 'version': osxphotos.__version__, 'data_root': str(ROOT)}
            elif command == 'ocr-probe':
                from PIL import Image, ImageDraw, ImageFont
                path = ROOT / 'diagnostics' / 'ocr-probe.png'
                path.parent.mkdir(parents=True, exist_ok=True)
                im = Image.new('RGB', (1200, 300), 'white')
                draw = ImageDraw.Draw(im)
                font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 64)
                draw.text((40, 50), 'Invoice 2026-08-01', font=font, fill='black')
                draw.text((40, 150), 'Total USD 100.00', font=font, fill='black')
                im.save(path)
                text = ocr._ocr_vision(str(path))
                if 'invoice' not in text.lower() or '100' not in text:
                    raise RuntimeError('内置 OCR 样本核对失败。')
                data = {'message': 'Apple Vision OCR 合成样本核对通过'}
            elif command in ('journey-snapshot', 'journey-enrich'):
                import journey
                data = journey.run(request, cfg=config(request), api=sys.modules[__name__])
            elif command == 'history':
                entries = []
                for path in sorted((ROOT / 'plans').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
                    p = json.loads(path.read_text())
                    entries.append({k: p[k] for k in ('id', 'kind', 'created', 'library') } | {'count': len(p['rows'])})
                data = {'entries': entries}
            elif command == 'load-plan':
                data = load_plan(request['plan_id'])
            else:
                cfg = config(request)
                if command == 'audit':
                    data = audit(request, cfg)
                elif command == 'plan':
                    data = build_plan(request, cfg)
                elif command == 'apply':
                    data = apply_plan(request, cfg)
                elif command == 'delete-preview':
                    data = deletion_preview(request, cfg)
                else:
                    raise ValueError('未知操作。')
        print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False))
    except Exception as exc:
        text = str(exc)
        if isinstance(exc, PermissionError) or 'authorization' in text.lower() or 'not authorized' in text.lower():
            text = '无法访问照片。请在系统设置 → 隐私与安全性 → 完全磁盘访问权限中启用 PhotoDesk，然后重新打开。'
        print(json.dumps({'ok': False, 'error': text}, ensure_ascii=False))


if __name__ == '__main__':
    main()

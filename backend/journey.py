"""Local, incremental photo connections. No library mutations or network calls."""
from __future__ import annotations

import collections
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid
import bisect

VERSION = 'journey-2'
MEETING = re.compile(r'会议|会场|议程|研讨|汇报|座谈|评审|培训|讲座|conference|meeting|agenda', re.I)
WORK = re.compile(r'工程|项目|施工|设计|报告|合同|投标|验收|水利|水库|图纸|工作')
CAT_ALBUM = re.compile(r'猫|cats?|大白', re.I)


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def stamp(p):
    path = p.path or ''
    stat = Path(path).stat() if path and Path(path).is_file() else None
    return digest((VERSION, p.uuid, p.fingerprint, str(p.date_modified),
                   stat.st_size if stat else 0, stat.st_mtime_ns if stat else 0))


def visual(path):
    import Vision
    from Foundation import NSURL
    import Quartz
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
    image = Quartz.CGImageSourceCreateThumbnailAtIndex(source, 0, {
        Quartz.kCGImageSourceCreateThumbnailFromImageAlways: True,
        Quartz.kCGImageSourceThumbnailMaxPixelSize: 640,
        Quartz.kCGImageSourceCreateThumbnailWithTransform: True})
    if image is None:
        raise ValueError('No readable preview')
    request = Vision.VNClassifyImageRequest.alloc().init()
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(str(error))
    return {str(r.identifier()): round(float(r.confidence()), 4)
            for r in (request.results() or []) if float(r.confidence()) >= .12}


def meaning(p, insight, pet_names):
    persons = sorted(set(p.persons or []) - {'_UNKNOWN_'})
    albums = p.albums or []
    labels = insight.get('labels', {})
    text = insight.get('text', '')
    evidence = []
    cats = sorted(set(persons) & pet_names)
    is_cat = bool(cats or any(CAT_ALBUM.search(a) for a in albums)
                  or max(labels.get('cat', 0), labels.get('adult_cat', 0)) >= .55)
    if cats:
        evidence.append('已命名宠物：' + '、'.join(cats))
    elif any(CAT_ALBUM.search(a) for a in albums):
        evidence.append('来自已有猫相册')
    elif is_cat:
        evidence.append('本机图像识别为猫；个体未确认')
    meeting_text = MEETING.search(' '.join([p.title or '', *albums, text]))
    is_meeting = bool(meeting_text or labels.get('conference', 0) >= .55)
    is_work = bool(is_meeting or WORK.search(' '.join([p.title or '', *albums, text])))
    if meeting_text:
        evidence.append('会议线索：' + meeting_text.group(0))
    elif is_meeting:
        evidence.append('图像显示会议场景（待核对）')
    elif is_work:
        evidence.append('文字含项目或工作线索')
    if persons:
        evidence.append('人物：' + '、'.join(persons))
    place = ''
    if p.place:
        place = p.place.name or ''
    if place:
        evidence.append('拍摄地点：' + place)
    screenshot = bool(getattr(p, 'screenshot', False) or labels.get('screenshot', 0) >= .65)
    document = bool(labels.get('document', 0) >= .55)
    if is_cat:
        category, title = 'cats', ('、'.join(cats) if cats else '猫咪') + '的日常'
    elif is_meeting:
        category, title = 'meetings', '会议与交流（自动归集）'
        headings = [line.strip() for line in text.splitlines() if 5 <= len(line.strip()) <= 40
                    and MEETING.search(line) and not re.search(r'\d{7,}|@', line)]
        if headings:
            title = headings[0] + '（文字线索）'
    elif is_work:
        category, title = 'work', '项目与工作记录'
    elif document:
        category, title = 'documents', '文档与资料'
    elif screenshot:
        category, title = 'screenshots', '截图与信息留存'
    elif persons:
        category, title = 'life', '与' + '、'.join([n for n in persons if n not in pet_names][:3]) + '的片段'
    elif labels.get('food', 0) >= .65:
        category, title = 'life', '餐桌上的记忆'
    else:
        category, title = 'life', (place + '的片段') if place else '生活片段'
    tracks = ['全部', '个人时间线']
    if is_cat:
        tracks += ['猫时间线'] + ['猫 · ' + n for n in cats]
    if is_meeting:
        tracks += ['会议与工作']
    elif is_work:
        tracks += ['会议与工作']
    elif category in ('documents', 'screenshots'):
        tracks += ['资料与截图']
    tracks += ['人物 · ' + n for n in persons if n not in pet_names]
    return dict(category=category, title=title, tracks=tracks, people=persons,
                place=place, evidence=evidence, cats=cats)


def distance(a, b):
    if not a or not b or None in a or None in b:
        return 0
    la, lo, lb, lob = map(math.radians, (*a, *b))
    x = math.sin((lb-la)/2)**2 + math.cos(la)*math.cos(lb)*math.sin((lob-lo)/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(x)))


def connect_meeting_material(entries):
    anchors = sorted([(p.date.timestamp(), p, m) for p, m in entries if p.date and m['category'] == 'meetings'], key=lambda a: a[0])
    times = [a[0] for a in anchors]
    for p, m in entries:
        if not p.date or m['category'] not in ('work', 'documents', 'screenshots') or not anchors:
            continue
        position = bisect.bisect_left(times, p.date.timestamp())
        for _, anchor, meaning in sorted(anchors[max(0, position-1):position+1], key=lambda a: abs(a[0]-p.date.timestamp())):
            if abs((p.date-anchor.date).total_seconds()) <= 90*60 and p.date.date() == anchor.date.date() and distance(p.location, anchor.location) <= 1:
                m['category'] = 'meetings'; m['title'] = meaning['title']
                m['tracks'] = list(dict.fromkeys(m['tracks'] + ['会议与工作']))
                m['evidence'].append('关联同日 90 分钟内的会议线索（时间关联，待核对）')
                break
    return entries


def event_buckets(entries):
    """Same local day, subject, <= 3 h gap, <= 8 km. No invented event names."""
    buckets = []
    last = {}
    for p, m in sorted(entries, key=lambda entry: entry[0].date.timestamp() if entry[0].date else 0):
        key = (p.date.strftime('%Y-%m-%d') if p.date else p.uuid,
               m['category'], tuple(m['cats']))
        bucket = last.get(key)
        if bucket:
            previous = bucket[-1][0]
            gap = (p.date - previous.date).total_seconds() if p.date and previous.date else float('inf')
            if gap > 3 * 3600 or distance(previous.location, p.location) > 8:
                bucket = None
        if bucket is None:
            bucket = []; buckets.append(bucket); last[key] = bucket
        bucket.append((p, m))
    return sorted(buckets, key=lambda b: b[-1][0].date.timestamp() if b[-1][0].date else 0, reverse=True)


def recommend_duplicate(p, keeper, hashes, protected):
    return (p.uuid != keeper.uuid and p.uuid in hashes and hashes.get(keeper.uuid) == hashes[p.uuid]
            and not protected and not p.hasadjustments and not keeper.hasadjustments
            and not p.ismovie and not p.live_photo and not getattr(p, 'hidden', False)
            and p.date == keeper.date and p.location == keeper.location
            and set(p.albums or []) <= set(keeper.albums or [])
            and set(p.keywords or []) <= set(keeper.keywords or [])
            and set(p.persons or []) <= set(keeper.persons or [])
            and (not p.title or p.title == keeper.title)
            and (not getattr(p, 'description', '') or p.description == getattr(keeper, 'description', '')))


def duplicates(photos, api, cfg, connection):
    groups = collections.defaultdict(list)
    for p in photos:
        if api.editable(p) and p.fingerprint:
            groups[(p.fingerprint, p.ismovie, p.live_photo)].append(p)
    records = []; recommended = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda p: (not bool(api.lib.is_protected(p, cfg)),
                                   not bool(p.hasadjustments), -len(p.albums or []),
                                   -(p.original_filesize or 0), p.uuid))
        keeper = members[0]
        group = '重复组 · ' + keeper.uuid[:8]
        hashes = {}
        for p in members:
            if p.path and Path(p.path).is_file() and not p.ismovie and not p.live_photo and not p.hasadjustments:
                key = 'hash:' + stamp(p)
                cached = connection.execute('SELECT value FROM cache WHERE key=?', (key,)).fetchone()
                if cached:
                    hashes[p.uuid] = json.loads(cached[0])
                else:
                    with open(p.path, 'rb') as f:
                        hashes[p.uuid] = hashlib.file_digest(f, 'sha256').hexdigest()
                    connection.execute('INSERT OR REPLACE INTO cache VALUES (?,?)', (key, json.dumps(hashes[p.uuid])))
        for p in members:
            redundant = recommend_duplicate(p, keeper, hashes, api.lib.is_protected(p, cfg))
            note = ('建议删除：文件内容完全相同，保留副本含已有相册及标记' if redundant else
                    '建议保留：优先收藏、已有编辑及分类更完整的副本' if p == keeper else
                    '需逐张核对：含独立标记、编辑、动态内容或缺少原片，不预选删除')
            r = api.item(api.lib.PlanRow(p.cloud_guid or '', p.original_filename or '', api.lib.photo_date(p),
                                        'review', group, note), p, p.uuid, cfg)
            r['group'] = group; r['recommended'] = redundant
            records.append(r)
            if redundant:
                recommended.append(r['id'])
    plan = api.persist_plan('duplicates', str(cfg.library), records, len(photos),
                            ['已自动比较原片指纹；仅字节一致且保留副本覆盖相册与标记的静态照片预选删除。Live Photo、视频和编辑版本留给你核对。'],
                            token=str(uuid.uuid5(uuid.NAMESPACE_URL, str(cfg.library) + '/journey-duplicates')))
    return plan


def run(request, cfg, api):
    db = api.lib.load_db(cfg.library)
    cfg.raw['library'] = str(db.library_path)
    photos = db.photos()
    library_key = digest(cfg.library)
    folder = api.ROOT / 'journey' / library_key
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / 'index.sqlite', timeout=30)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    cache = dict(connection.execute('SELECT key,value FROM cache'))
    keys = {p.uuid: stamp(p) for p in photos}
    pending = [p for p in photos if keys[p.uuid] not in cache]
    pending.sort(key=lambda p: p.date.timestamp() if p.date else 0, reverse=True)
    if request['command'] == 'journey-enrich':
        for p in pending[:max(1, min(24, int(request.get('limit', 12))))]:
            insight = {'labels': {}, 'text': '', 'state': 'complete'}
            path = api.preview_path(p)
            if not path:
                insight['state'] = 'unavailable'
            else:
                try:
                    insight['labels'] = visual(path)
                    labels = insight['labels']
                    if not p.ismovie and (p.uti == 'public.png' or labels.get('document', 0) >= .3 or labels.get('conference', 0) >= .3):
                        text, error = api.cached_ocr(p, request, 0, 0)
                        insight['text'] = text or ''
                        if error:
                            insight['state'] = 'partial'
                except Exception as exc:
                    insight['state'] = 'failed'; insight['error'] = type(exc).__name__
            value = json.dumps(insight, ensure_ascii=False)
            connection.execute('INSERT OR REPLACE INTO cache VALUES (?,?)', (keys[p.uuid], value))
            connection.commit(); cache[keys[p.uuid]] = value
    pet_names = set(cfg.section('classify').get('pet_faces', []))
    entries = []; complete = unavailable = failed = 0
    for p in photos:
        insight = json.loads(cache.get(keys[p.uuid], '{}'))
        if insight:
            complete += 1
            unavailable += insight.get('state') in ('unavailable', 'partial')
            failed += insight.get('state') == 'failed'
        entries.append((p, meaning(p, insight, pet_names)))
    records = []; events = []
    for bucket in event_buckets(connect_meeting_material(entries)):
        first, m = bucket[0]; last = bucket[-1][0]
        eid = digest('|'.join(sorted(p.uuid for p, _ in bucket)))[:20]
        date = api.lib.photo_date(first)
        title = m['title']
        label = date + ' · ' + title + ' · ' + eid[:4]
        tracks = sorted({t for _, info in bucket for t in info['tracks']})
        evidence = list(dict.fromkeys(e for _, info in bucket for e in info['evidence']))[:5]
        related = []
        for p, info in reversed(bucket):
            r = api.item(api.lib.PlanRow(p.cloud_guid or '', p.original_filename or '', api.lib.photo_date(p),
                                        'review', title, '；'.join(info['evidence']) or '按拍摄时间归集，内容识别在后台补充'), p, p.uuid, cfg)
            r['group'] = label; r['read_only'] = not api.editable(p)
            records.append(r); related.append(r)
        events.append(dict(id=eid, title=title, group=label, date=date, end_date=api.lib.photo_date(last),
                           count=len(bucket), tracks=tracks, people=sorted({n for _, info in bucket for n in info['people']}),
                           place=m['place'], evidence=evidence, cover=related[0]))
    plan = api.persist_plan('journey', cfg.library, records, len(photos),
                            ['按拍摄时间、人物、已有相册及本机内容识别自动联系；同日、同主题且间隔不超过 3 小时、位置不超过 8 公里的照片聚合为片段。共享内容可浏览，不参与删除。'],
                            token=str(uuid.uuid5(uuid.NAMESPACE_URL, cfg.library + '/journey')))
    duplicate_plan = duplicates(photos, api, cfg, connection)
    connection.commit(); connection.close()
    result = dict(library=cfg.library, generated=api.now(), total=len(photos), analyzed=complete,
                  pending=len(photos)-complete, unavailable=unavailable, failed=failed,
                  events=events, plan=plan, duplicates=duplicate_plan,
                  albums=len(db.albums), tracks=sorted({t for e in events for t in e['tracks']}))
    api.atomic_json(folder / 'latest.json', result)
    return result

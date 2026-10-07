"""photodesk agent commands: what a person sees and does in the PhotoDesk window, as commands.

Every command runs the app's own engine (bridge.handle and journey) with the app's saved settings,
so the window and the CLI read and write the same timeline cache, plans, records and settings.
Deleting photos stays in the app (PhotoKit plus the system confirmation); `delete-check` stops
right before it. Writes to Apple Photos need an explicit --confirm (or the old --apply names).
"""
from __future__ import annotations

import collections
import contextlib
import functools
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import uuid

import click

API = None  # the running bridge module; install() sets it
KINDS = ('library', 'classify', 'triage', 'sensitive', 'title')
JSON_HELP = '输出一个 JSON 对象 {"ok": true, ...}；失败时 {"ok": false, "error": ...} 并以 1 退出'
PERMISSION = '无权读取照片或保存数据，请给当前终端完全磁盘访问权限。'


def install(group, api):
    """Add the agent commands to the photodesk group (replacing the old names they absorb)."""
    global API
    API = api
    for command in COMMANDS:
        group.add_command(command)


def engine():
    if API is None:
        raise click.ClickException('引擎未初始化，请通过 photodesk 命令运行。')
    return API


# ---------------- output and errors ----------------
def friendly(exc):
    if isinstance(exc, click.ClickException):
        return ' '.join(exc.format_message().splitlines())
    if isinstance(exc, PermissionError) or (API is not None and API.permission_denied(exc)):
        return PERMISSION
    text = ' '.join(str(exc).split())
    if isinstance(exc, (ValueError, RuntimeError)) and text:
        return text
    return f'操作未完成（{type(exc).__name__}）：{text}' if text else f'操作未完成（{type(exc).__name__}）。'


def execute(name, as_json, work):
    """Run work() -> (payload, lines); print JSON or text; exit 1 when it fails."""
    try:
        with contextlib.redirect_stdout(sys.stderr):  # library code must not pollute the JSON
            payload, lines = work()
    except click.exceptions.Exit:
        raise
    except Exception as exc:
        message = friendly(exc)
        if as_json:
            click.echo(json.dumps({'ok': False, 'command': name, 'error': message}, ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(message) from exc
    ok = bool(payload.pop('ok', True))
    if as_json:
        click.echo(json.dumps({'ok': ok, 'command': name, **payload}, ensure_ascii=False, default=str))
    else:
        for line in lines:
            click.echo(line)
    if not ok:
        raise click.exceptions.Exit(1)


def agent(name, label=None, **settings):
    """A click command with --json and the shared error handling."""
    def decorate(fn):
        @functools.wraps(fn)
        def callback(as_json, **options):
            execute(label or name, as_json, lambda: fn(**options))
        callback = click.option('--json', 'as_json', is_flag=True, help=JSON_HELP)(callback)
        return click.command(name, **settings)(callback)
    return decorate


def library_option(fn):
    return click.option('--library', default=None, metavar='PATH',
                        help='.photoslibrary 路径；默认与 App 相同（App 里选的图库，否则“照片”最近打开的图库）')(fn)


def selection_options(fn):
    for option in reversed((
        click.option('--select', 'ids', multiple=True, metavar='ID[,ID…]', help='计划中的行号（plan-show 的 id）；可重复'),
        click.option('--select-group', 'groups', multiple=True, metavar='NAME', help='整组选择（plan-show 的 groups）；可重复'),
        click.option('--select-all', 'everything', is_flag=True, help='选择全部可操作项（同 ⌘A）'),
    )):
        fn = option(fn)
    return fn


# ---------------- the app's context: library, settings, requests ----------------
def resolve_library(explicit):
    """(path, source): --library, else an explicit --config library, else what the app uses."""
    if explicit:
        return explicit, 'option'
    root = click.get_current_context().find_root()
    config_path = (root.obj or {}).get('config_path')
    if config_path:
        from photocli import lib
        configured = lib.load_config(config_path).library
        if configured:
            return configured, 'config'
    if os.environ.get('PHOTODESK_DEMO_ROOT'):
        return '', 'demo'
    import preferences
    return preferences.library()


def request(command, library, **extra):
    """PhotoDeskModel.request(): the command, the library and the app's engine options."""
    import preferences
    values, _ = preferences.load()
    return {'command': command, 'library': library, 'settings': preferences.engine_options(values), **extra}


def run_engine(command, library=None, **extra):
    return engine().handle(request(command, library or '', **extra))


def load_plan(plan_id):
    return engine().handle({'command': 'load-plan', 'plan_id': plan_id})


def summary(plan):
    rows = plan['rows']
    return dict(id=plan['id'], kind=plan['kind'], library=plan['library'], created=plan['created'],
                examined=plan['examined'], warnings=plan['warnings'], csv_path=plan['csv_path'],
                row_count=len(rows), groups=dict(collections.Counter(r.get('group', '') for r in rows)),
                actions=dict(collections.Counter(r['action'] for r in rows)))


def matches(row, search):
    return not search or any(search.lower() in str(row.get(k) or '').lower()
                             for k in ('filename', 'target', 'note', 'date'))


def page(items, limit, offset):
    return items[offset:] if limit == 0 else items[offset:offset + limit]


def row_line(r):
    marks = ' [只读]' if r.get('read_only') else (' [建议删除]' if r.get('recommended') else '')
    return f"  {r['id']} · {r['date']} · {r['filename']} · {r['action']} {r['target']}{marks}"


def timeline_cache(library):
    """(latest.json data, folder) for the library, the way journey.run stored it.

    With no library (following the system library, like the app), it is the library Photos opened
    last, which is what the engine's refresh would read; a cache left from another library is not
    shown in its place.
    """
    import journey
    root = engine().ROOT / 'journey'
    following = not library and not os.environ.get('PHOTODESK_DEMO_ROOT')
    if following:
        import preferences
        library = preferences.photos_last_library() or ''
    wanted = str(Path(library).expanduser().resolve()) if library else None
    if wanted:
        for key in dict.fromkeys((library, wanted)):
            path = journey.cache_folder(engine(), key) / 'latest.json'
            if path.is_file():
                return json.loads(path.read_text()), path.parent
    found = []
    for path in sorted(root.glob('*/latest.json')):
        data = json.loads(path.read_text())
        if wanted is None or str(Path(data['library']).resolve()) == wanted:
            found.append((data, path.parent))
    if not found and following and wanted and any(root.glob('*/latest.json')):
        raise ValueError(f'时间线缓存属于其他图库；“照片”最近打开的是 {wanted}。'
                         '先运行 photodesk refresh 为它建立时间线（或打开 PhotoDesk）。')
    if not found:
        raise ValueError('还没有这个图库的时间线缓存；先运行 photodesk refresh（或打开 PhotoDesk）。')
    # Demo data, or Photos has no last-opened library on record: the newest cache.
    return max(found, key=lambda f: f[0]['generated'])


def journey_header(data):
    status = (f"已联系 {data['total']} 张照片 · 内容识别 {data['analyzed']} / {data['total']}"
              if data['pending'] else
              f"全部照片已归集；内容识别缺失 {data['unavailable']} 项，失败 {data['failed']} 项")
    return dict(library=data['library'], generated=data['generated'], total=data['total'],
                analyzed=data['analyzed'], pending=data['pending'], unavailable=data['unavailable'],
                failed=data['failed'], albums=data['albums'], tracks=data['tracks'],
                event_count=len(data['events']), plan_id=data['plan']['id'],
                duplicates_plan_id=data['duplicates']['id'], status=status)


# ---------------- 图库、时间线、重复 ----------------
@agent('audit')
@click.option('--details', is_flag=True, help='附带画像：已编辑、含 GPS、文件类型、场景标签与人物 Top（含人名）')
@library_option
def audit(details, library):
    """图库概览（同 App“图库概览”）：个人照片与视频、收藏、Live、共享只读数、本地原片、年份与相册。只读。"""
    path, _ = resolve_library(library)
    data = run_engine('audit', path, details=details)
    lines = [f"图库：{data['library']}",
             f"个人 {data['total']} 项（照片 {data['photos']} / 视频 {data['movies']}） · 收藏 {data['favorites']} · "
             f"Live {data['live']} · 本地原片 {data['local']} · 共享只读 {data['shared']}",
             '按年：' + '，'.join(f'{y} {n}' for y, n in data['by_year'].items()),
             f"现有相册 {len(data['albums'])} 个", data['message']]
    if details:
        lines.append(f"已编辑 {data['edited']} · 含 GPS {data['with_gps']} · 类型 {len(data['by_type'])} 种")
    return data, lines


@agent('timeline')
@click.option('--track', default='全部', show_default=True,
              help='时间线：全部、个人时间线、猫时间线、会议与工作、资料与截图、人物 · 名字、猫 · 名字')
@click.option('--search', default='', help='在片段标题、日期、地点、人物与线索中搜索（同 App 的片段搜索）')
@click.option('--event', 'event_id', default=None, metavar='EVENT_ID', help='列出一个片段里的照片（同“查看片段”）')
@click.option('--limit', type=click.IntRange(0), default=60, show_default=True, help='最多列出的片段或照片；0 = 全部')
@click.option('--offset', type=click.IntRange(0), default=0, help='跳过前 N 个（同“显示更早的片段”）')
@library_option
def timeline(track, search, event_id, limit, offset, library):
    """我的时间线：读取 App 已生成的片段与识别进度（只读，不重建；重建用 refresh）。"""
    path, _ = resolve_library(library)
    data, _ = timeline_cache(path)
    header = journey_header(data)
    rows = data['plan']['rows']
    selectable = collections.Counter(r['group'] for r in rows if not r.get('read_only'))
    if event_id:
        event = next((e for e in data['events'] if e['id'] == event_id), None)
        if event is None:
            raise ValueError(f'时间线里没有片段 {event_id}；用 photodesk timeline 查看片段 ID。')
        members = [r for r in rows if r['group'] == event['group']]
        shown = page(members, limit, offset)
        payload = dict(header, event={k: v for k, v in event.items() if k != 'cover'},
                       row_count=len(members), selectable=selectable[event['group']], rows=shown)
        lines = [f"{event['date']} · {event['title']} · {len(members)} 张（可操作 {selectable[event['group']]}）"]
        lines += [row_line(r) for r in shown]
        return payload, lines
    needle = search.lower()
    events = [e for e in data['events'] if (track == '全部' or track in e['tracks']) and
              (not needle or any(needle in str(v).lower()
                                 for v in [e['title'], e['date'], e['place'], *e['people'], *e['evidence']]))]
    shown = [dict(e, selectable=selectable[e['group']]) for e in page(events, limit, offset)]
    payload = dict(header, track=track, search=search, matched=len(events), offset=offset, events=shown)
    lines = [header['status'], f"生成于 {header['generated']}；片段 {header['event_count']}，当前筛选 {len(events)}",
             *(f"  {e['id']} · {e['date']} · {e['title']} · {e['count']} 张" + (f" · {e['place']}" if e['place'] else '')
               for e in shown)]
    return payload, lines


@agent('refresh')
@click.option('--enrich', is_flag=True, help='继续做本机内容识别（Vision/OCR），直到没有待识别项或达到 --max-batches')
@click.option('--batch', type=click.IntRange(1, 24), default=None, help='每批识别数量；默认 App 设置（6/12/24）')
@click.option('--max-batches', type=click.IntRange(0), default=0, help='最多识别批数；0 = 直到完成')
@click.option('--retry-failed', is_flag=True, help='先清除识别失败的缓存再识别（同“重试失败的识别”）')
@library_option
def refresh(enrich, batch, max_batches, retry_failed, library):
    """刷新图库与时间线（同 ⌘R）：只写 PhotoDesk 自己的索引、计划与缓存，不改“照片”。"""
    import preferences
    path, _ = resolve_library(library)
    values, _ = preferences.load()
    batch = batch or values['batchSize']

    def step(command, retry):
        # 'saved': compare with the stored result and skip rewriting ~13 MB when nothing changed.
        return run_engine(command, path, limit=batch, options=preferences.engine_options(values),
                          retry_failed=retry, previous_digest='saved')

    data = step('journey-snapshot', retry_failed)
    unchanged = bool(data.get('unchanged'))
    batches, note = 0, ''
    if enrich and not values['recognizeContent']:
        note = '设置里已关闭内容识别，未做识别。'
    while enrich and values['recognizeContent'] and data['pending'] and (not max_batches or batches < max_batches):
        before = data['pending']
        data = step('journey-enrich', False)
        batches += 1
        unchanged = unchanged and bool(data.get('unchanged'))
        click.echo(f"内容识别 {data['analyzed']} / {data['total']}", err=True)
        if data['pending'] >= before:
            note = '本批没有减少待识别项，已停止。'
            break
    payload = dict(journey_header(data), unchanged=unchanged, batches=batches, batch_size=batch)
    if note:
        payload['note'] = note
    lines = [payload['status'], f"片段 {payload['event_count']} · 重复建议计划 {payload['duplicates_plan_id']}",
             '结果与上次相同，未重写文件。' if unchanged else f"已更新时间线（生成于 {payload['generated']}）。"]
    if data['pending'] and not enrich:
        lines.append(f"还有 {data['pending']} 项待识别；加 --enrich 继续（App 打开时也会在后台完成）。")
    return payload, lines + ([note] if note else [])


@agent('duplicates')
@click.option('--recommended-only', is_flag=True, help='只列建议删除的副本')
@library_option
def duplicates(recommended_only, library):
    """重复核对：自动比对出的重复组、建议保留的副本与建议删除项（读时间线缓存，只读）。"""
    import preferences
    path, _ = resolve_library(library)
    data, _ = timeline_cache(path)
    plan = data['duplicates']
    groups = collections.OrderedDict()
    for r in plan['rows']:
        groups.setdefault(r['group'], []).append(r)
    listed = [dict(group=name, keeper=members[0]['id'],
                   rows=[r for r in members if r.get('recommended') or not recommended_only])
              for name, members in groups.items()]
    listed = [g for g in listed if g['rows']]
    recommended = [r['id'] for r in plan['rows'] if r.get('recommended')]
    payload = dict(plan_id=plan['id'], library=plan['library'], generated=data['generated'],
                   group_count=len(groups), row_count=len(plan['rows']), recommended=recommended,
                   preselect=preferences.load()[0]['preselectDuplicates'], warnings=plan['warnings'], groups=listed)
    lines = [f"重复组 {len(groups)} 个，共 {len(plan['rows'])} 张；建议删除 {len(recommended)} 张（计划 {plan['id']}）"]
    for g in listed:
        lines.append(f"{g['group']}（保留 {g['keeper']}）")
        lines += [row_line(r) for r in g['rows']]
    lines.append('删除前核对：photodesk delete-check --recommended；删除只能在 PhotoDesk 里确认。')
    return payload, lines


@agent('photos')
@click.option('--month', default=None, metavar='YYYY-MM', help='只看某月（或“日期未知”）')
@click.option('--search', default='', help='在文件名、月份、日期与说明中搜索')
@click.option('--limit', type=click.IntRange(0), default=60, show_default=True, help='最多列出几项；0 = 全部')
@click.option('--offset', type=click.IntRange(0), default=0)
@library_option
def photos(month, search, limit, offset, library):
    """全部照片：按拍摄月份倒序浏览个人照片与视频（只读，不保存计划；要核对删除请用 plan library）。"""
    path, _ = resolve_library(library)
    plan = run_engine('plan', path, kind='library', persist=False)
    rows = [r for r in plan['rows'] if (not month or r['group'] == month) and matches(r, search)]
    shown = page(rows, limit, offset)
    months = dict(collections.Counter(r['group'] for r in plan['rows']))
    payload = dict(library=plan['library'], total=len(plan['rows']), months=months, month=month,
                   search=search, matched=len(rows), offset=offset, rows=shown, plan_id=None)
    return payload, [f"个人照片与视频 {len(plan['rows'])} 项，筛选后 {len(rows)} 项", *map(row_line, shown)]


# ---------------- 计划、写入、删除前核对 ----------------
def make_plan(kind, limit, request_id, library, out_path=None):
    path, _ = resolve_library(library)
    extra = {'kind': kind, 'limit': limit}
    if request_id or kind in ('triage', 'sensitive'):
        extra['request_id'] = request_id or str(uuid.uuid4())
        click.echo(f"进度：photodesk progress {extra['request_id']}", err=True)
    plan = run_engine('plan', path, **extra)
    payload = summary(plan)
    if out_path:
        shutil.copyfile(plan['csv_path'], out_path)
        payload['csv_copy'] = str(Path(out_path).resolve())
    lines = [f"已生成 {kind} 计划 {plan['id']}：{len(plan['rows'])} 项，尚未写入“照片”",
             *(f"  {g}：{n}" for g, n in list(payload['groups'].items())[:20]), *plan['warnings'],
             f"查看：photodesk plan-show {plan['id']}；写入：photodesk apply {plan['id']} --select-all（加 --confirm 才写）"]
    return payload, lines


@agent('plan')
@click.argument('kind', type=click.Choice(KINDS))
@click.option('--limit', type=click.IntRange(0, 100000), default=100, show_default=True,
              help='triage/sensitive：识别最近 N 个候选（App 的 50/100/全部；0 = 全部）')
@click.option('--request-id', default=None, help='进度标识，可用 photodesk progress 查询（triage/sensitive 自动生成）')
@library_option
def plan(kind, limit, request_id, library):
    """生成整理建议（同 App“生成建议”）：只读图库，把计划保存到 PhotoDesk 并出现在整理记录里。

    KIND：library 全部照片 · classify 分类整理 · triage 截图与票据 · sensitive 敏感照片 · title 照片标题。
    """
    return make_plan(kind, limit, request_id, library)


@agent('plans')
@click.option('--kind', type=click.Choice((*KINDS, 'journey', 'duplicates')), default=None, help='只列某类计划')
@click.option('--limit', type=click.IntRange(1, 1000), default=30, show_default=True)
def plans(kind, limit):
    """整理记录：最近保存的计划（App 显示最近 30 份）。只读。"""
    entries = engine().handle({'command': 'history', 'limit': limit, 'kind': kind})['entries']
    return dict(entries=entries), [f"  {e['id']} · {e['kind']} · {e['count']} 项 · {e['created']}" for e in entries] or ['（没有计划）']


@agent('plan-show')
@click.argument('plan_id')
@click.option('--group', default=None, help='只看一个分组（同分组筛选）')
@click.option('--search', default='', help='在文件名、目标、说明与日期中搜索')
@click.option('--limit', type=click.IntRange(0), default=60, show_default=True, help='最多列出几行；0 = 全部')
@click.option('--offset', type=click.IntRange(0), default=0)
@click.option('--csv-out', type=click.Path(dir_okay=False), default=None, help='把完整清单 CSV 另存到此路径（同“导出清单”）')
def plan_show(plan_id, group, search, limit, offset, csv_out):
    """打开计划（同整理记录里的“打开”）：分组计数、筛选、逐行内容；可导出 CSV。"""
    plan = load_plan(plan_id)
    rows = [r for r in plan['rows'] if (not group or r.get('group') == group) and matches(r, search)]
    shown = page(rows, limit, offset)
    payload = dict(summary(plan), group=group, search=search, matched=len(rows), offset=offset, rows=shown)
    if csv_out:
        shutil.copyfile(plan['csv_path'], csv_out)
        payload['csv_copy'] = str(Path(csv_out).resolve())
    lines = [f"{plan['kind']} 计划 {plan['id']}：{len(plan['rows'])} 项，筛选后 {len(rows)} 项",
             *(f"  分组 {g}：{n}" for g, n in list(payload['groups'].items())[:30]), *map(row_line, shown)]
    return payload, lines


def choose(plan, ids=(), groups=(), everything=False, recommended=False):
    """The GUI's selection as explicit arguments; read-only rows are never picked in bulk."""
    rows = plan['rows']
    by_id = {r['id']: r for r in rows}
    chosen = {}
    for token in ids:
        for part in filter(None, (p.strip() for p in token.split(','))):
            if part not in by_id:
                raise ValueError(f'计划中没有第 {part} 项；用 photodesk plan-show 查看行号。')
            chosen[part] = True
    for name in groups:
        members = [r['id'] for r in rows if r.get('group') == name and not r.get('read_only')]
        if not members:
            raise ValueError(f'计划中没有可操作的分组“{name}”。')
        chosen.update(dict.fromkeys(members, True))
    if everything:
        chosen.update(dict.fromkeys((r['id'] for r in rows if not r.get('read_only')), True))
    if recommended:
        members = [r['id'] for r in rows if r.get('recommended')]
        if not members:
            raise ValueError('这份计划没有建议删除项。')
        chosen.update(dict.fromkeys(members, True))
    if not chosen:
        raise ValueError('没有选中任何项目；用 --select、--select-group 或 --select-all 指定。')
    return list(chosen)


def apply_rows(plan_id, selected, confirm, library, request_id=None):
    path, _ = resolve_library(library)
    extra = {'plan_id': plan_id, 'selected': selected, 'confirmed': confirm}
    if request_id:
        extra['request_id'] = request_id
    result = run_engine('apply', path, **extra)
    payload = dict(result, plan_id=plan_id, selected=len(selected), confirmed=confirm)
    if not confirm:
        return payload, [result['message'], f'确认写入：photodesk apply {plan_id} …同样的选择… --confirm']
    return payload, [result['message'], f"记录：{result['receipt_path']}"]


@agent('apply')
@click.argument('plan_id')
@selection_options
@click.option('--confirm', is_flag=True, help='真正写入“照片”（加相册、关键词、标题）；不加只做预检')
@click.option('--request-id', default=None, help='进度标识，可用 photodesk progress 查询')
@library_option
def apply(plan_id, ids, groups, everything, confirm, request_id, library):
    """检查并写入（同“检查并写入 → 确认写入”）。默认只预检，不改图库。

    --confirm 才写入“照片”：写前重新核对图库、照片、共享状态与标题冲突，写后回读核对，
    执行记录保存在 history/（photodesk records）。与 App 的写入互斥。首次写入时系统可能询问是否允许终端控制“照片”。
    """
    engine().guard({'command': 'apply'})  # refuse before reading anything, as the pipe does
    plan = load_plan(plan_id)
    return apply_rows(plan_id, choose(plan, ids, groups, everything), confirm, library, request_id)


@agent('delete-check')
@click.argument('plan_id', required=False)
@selection_options
@click.option('--event', 'events', multiple=True, metavar='EVENT_ID', help='时间线片段（同首页选中片段；自动使用时间线计划）')
@click.option('--recommended', is_flag=True, help='重复核对里建议删除的副本（自动使用重复建议计划）')
@click.option('--verbose', is_flag=True, help='列出每张照片的本地标识与文件名（默认只给数量）')
@library_option
def delete_check(plan_id, ids, groups, everything, events, recommended, verbose, library):
    """删除前核对（同 ⌘⌫ 的预检）：解析将删除的准确本地照片，不删除任何东西。

    真正删除只在 PhotoDesk 里完成：选中后确认，系统再确认，删除后回读；可在“照片 → 最近删除”恢复。
    """
    engine().guard({'command': 'delete-preview'})
    groups = list(groups)
    if events or (recommended and not plan_id):
        path, _ = resolve_library(library)
        data, _ = timeline_cache(path)
        by_id = {e['id']: e for e in data['events']}
        default = data['duplicates']['id'] if recommended and not events else data['plan']['id']
        if plan_id and plan_id != default:
            raise ValueError('--event 用于时间线计划、--recommended 用于重复建议计划；不要另给计划标识。')
        plan_id = default
        for event in events:
            if event not in by_id:
                raise ValueError(f'时间线里没有片段 {event}。')
            groups.append(by_id[event]['group'])
    if not plan_id:
        raise ValueError('请给出计划标识，或用 --event / --recommended。')
    selected = choose(load_plan(plan_id), ids, groups, everything, recommended)
    path, _ = resolve_library(library)
    result = run_engine('delete-preview', path, plan_id=plan_id, selected=selected)
    items = result['items']
    payload = dict(plan_id=plan_id, library=result['library'], selected=len(selected), count=len(items),
                   protected=sum(bool(i['protected']) for i in items),
                   note='只做核对，未删除任何照片；删除请在 PhotoDesk 中选中后确认。')
    if verbose:
        payload['items'] = items
    lines = [f"可删除 {len(items)} 张（其中收藏、人物或保护标记 {payload['protected']} 张需逐张核对）", payload['note']]
    if verbose:
        lines += [f"  {i['uuid']} · {i['filename']}" + (f" [{i['protected']}]" if i['protected'] else '') for i in items]
    return payload, lines


@agent('records')
@click.option('--kind', type=click.Choice(('apply', 'delete')), default=None, help='只看写入或删除记录')
@click.option('--limit', type=click.IntRange(1, 1000), default=30, show_default=True)
@click.option('--verbose', is_flag=True, help='附带文件名')
def records(kind, limit, verbose):
    """操作记录：history/ 里 App 与 photodesk 的写入回执、删除记录（状态、时间、数量）。只读。"""
    entries = engine().records(kind, limit, verbose)
    lines = [f"  {r['created']} · {r['operation']} · {r['state']} · {r['count']} 项" for r in entries]
    return dict(records=entries), lines or ['（没有记录）']


@agent('progress')
@click.argument('request_id')
def progress(request_id):
    """查看长任务进度（plan/apply 的 --request-id；App 自己的任务也可查）。只读。"""
    if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', request_id):
        raise ValueError('进度标识无效。')
    path = engine().ROOT / 'progress' / f'{request_id}.json'
    if not path.is_file():
        raise ValueError('没有这个任务的进度记录（尚未开始或标识有误）。')
    data = json.loads(path.read_text())
    return dict(request_id=request_id, **data), [f"{data['message']}（{data['done']} / {data['total']}）"]


# ---------------- 设置与诊断 ----------------
def settings_payload():
    import preferences
    values, saved = preferences.load()
    library, source = preferences.library()
    return dict(domain=preferences.domain(), saved=saved, app_running=preferences.app_running(),
                preferences=values, library=library, library_source=source,
                engine_options=preferences.engine_options(values))


@click.group('settings', invoke_without_command=True)
@click.option('--json', 'as_json', is_flag=True, help=JSON_HELP)
@click.pass_context
def settings(ctx, as_json):
    """App 设置（与设置窗口同一份）：不带子命令时显示；settings set KEY VALUE 修改一项。"""
    if ctx.invoked_subcommand:
        return

    def show():
        data = settings_payload()
        source = {'env': 'PHOTODESK_LIBRARY', 'saved': 'App 里选择', 'system': '跟随“照片”最近打开的图库'}[data['library_source']]
        lines = [f"图库：{data['library'] or '（跟随系统）'}（{source}）",
                 *(f'  {k} = {v}' for k, v in data['preferences'].items()),
                 '（尚未保存过设置，以上为默认值）' if not data['saved'] else '',
                 'PhotoDesk 正在运行：修改请用 App 的设置窗口。' if data['app_running'] else '']
        return data, [line for line in lines if line]
    execute('settings', as_json, show)


@agent('set', label='settings set')
@click.argument('key')
@click.argument('value')
def settings_set(key, value):
    """修改一项设置（取值同设置窗口）。PhotoDesk 运行时拒绝，避免被 App 覆盖。

    KEY：automatic includeShared recognizeContent refreshSeconds(60/300/900) batchSize(6/12/24)
    eventHours(1–12) eventKilometers(1–100) meetingMinutes(15–180，步长 15) petNames
    preselectDuplicates thumbnailWidth(140–280，步长 10) appearance(system/light/dark)
    initialTrack library（.photoslibrary 路径；空字符串 = 跟随系统）。
    """
    import preferences
    parsed = preferences.parse(key, value)
    preferences.save(key, parsed)
    data = settings_payload()
    current = data['library'] if key == preferences.LIBRARY_KEY else data['preferences'][key]
    return dict(key=key, value=current, domain=data['domain']), [f'已保存 {key} = {current}（下次打开 PhotoDesk 生效）']


settings.add_command(settings_set)


@agent('doctor')
@click.option('--ocr', 'ocr_check', is_flag=True, help='再用内置合成样本核对本机 OCR（写 diagnostics/ocr-probe.png）')
@library_option
def doctor(ocr_check, library):
    """诊断：引擎版本、数据目录、图库能否读取（完全磁盘访问）、App 是否运行、时间线缓存；--ocr 核对 OCR。

    只读，--ocr 例外：它写一张合成样本图 diagnostics/ocr-probe.png。说明类检查（app_running、
    photos_automation）的 ok 为 null：只报告情况，不代表已验证。
    """
    import preferences
    from photocli.cli import app_version
    checks = []

    def check(name, ok, detail, required=True):
        # ok None = informational: reported, not verified (never counts as a pass).
        checks.append(dict(name=name, ok=None if ok is None else bool(ok), required=required, detail=detail))

    ping = engine().handle({'command': 'ping'})
    check('engine', True, f"PhotoDesk {app_version()} · osxphotos {ping['version']}")
    root = engine().ROOT
    check('data_root', os.access(root, os.W_OK), str(root))
    path, source = resolve_library(library)
    if os.environ.get('PHOTODESK_DEMO_ROOT'):
        library_path = Path(os.environ['PHOTODESK_DEMO_ROOT'])
        probe = library_path / 'demo-input.json'
    else:
        if not path:
            from osxphotos.utils import get_last_library_path, get_system_library_path
            path = get_last_library_path() or get_system_library_path() or ''
        library_path = Path(path).expanduser()
        probe = library_path / 'database' / 'Photos.sqlite'
    try:
        with open(probe, 'rb') as handle:
            handle.read(16)
        check('library_readable', True, f'{library_path}（{source}）')
    except PermissionError:
        check('library_readable', False, f'{library_path}：{PERMISSION}')
    except OSError as exc:
        check('library_readable', False, f'{library_path}：图库不存在或不可读（{type(exc).__name__}）')
    running = preferences.app_running()
    check('app_running', None, 'PhotoDesk 正在运行（settings set 会被拒绝）' if running else 'PhotoDesk 未运行', required=False)
    try:
        data, _ = timeline_cache(str(library_path) if path else '')
        check('timeline_cache', True, f"生成于 {data['generated']}，待识别 {data['pending']}", required=False)
    except ValueError as exc:
        check('timeline_cache', False, str(exc), required=False)
    check('photos_automation', None, '未检查：首次 apply --confirm 时系统会询问是否允许终端控制“照片”', required=False)
    if ocr_check:
        try:
            check('ocr', True, engine().handle({'command': 'ocr-probe'})['message'])
        except Exception as exc:
            check('ocr', False, friendly(exc))
    ok = all(c['ok'] is True for c in checks if c['required'])
    lines = [f"{'·' if c['ok'] is None else '✓' if c['ok'] else '✗'} {c['name']}：{c['detail']}" for c in checks]
    return dict(ok=ok, app_running=running, checks=checks), lines


# ---------------- 旧命令名：同一流程的别名 ----------------
def moved(old, new):
    click.echo(f'提示：{old} 已并入 photodesk {new}（与 App 同一计划与写入流程）。', err=True)


def latest_plan(kind):
    entries = engine().handle({'command': 'history', 'limit': 1, 'kind': kind})['entries']
    if not entries:
        raise ValueError(f'还没有 {kind} 计划；先运行 photodesk plan {kind}。')
    return entries[0]['id']


def plan_then_apply(kind, limit, confirm, library):
    payload, lines = make_plan(kind, limit, None, library)
    if confirm and payload['row_count']:
        plan_record = load_plan(payload['id'])
        result, more = apply_rows(payload['id'], choose(plan_record, everything=True), True, library)
        payload['apply'] = result
        lines += more
    return payload, lines


@agent('classify-plan')
@click.option('--out', 'out_path', default=None, help='另存一份 CSV 到此路径')
@library_option
def classify_plan(out_path, library):
    """旧名：等同 plan classify（--out 另存 CSV）。"""
    moved('classify-plan', 'plan classify')
    return make_plan('classify', 100, None, library, out_path)


@agent('title-plan')
@click.option('--out', 'out_path', default=None, help='另存一份 CSV 到此路径')
@library_option
def title_plan(out_path, library):
    """旧名：等同 plan title（只为空标题补建议）。"""
    moved('title-plan', 'plan title')
    return make_plan('title', 100, None, library, out_path)


def legacy_apply(kind, plan_id, confirm, limit, library):
    if plan_id and not re.fullmatch(r'[0-9a-f-]{36}', plan_id):
        raise ValueError('旧的 CSV 计划已停用；请用 photodesk plan 生成计划，再传它的标识。')
    plan_id = plan_id or latest_plan(kind)
    selected = choose(load_plan(plan_id), everything=True)
    return apply_rows(plan_id, selected[:limit] if limit else selected, confirm, library)


@agent('classify-apply')
@click.option('--plan', 'plan_id', default=None, help='计划标识（默认最近一份分类计划）')
@click.option('--apply', 'confirm', is_flag=True, help='写入“照片”；不加只预检')
@library_option
def classify_apply(plan_id, confirm, library):
    """旧名：等同 apply <最近分类计划> --select-all [--confirm]。"""
    moved('classify-apply', 'apply')
    return legacy_apply('classify', plan_id, confirm, None, library)


@agent('title-apply')
@click.option('--plan', 'plan_id', default=None, help='计划标识（默认最近一份标题计划）')
@click.option('--apply', 'confirm', is_flag=True, help='写入“照片”；不加只预检')
@click.option('--limit', type=click.IntRange(1), default=None, help='只处理前 N 项')
@library_option
def title_apply(plan_id, confirm, limit, library):
    """旧名：等同 apply <最近标题计划> --select-all [--confirm]；已有标题不会被覆盖。"""
    moved('title-apply', 'apply')
    return legacy_apply('title', plan_id, confirm, limit, library)


@agent('triage')
@click.option('--limit', type=click.IntRange(0), default=100, show_default=True, help='识别最近 N 个候选；0 = 全部')
@click.option('--apply', 'confirm', is_flag=True, help='生成后把全部建议写入“照片”的整理相册（保留/待核对，不建删除相册）')
@library_option
def triage(limit, confirm, library):
    """旧名：等同 plan triage；--apply 再对新计划 apply --select-all --confirm。"""
    moved('triage', 'plan triage')
    return plan_then_apply('triage', limit, confirm, library)


@agent('ocr-scan')
@click.option('--limit', type=click.IntRange(0), default=100, show_default=True, help='识别最近 N 个候选；0 = 全部')
@click.option('--apply', 'confirm', is_flag=True, help='生成后给命中照片加 🔒敏感 关键词与相册')
@library_option
def ocr_scan(limit, confirm, library):
    """旧名：等同 plan sensitive；--apply 再对新计划 apply --select-all --confirm。"""
    moved('ocr-scan', 'plan sensitive')
    return plan_then_apply('sensitive', limit, confirm, library)


# ---------------- 由 App 可执行文件执行的命令 ----------------
# These belong to the app itself, not to the photo engine: the「配置与更新…」window's settings, version and release
# channel, the saved shortcuts and their rules, the system login item, and a running PhotoDesk's own actions. The
# work is done inside the app executable (Sources/AgentCommands.swift, entered in PhotoDeskEntry.main before any
# window exists); the words go to it unchanged and its stdout, stderr and exit code come back unchanged. Nothing is
# parsed or re-implemented here. A running PhotoDesk is not restarted or signalled from here.
APP_VERBS = ('config', 'update', 'shortcuts', 'login', 'automation', 'cancel')
# The shared layer waits at most 30 seconds for one sync pass or one release lookup; an import with sync on does both.
APP_SECONDS = 60
APP_SUMMARIES = {
    'config': '配置与更新窗口的配置项：status | export -o <file> | import <file> --yes | sync on|off --yes。',
    'update': '检查更新：update check（只读）。',
    'shortcuts': '快捷键：已保存的绑定、作用范围与冲突；scope 改作用范围，clear 清除绑定。',
    'login': '登录 Mac 时启动：status | on|off --yes。',
    'automation': '运行中的 PhotoDesk 的自动整理：status | pause | resume。',
    'cancel': '取消运行中的 PhotoDesk 里进行中的任务（同状态栏“取消”）。',
}


def app_binary():
    """The app executable that carries these commands: this bundle's own.

    From source there is no bundle; PHOTODESK_NATIVE may name a compiled app executable (the tests do). The frozen
    engine ignores that variable and only ever runs the executable of the bundle it sits in.
    """
    if getattr(sys, 'frozen', False):
        contents = Path(sys.executable).resolve().parents[2]
        try:
            with (contents / 'Info.plist').open('rb') as stream:
                binary = contents / 'MacOS' / plistlib.load(stream)['CFBundleExecutable']
        except (OSError, KeyError, ValueError):
            return None
        return binary if binary.is_file() else None
    named = os.environ.get('PHOTODESK_NATIVE')
    return Path(named) if named and Path(named).is_file() else None


def relay(stream, data):
    """The child's bytes as they are; a text-only stream (in-process tests) gets them decoded."""
    raw = getattr(stream, 'buffer', None)
    if raw is None:
        stream.write(data.decode('utf-8', 'replace'))
        return
    stream.flush()
    raw.write(data)
    raw.flush()


def app_failure(words, code, message):
    """The forwarding itself failed: the same shape as the app's own failures, which otherwise pass through untouched."""
    if '--json' in words:
        command = ' '.join(word for word in words[:2] if not word.startswith('-'))
        print(json.dumps(dict(ok=False, command=command, error=dict(code=code, message=message)), ensure_ascii=False))
    else:
        print('错误：' + message, file=sys.stderr)
    return 1


def app_command(words):
    """Run `photodesk <APP_VERBS word> …` in the app executable and return its exit code."""
    binary = app_binary()
    if binary is None:
        return app_failure(words, 'app_missing', f'找不到 PhotoDesk 的 App 可执行文件：{words[0]} 由它执行，请从已安装的 PhotoDesk.app 运行 photodesk')
    try:
        done = subprocess.run([str(binary), *words], stdin=subprocess.DEVNULL, capture_output=True, timeout=APP_SECONDS)
    except subprocess.TimeoutExpired:
        return app_failure(words, 'timeout', f'{APP_SECONDS} 秒内没有结束，已终止；先用读命令读回当前状态，不要直接重发')
    except OSError as exc:
        return app_failure(words, 'app_missing', f'无法运行 {binary}：{exc}')
    if done.returncode < 0:
        return app_failure(words, 'app_failed', f'App 可执行文件被信号 {-done.returncode} 终止，没有结果；先用读命令读回当前状态')
    relay(sys.stdout, done.stdout)
    relay(sys.stderr, done.stderr)
    return done.returncode


def app_stub(name):
    """Lists the word under Commands and forwards it when click reaches it (e.g. after --config)."""
    @click.command(name, help=APP_SUMMARIES[name], short_help=APP_SUMMARIES[name], add_help_option=False,
                   context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
    @click.pass_context
    def stub(ctx):
        raise click.exceptions.Exit(app_command([name, *ctx.args]))
    return stub


COMMANDS = (audit, timeline, refresh, duplicates, photos, plan, plans, plan_show, apply, delete_check,
            records, progress, settings, doctor, classify_plan, title_plan, classify_apply, title_apply,
            triage, ocr_scan, *map(app_stub, APP_VERBS))

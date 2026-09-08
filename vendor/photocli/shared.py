"""shared-list — 共享相册只读分析 + 出手动清单。

硬边界:iCloud 共享相册无任何 CLI 可写(Apple 没开 API),即使用户是 owner。
所以本模块只读共享相册,找出潜在可清理项(精确重复/疑似冗余),
输出一份 HTML 清单供用户在 Photos.app 里手动操作。
"""
from __future__ import annotations

import collections
import html
from pathlib import Path

import click

from .lib import load_config, load_db


@click.command("shared-list")
@click.pass_context
def shared_list(ctx: click.Context) -> None:
    """列共享相册 + 按 fingerprint 找精确重复,出手动清单 HTML。"""
    cfg = load_config(ctx.obj.get("config_path"))
    db = load_db(cfg.library)
    shared = [p for p in db.photos() if p.shared]

    # 按相册聚合
    by_album: dict[str, list] = collections.defaultdict(list)
    for p in shared:
        for a in (p.albums or []):
            by_album[a].append(p)

    # 精确重复(同 fingerprint)
    fp = collections.defaultdict(list)
    for p in shared:
        if p.fingerprint:
            fp[p.fingerprint].append(p)
    dup_groups = {k: v for k, v in fp.items() if len(v) > 1}

    rows = []
    for album, photos in sorted(by_album.items(), key=lambda kv: -len(kv[1])):
        rows.append(f"<tr><td>{html.escape(album)}</td><td>{len(photos)}</td></tr>")
    dup_rows = []
    for grp in dup_groups.values():
        names = ", ".join(html.escape(p.original_filename or p.uuid[:8]) for p in grp)
        dup_rows.append(f"<tr><td>{len(grp)}</td><td>{names}</td></tr>")

    out = cfg.path("reports") / "shared-manual-checklist.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>共享相册手动清单</title><style>
body{{font:15px/1.6 -apple-system,"PingFang SC",sans-serif;background:#0d1117;color:#e6edf3;max-width:900px;margin:0 auto;padding:30px}}
h1{{font-size:22px}} h2{{border-bottom:1px solid #30363d;padding-bottom:6px;margin-top:30px}}
table{{width:100%;border-collapse:collapse}} td,th{{border-bottom:1px solid #30363d;padding:8px;text-align:left}}
.note{{background:rgba(210,153,34,.1);border-left:3px solid #d29922;padding:10px 14px;border-radius:0 8px 8px 0}}
code{{background:#161b22;padding:2px 6px;border-radius:4px;color:#56d4dd}}</style></head><body>
<h1>📋 共享相册手动操作清单</h1>
<div class="note">⚠️ iCloud 共享相册<b>无法用命令行修改</b>(Apple 没开 API)。下面是只读分析,
你需要在 <b>Photos.app</b> 里手动处理。删除共享相册照片:选中 → 右键 → 移除。</div>
<h2>共享相册概览(共 {len(shared)} 张)</h2>
<table><tr><th>相册</th><th>张数</th></tr>{''.join(rows)}</table>
<h2>精确重复组(同 fingerprint,{len(dup_groups)} 组)</h2>
{'<table><tr><th>组内张数</th><th>文件</th></tr>' + ''.join(dup_rows) + '</table>' if dup_rows else '<p>未发现精确重复。</p>'}
</body></html>""")
    click.echo(f"共享相册 {len(shared)} 张,{len(by_album)} 个相册,精确重复 {len(dup_groups)} 组")
    click.echo(f"手动清单已写: {out}")

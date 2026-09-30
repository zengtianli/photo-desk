"""backup — 删除前的安全网：整包冷备(rsync) + osxphotos sidecar 导出(个人库范围)。

注意:整包 rsync 需 Photos.app 退出;sidecar export 用 PhotoKit 需 Photos.app 运行。
本命令默认只跑 sidecar(可重入增量);整包 rsync 用 --full(需先退出 Photos)。
"""
from __future__ import annotations

import datetime as _dt
import subprocess
from pathlib import Path

import click

from .lib import load_config, get_logger


def _photos_running() -> bool:
    return subprocess.run(["pgrep", "-x", "Photos"], capture_output=True).returncode == 0


@click.command("backup")
@click.option("--dest", default=None, help="备份目标目录(默认 PhotoDesk/cli/backups)")
@click.option("--full", is_flag=True, help="含整包 rsync 冷备(需先退出 Photos.app)")
@click.option("--sidecar/--no-sidecar", default=True, help="是否导出 sidecar(默认是)")
@click.pass_context
def backup(ctx: click.Context, dest: str | None, full: bool, sidecar: bool) -> None:
    """备份：osxphotos sidecar 元数据导出（默认），--full 另做整包冷备。建议在大批删除前运行。"""
    cfg = load_config(ctx.obj.get("config_path"))
    log = get_logger("backup", cfg)
    today = _dt.date.today().isoformat()
    lib = cfg.library or str(Path.home() / "Pictures/Photos Library.photoslibrary")

    if full:
        bdest = Path(dest or cfg.path('backups') / f"Photos-Backup-{today}").expanduser()
        if any(s in str(bdest) for s in ("iCloud", "Dropbox", "Google Drive")):
            raise SystemExit("❌ 备份目标不能是云同步目录(P0 灾难)")
        if _photos_running():
            raise click.ClickException('整包备份需要先退出照片 App；未改变运行中的照片 App。')
        bundle = bdest / "Photos Library.photoslibrary"
        bdest.mkdir(parents=True, exist_ok=True)
        log.info(f"整包 rsync → {bundle}")
        subprocess.run(["rsync", "-aH", f"{lib}/", f"{bundle}/"], check=True)
        log.info(f"✅ 整包冷备完成: {bundle}")

    if sidecar:
        sdest = Path(dest or cfg.path('backups') / f"Photos-Sidecar-{today}").expanduser()
        sdest.mkdir(parents=True, exist_ok=True)
        # 豁免「必带偏移量」: 这只是**文件名**里的本地时间戳(osxphotos report 落盘名),
        # 不是产物内容里的时间断言;+0800 这种偏移量放进文件名反而难读。
        # 语义上要的就是"本地哪一刻跑的",故显式 astimezone() 而非裸 now()。
        report = sdest / f".report-{_dt.datetime.now(_dt.timezone.utc).astimezone():%Y%m%d-%H%M%S}.csv"
        log.info(f"sidecar 导出(个人库) → {sdest}")
        cmd = [
            "export", str(sdest),
            "--sidecar", "JSON", "--touch-file",
            "--update", "--report", str(report),
        ]
        if cfg.personal_only:
            cmd.append("--not-shared")
        if cfg.library:
            cmd.extend(['--db', cfg.library])
        cmd.append("--verbose")
        from osxphotos.cli import cli_main
        cli_main.main(args=cmd, prog_name='photodesk backup', standalone_mode=False)
        log.info(f"✅ sidecar 完成,报告 {report}")

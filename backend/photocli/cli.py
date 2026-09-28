"""photocli 入口 — `photocli <subcommand>`。"""
from __future__ import annotations

import click
import os
from pathlib import Path
import plistlib
import sys

from . import __version__, audit, backup, classify, dedup, ocr, shared, title, triage


def app_version():
    if getattr(sys, 'frozen', False):
        info = Path(sys.executable).resolve().parents[2] / 'Info.plist'
        if info.is_file():
            with info.open('rb') as stream:
                data = plistlib.load(stream)
            return f"{data['CFBundleShortVersionString']} ({data['CFBundleVersion']})"
    return __version__


@click.group(name='photodesk')
@click.version_option(app_version(), prog_name='photodesk')
@click.option("--config", "config_path", default=None, help="私有 YAML 配置路径(默认 PhotoDesk 数据目录的 cli-config.yaml，没有则用中性默认)")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
    """iCloud Photos 整理工具。plan-file 工作流,dry-run 默认,删除永远手动。"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


cli.add_command(audit.audit)
cli.add_command(backup.backup)
cli.add_command(classify.classify_plan)
cli.add_command(classify.classify_apply)
cli.add_command(ocr.ocr_scan)
cli.add_command(ocr.ocr_extract)
cli.add_command(shared.shared_list)
cli.add_command(dedup.dedup_export)
cli.add_command(dedup.reconcile)
cli.add_command(triage.triage)
cli.add_command(title.title_plan)
cli.add_command(title.title_apply)


def run(args):
    from . import lib
    os.umask(0o077)
    try:
        lib.REPO_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        lib.REPO_ROOT.chmod(0o700)
        lib.REPO_ROOT.parent.chmod(0o700)
        if os.environ.get('PHOTODESK_DEMO_ROOT') and ('--apply' in args or 'backup' in args):
            raise click.ClickException('演示模式禁止写入系统照片图库或执行备份。')
        cli.main(args=args, prog_name='photodesk', standalone_mode=False)
        return 0
    except click.ClickException as exc:
        click.echo('错误：' + ' '.join(exc.format_message().splitlines()), err=True)
        return 1
    except PermissionError:
        click.echo('错误：无权读取照片或保存数据，请给当前终端完全磁盘访问权限。', err=True)
        return 1
    except (ValueError, OSError) as exc:
        click.echo(f'错误：无法完成操作，请检查图库、配置和文件权限（{type(exc).__name__}）。', err=True)
        return 1
    except Exception as exc:
        click.echo(f'错误：操作未完成，请检查配置或重新生成整理计划（{type(exc).__name__}）。', err=True)
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or ['--help']))

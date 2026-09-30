"""photodesk 命令组。

这里注册只有命令行才有的旧工具（backup、ocr-extract、shared-list、dedup-export、reconcile）；
App 功能对应的命令由 backend/desk_cli.py 在 bridge.dispatch 时加入，走与 App 相同的引擎。
"""
from __future__ import annotations

import click
import json
import os
from pathlib import Path
import plistlib
import sys

from . import __version__, backup, dedup, ocr, shared


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
@click.option("--config", "config_path", default=None, help="私有 YAML 配置：旧工具默认读数据目录的 cli-config.yaml；显式传入时，其中的 library 也用于其他命令")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
    """PhotoDesk · 照片台命令行：与 App 同一引擎、同一份时间线、计划、记录与设置。

    读取类命令加 --json 输出 {"ok": ...}，失败以 1 退出。写入“照片”必须显式 --confirm
    （旧命令名用 --apply）；删除照片只在 App 内经系统确认，命令行止于 delete-check。
    图库默认与 App 相同；--config 的私有 YAML 只给旧工具和显式指定图库时使用。
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


cli.add_command(backup.backup)
cli.add_command(ocr.ocr_extract)
cli.add_command(shared.shared_list)
cli.add_command(dedup.dedup_export)
cli.add_command(dedup.reconcile)


def run(args):
    from . import lib
    # --json callers parse stdout, so every failure, including the ones before a command runs
    # (usage errors, the demo guard, an unwritable data folder), is one JSON object there.
    as_json = '--json' in args and '--help' not in args

    def fail(message):
        if as_json:
            name = next((a for a in args if a in cli.commands), None)
            click.echo(json.dumps({'ok': False, 'command': name, 'error': message}, ensure_ascii=False))
        else:
            click.echo('错误：' + message, err=True)
        return 1

    os.umask(0o077)
    try:
        try:
            lib.REPO_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
            lib.REPO_ROOT.chmod(0o700)
            lib.REPO_ROOT.parent.chmod(0o700)
        except OSError:
            # Keeping the folder private is done where it can be; a read must not fail on this
            # metadata write, and a command that has to write reports its own error.
            pass
        if os.environ.get('PHOTODESK_DEMO_ROOT') and ('--apply' in args or 'backup' in args) and '--help' not in args:
            raise click.ClickException('演示模式禁止写入系统照片图库或执行备份。')
        code = cli.main(args=args, prog_name='photodesk', standalone_mode=False)
        # Non-standalone click returns the exit code of ctx.exit()/Exit (e.g. a failed --json result).
        return code if isinstance(code, int) else 0
    except click.ClickException as exc:
        return fail(' '.join(exc.format_message().splitlines()))
    except PermissionError:
        return fail('无权读取照片或保存数据，请给当前终端完全磁盘访问权限。')
    except (ValueError, OSError) as exc:
        return fail(f'无法完成操作，请检查图库、配置和文件权限（{type(exc).__name__}）。')
    except Exception as exc:
        return fail(f'操作未完成，请检查配置或重新生成整理计划（{type(exc).__name__}）。')


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or ['--help']))

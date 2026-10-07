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


# The shared lifecycle layer's own help lines for `photodesk` (AppLifecycleCLI.helpRead / helpWrite / helpWindowOnly),
# verbatim. tests/test_lifecycle_cli.py looks each of them up in what the compiled app prints for `config --help`, so
# the two cannot drift.
LIFECYCLE_READS = (
    '  config status              「使用 iCloud 记住配置」开关、开关下面那句同步状态、当前可迁移的配置项、App 是否在运行（只读）',
    '  update check               检查更新：当前版本、此渠道最新版本、有没有新版、怎么升级（只读；私有渠道读 iCloud Drive 里的发行记录，公开渠道联网读发行记录）')
LIFECYCLE_WRITES = (
    '  config export -o <file>        导出配置：与窗口「导出配置…」同一份文件；不改设置，只写你指定的那个文件（--force 覆盖；-o - 输出到标准输出，不写文件）',
    '  config import <file> --yes     导入配置：先备份原配置再覆盖，与窗口「导入配置…」相同',
    '  config sync on|off --yes       拨动「使用 iCloud 记住配置」（--dry-run 只看会不会变；用 photodesk config status 回读）',
    '  update install --yes           升级到新版：与窗口「升级到新版…」同一条路——验证发行包与签名、替换当前 App，运行中的先退出、换好再重开；配置保留，替换失败回滚（--dry-run 只看会做什么；用 photodesk update check 回读）')
LIFECYCLE_WINDOW_ONLY = '打开「配置与更新…」窗口'

HELP = """PhotoDesk · 照片台命令行：与 App 同一引擎、同一份时间线、计划、记录与设置。

读取类命令加 --json 输出 {"ok": ...}，失败以 1 退出。写入“照片”必须显式 --confirm
（旧命令名用 --apply）；删除照片只在 App 内经系统确认，命令行止于 delete-check。
图库默认与 App 相同；--config 的私有 YAML 只给旧工具和显式指定图库时使用。

\b
读命令（不改“照片”，不改 PhotoDesk 的数据）：
  doctor 读回当前状态：版本、数据目录、图库能否读取、App 是否运行、时间线缓存、
         照片与自动化授权是否到位（只读系统现有授权，不询问、不弹窗）
  timeline duplicates photos audit plans plan-show records progress
  settings delete-check reconcile
  shortcuts                  已保存的快捷键、作用范围与冲突提示（同设置窗口“快捷键”页）
  login status               “登录 Mac 时启动”是否开着
  automation status          运行中的 PhotoDesk 的自动整理与任务状态；App 未运行时照实说
@LIFECYCLE_READS@
写命令：
  refresh plan    只写 PhotoDesk 自己的索引、计划与缓存
  settings set    改 App 设置；PhotoDesk 运行时拒绝，改后用 settings 读回
  apply           加 --confirm 才写入“照片”，不加只预检；写后用 records 读回
  backup ocr-extract shared-list dedup-export    只写各自的导出文件
  shortcuts set <动作> <组合键> [application|global]   给动作设一个组合键（窗口里是按键录制，这里写出来，如 ctrl+opt+p）；PhotoDesk 运行时拒绝，改后用 shortcuts 读回
  shortcuts scope <动作> application|global      改已有快捷键的作用范围；PhotoDesk 运行时拒绝，改后用 shortcuts 读回
  shortcuts clear <动作> | clear --all           清除一个动作的绑定 / 清除所有快捷键；PhotoDesk 运行时拒绝
  login on|off --yes         拨动“登录 Mac 时启动”（--dry-run 只看会不会变；用 login status 读回）
  automation pause|resume    暂停 / 继续运行中的 PhotoDesk 的自动整理（只改这一次运行，不改设置；用 automation status 读回）
  cancel                     取消运行中的 PhotoDesk 里进行中的任务（同状态栏“取消”；正在写入图库时不能取消）
  start                      在后台启动 PhotoDesk：不激活、窗口不显示（Dock 里会有图标）；已在运行时不再启动。用 automation status 读回
  quit                       退出运行中的 PhotoDesk（同 ⌘Q；正在写入图库时不退出）。settings set、shortcuts set|scope|clear 要它不在运行
@LIFECYCLE_WRITES@

\b
--json 输出（stdout，一个 JSON 对象）：
  成功 {"ok": true, "command": "<命令>", ...}
  失败 {"ok": false, "command": "<命令或 null>", "error": "原因"}
  config、update、shortcuts、login、automation、cancel、start、quit 由 PhotoDesk.app 自己执行（引擎原样转交），失败时 error 是对象：
  失败 {"ok": false, "command": "<命令>", "error": {"code": "<短码>", "message": "原因"}}；各自的 --help 列出字段与短码
  backup、ocr-extract 没有 --json，只输出文本进度。

\b
退出码：
  0  成功（查无结果也算成功）
  1  失败：操作失败、参数或用法错误、权限不足；doctor 的必需项未通过也是 1
  2  用法错误或缺确认参数：只有 config、update、shortcuts、login、automation、cancel、start、quit 这八个用 2
     （error.code 为 usage、confirmation_required、file_exists），其余命令的用法错误仍是 1

\b
仅在窗口中：
  确认删除（产品规定删除只在 App 内，PhotoKit 的系统确认须真人点；命令止于 delete-check）
  导入验收测试图…（产品边界：它向本人的系统照片图库写入一张合成测试图，命令建得出、删不掉——删除要本人在窗口里逐项确认、再点系统确认；产品约定不在本人图库无人值守做写入，所以不给命令）
  完全磁盘访问权限、照片访问权限（系统授权须真人在系统设置里开；是否到位用 doctor 读）
  录制快捷键（要真人按键；把组合键写出来设置用 shortcuts set）
  上一张 / 下一张 / 关闭预览、显示主窗口、错误提示的收起、原生操作说明
  在“照片”中打开、在“照片”中查看、打开本地记录、在 Finder 显示 App
  PhotoDesk 安装与使用教程、@LIFECYCLE_WINDOW_ONLY@
""".replace('@LIFECYCLE_READS@', '\n'.join(LIFECYCLE_READS)).replace('@LIFECYCLE_WRITES@', '\n'.join(LIFECYCLE_WRITES)) \
    .replace('@LIFECYCLE_WINDOW_ONLY@', LIFECYCLE_WINDOW_ONLY)


@click.group(name='photodesk', help=HELP)
@click.version_option(app_version(), prog_name='photodesk')
@click.option("--config", "config_path", default=None, help="私有 YAML 配置：旧工具默认读数据目录的 cli-config.yaml；显式传入时，其中的 library 也用于其他命令")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
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

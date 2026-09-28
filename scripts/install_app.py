#!/usr/bin/env python3
"""Install the verified PhotoDesk bundle without touching a running instance."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import uuid


def check_bundle(path: Path, bundle_id: str) -> None:
    if path.is_symlink():
        raise RuntimeError(f"拒绝替换软链接：{path}")
    with (path / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != bundle_id:
        raise RuntimeError(f"bundle ID 不符，未改动：{path}")


def check_running(paths: list[Path]) -> None:
    rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
    prefixes = tuple(str(path) + "/Contents/" for original in paths for path in (original, original.resolve()))
    for row in rows.splitlines():
        fields = row.strip().split(None, 1)
        if len(fields) == 2 and (fields[1].startswith(prefixes)
                                or str(Path(fields[1]).resolve()).startswith(prefixes)):
            raise RuntimeError(f"PhotoDesk 正在运行（PID {fields[0]}）；请正常退出后重试，未终止进程")


def install(source: Path, name_en: str, display_name: str, bundle_id: str,
            applications: Path = Path("/Applications"), trash: Path | None = None,
            bin_dir: Path | None = None) -> Path:
    if bundle_id != "cyou.tianli.PhotoDesk" or name_en != "PhotoDesk":
        raise RuntimeError("安装器仅接管 PhotoDesk 的既有名称和 bundle ID")
    if not display_name or "/" in display_name or display_name in (".", ".."):
        raise RuntimeError("无效的 display_name")
    source = source.resolve(strict=True)
    applications = applications.resolve()
    destination = applications / f"{name_en}.app"
    legacy = applications / f"{display_name}.app"
    targets = list(dict.fromkeys([destination, legacy]))
    check_bundle(source, bundle_id)
    cli_relative = Path("Contents/Resources/bin/photodesk")
    if not (source / cli_relative).is_file() or not os.access(source / cli_relative, os.X_OK):
        raise RuntimeError("构建产物缺少可执行的 photodesk 命令")
    link = (bin_dir or Path.home() / ".local/bin") / "photodesk"
    if link.exists() and not link.is_symlink():
        raise RuntimeError(f"命令路径已有非软链文件，未覆盖：{link}")
    previous_link = os.readlink(link) if link.is_symlink() else None
    if previous_link is not None and not str(link.resolve()).startswith(tuple(str(p) + "/Contents/" for p in targets)):
        raise RuntimeError(f"命令路径指向其他应用，未覆盖：{link}")
    for target in targets:
        if target.exists() or target.is_symlink():
            check_bundle(target, bundle_id)
        if target == source:
            raise RuntimeError("构建产物不能同时是安装目标")
    check_running(targets)
    # Stage first; a failed copy/signature check leaves both installed paths intact.
    stage_root = Path(tempfile.mkdtemp(prefix=".PhotoDesk-install-", dir=applications))
    staged = stage_root / destination.name
    moved: list[tuple[Path, Path]] = []
    installed = False
    linked = False
    try:
        subprocess.run(["/usr/bin/ditto", str(source), str(staged)], check=True)
        check_bundle(staged, bundle_id)
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(staged)], check=True)
        check_running(targets)
        backup_root = (trash or Path.home() / ".Trash") / (
            "photodesk-install-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        for target in targets:
            if target.exists() or target.is_symlink():
                check_bundle(target, bundle_id)
                backup_root.mkdir(parents=True, exist_ok=True)
                backup = backup_root / target.name
                shutil.move(str(target), str(backup))
                moved.append((target, backup))
        staged.rename(destination)
        installed = True
        check_bundle(destination, bundle_id)
        link.parent.mkdir(parents=True, exist_ok=True)
        temporary_link = link.with_name(".photodesk-" + uuid.uuid4().hex)
        try:
            temporary_link.symlink_to(destination / cli_relative)
            temporary_link.replace(link)
            linked = True
        finally:
            temporary_link.unlink(missing_ok=True)
    except BaseException:
        if linked:
            link.unlink()
            if previous_link is not None:
                link.symlink_to(previous_link)
        if installed:
            destination.rename(staged)
        for target, backup in reversed(moved):
            shutil.move(str(backup), str(target))
        raise
    finally:
        shutil.rmtree(stage_root)
    print(f"已安装：{destination}（旧版已保留在废纸篓，未启动或重启进程）")
    print(f"命令行：{link} → {destination / cli_relative}")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--name-en", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--bundle-id", required=True)
    args = parser.parse_args()
    try:
        install(args.source, args.name_en, args.display_name, args.bundle_id)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"安装未完成：{error}\n")

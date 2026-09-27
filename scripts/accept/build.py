"""Build locally and ask Chapter to bind the actual binary to these source inputs.

Never installs, publishes, or changes the release manifest.
"""
from pathlib import Path
import shlex
import subprocess
import yaml
from _common import APP, ROOT


def main():
    config = yaml.safe_load((ROOT / "project.yaml").read_text())["sop"]
    command = [str(Path.home() / "Dev/.venv/bin/python"),
               str(ROOT.parent / "chapter/engine/app_sop.py"), "build-receipt",
               "--app", "photo-desk", "--artifact", str(APP),
               "--build-command", f"cd {shlex.quote(str(ROOT))} && bash build.sh --no-install"]
    for pattern in config["source"]:
        command.extend(["--source-glob", pattern])
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()

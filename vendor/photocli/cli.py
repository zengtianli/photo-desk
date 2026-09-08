"""photocli 入口 — `photocli <subcommand>`。"""
from __future__ import annotations

import click

from . import __version__, audit, backup, classify, dedup, ocr, shared, title, triage


@click.group()
@click.version_option(__version__)
@click.option("--config", "config_path", default=None, help="config.yaml 路径(默认包内)")
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


if __name__ == "__main__":
    cli()

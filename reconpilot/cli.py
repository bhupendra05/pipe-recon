"""
pipe-recon CLI — run reconciliation from the command line.

Usage:
    pipe-recon reconcile mapping.csv \\
        --source "postgresql://user:pass@host/crm" \\
        --target "postgresql://user:pass@host/dw" \\
        --table  CUSTOMER \\
        --direction INBOUND \\
        --filter "load_date = '2026-05-27'" \\
        --html   report.html

    pipe-recon sample-mapping [OUTPUT]
        Write a sample mapping CSV to fill in.
"""

from __future__ import annotations
import sys
import click
from datetime import datetime


@click.group()
@click.version_option("0.1.0", prog_name="pipe-recon")
def main():
    """pipe-recon — mapping-driven pipeline reconciliation tool."""


@main.command("reconcile")
@click.argument("mapping_file")
@click.option("--source", "-s", required=True, help="Source DSN (postgresql://, sqlite:///, etc.) or config key")
@click.option("--target", "-t", required=True, help="Target DSN or config key")
@click.option("--config",       default="connections.yaml", show_default=True, help="Path to connections.yaml")
@click.option("--table",  "-T", required=True, help="Source table name to reconcile")
@click.option("--direction", "-d", default="INBOUND", show_default=True,
              type=click.Choice(["INBOUND", "OUTBOUND"], case_sensitive=False),
              help="INBOUND = source→target, OUTBOUND = target→source")
@click.option("--filter",  "-f", "run_filter", default=None, help="WHERE clause to scope latest run, e.g. \"load_date = '2026-05-27'\"")
@click.option("--pipeline", "-p", default="", help="Pipeline display name")
@click.option("--sample",   "-n", default=None, type=int, help="Reconcile only N random rows")
@click.option("--html",          default=None, help="Write HTML report to this path")
@click.option("--json",   "json_out", default=None, help="Write JSON report to this path")
def reconcile_cmd(mapping_file, source, target, config, table, direction,
                  run_filter, pipeline, sample, html, json_out):
    """Reconcile SOURCE_TABLE using a mapping document."""
    from reconpilot.mapping import load_mapping
    from reconpilot.connection import connect_dsn, connect_from_config
    from reconpilot.reconciler import reconcile_from_mapping

    click.echo(f"📋 Loading mapping: {mapping_file}")
    try:
        doc = load_mapping(mapping_file)
    except Exception as e:
        click.secho(f"❌ Failed to load mapping: {e}", fg="red", err=True)
        sys.exit(1)

    doc.summary()

    # Connect source
    click.echo(f"\n🔌 Connecting source: {source}")
    try:
        if "://" in source:
            src_conn = connect_dsn(source, name="source")
        else:
            src_conn = connect_from_config(source, config)
    except Exception as e:
        click.secho(f"❌ Source connection failed: {e}", fg="red", err=True)
        sys.exit(1)

    # Connect target
    click.echo(f"🔌 Connecting target: {target}")
    try:
        if "://" in target:
            tgt_conn = connect_dsn(target, name="target")
        else:
            tgt_conn = connect_from_config(target, config)
    except Exception as e:
        click.secho(f"❌ Target connection failed: {e}", fg="red", err=True)
        sys.exit(1)

    click.echo(f"\n⚙️  Reconciling table '{table}' [{direction}]" +
               (f" — filter: {run_filter}" if run_filter else "") +
               (f" — sample: {sample}" if sample else ""))

    try:
        result = reconcile_from_mapping(
            mapping_doc=doc,
            source_conn=src_conn,
            target_conn=tgt_conn,
            source_table=table,
            direction=direction,
            pipeline_name=pipeline or table,
            run_filter=run_filter,
            sample=sample,
        )
    except Exception as e:
        click.secho(f"❌ Reconciliation failed: {e}", fg="red", err=True)
        sys.exit(1)
    finally:
        src_conn.close()
        tgt_conn.close()

    result.print()

    if html:
        from reconpilot.report import to_html
        to_html([result], html, project=pipeline or f"Reconciliation {datetime.now().strftime('%Y-%m-%d')}")
        click.secho(f"\n📄 HTML report saved: {html}", fg="green")

    if json_out:
        import json
        with open(json_out, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        click.secho(f"📄 JSON report saved: {json_out}", fg="green")

    sys.exit(0 if result.is_clean else 1)


@main.command("sample-mapping")
@click.argument("output", default="sample_mapping.csv")
def sample_mapping_cmd(output):
    """Create a sample mapping CSV file to fill in."""
    from reconpilot.mapping import create_sample_mapping
    create_sample_mapping(output)


@main.command("show-mapping")
@click.argument("mapping_file")
def show_mapping_cmd(mapping_file):
    """Print a summary of a mapping document."""
    from reconpilot.mapping import load_mapping
    try:
        doc = load_mapping(mapping_file)
        doc.summary()
    except Exception as e:
        click.secho(f"❌ {e}", fg="red", err=True)
        sys.exit(1)

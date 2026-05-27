"""
reconpilot.report — HTML report generator for pipeline reconciliation runs.

Produces a self-contained, professional HTML report with:
  1. Summary table — success count, error count, missing, extra, field mismatches per pipeline
  2. Side-by-side detail table — source value | target value | comment for every discrepancy
"""

from __future__ import annotations
import html as _html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reconpilot.reconciler import RunReconcileReport


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f0f4f8; color: #1a1a2e; font-size: 14px; }

/* ── Header ── */
.header { background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
          color: white; padding: 28px 40px; }
.header h1 { font-size: 1.5rem; font-weight: 700; }
.header .meta { font-size: 0.82rem; opacity: 0.75; margin-top: 5px; }

/* ── Summary banner ── */
.summary-banner { background: white; border-bottom: 1px solid #dde3ec;
                  padding: 14px 40px; display: flex; gap: 10px; flex-wrap: wrap; }
.pill { padding: 5px 14px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }
.pill.clean   { background: #d1fae5; color: #065f46; }
.pill.issues  { background: #fee2e2; color: #991b1b; }
.pill.info    { background: #dbeafe; color: #1e40af; }

/* ── Content wrapper ── */
.content { padding: 24px 40px; }

/* ── Section headings ── */
.section-heading {
  font-size: 0.72rem; font-weight: 800; text-transform: uppercase;
  letter-spacing: .1em; color: #475569; margin: 24px 0 10px;
  padding-bottom: 4px; border-bottom: 2px solid #e2e8f0;
}

/* ── Cards ── */
.card { background: white; border-radius: 10px; border: 1px solid #e2e8f0;
        box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 28px; overflow: hidden; }
.card-header { padding: 14px 18px; background: #f8fafc;
               border-bottom: 1px solid #e2e8f0; display: flex;
               align-items: center; gap: 10px; }
.card-header h2 { font-size: 0.95rem; font-weight: 700; flex: 1; }
.card-body { padding: 18px; }

/* ── Badges ── */
.badge { padding: 3px 9px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; }
.badge.clean   { background: #d1fae5; color: #065f46; }
.badge.issues  { background: #fee2e2; color: #991b1b; }
.badge.inbound { background: #dbeafe; color: #1e40af; }
.badge.outbound{ background: #ede9fe; color: #5b21b6; }

/* ── Summary stats grid ── */
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px,1fr));
              gap: 10px; margin-bottom: 18px; }
.stat { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
        padding: 10px 14px; text-align: center; }
.stat .num { font-size: 1.4rem; font-weight: 800; color: #1e3a5f; }
.stat .lbl { font-size: 0.68rem; color: #64748b; margin-top: 2px; text-transform: uppercase; letter-spacing:.04em; }
.stat.ok   { border-color: #bbf7d0; }
.stat.ok   .num { color: #16a34a; }
.stat.bad  { background: #fff1f2; border-color: #fecdd3; }
.stat.bad  .num { color: #be123c; }
.stat.warn { background: #fffbeb; border-color: #fde68a; }
.stat.warn .num { color: #b45309; }

/* ── Tables (shared) ── */
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { background: #f1f5f9; padding: 8px 11px; text-align: left;
     font-weight: 700; color: #475569; white-space: nowrap;
     position: sticky; top: 0; }
td { padding: 7px 11px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f8fafc; }

/* ── Summary overview table ── */
.overview-table th { font-size: 0.72rem; }
.overview-table td { font-size: 0.8rem; }
.overview-table .status-cell { font-weight: 700; }
.overview-table .status-clean  { color: #16a34a; }
.overview-table .status-issues { color: #be123c; }

/* ── Field-level table ── */
.field-row-mismatch td { background: #fff7ed !important; }

/* ── Detail diff table ── */
.diff-table { table-layout: fixed; }
.diff-table th:nth-child(1) { width: 90px; }   /* Key */
.diff-table th:nth-child(2) { width: 80px; }   /* Status */
.diff-table th:nth-child(3),
.diff-table th:nth-child(4) { width: 25%; }     /* Src / Tgt */
.diff-table th:nth-child(5) { width: auto; }    /* Comment */

.diff-missing td  { background: #fff1f2; }
.diff-extra td    { background: #fffbeb; }
.diff-mismatch td { background: #fefce8; }

.diff-missing  .status-badge { background:#fee2e2; color:#991b1b; }
.diff-extra    .status-badge { background:#fef9c3; color:#854d0e; }
.diff-mismatch .status-badge { background:#fef9c3; color:#78350f; }

.status-badge { display:inline-block; padding:2px 8px; border-radius:4px;
                font-size:0.68rem; font-weight:700; white-space:nowrap; }

.cell-val { font-family: monospace; font-size: 0.75rem; word-break: break-all; }
.cell-null { color: #94a3b8; font-style: italic; font-size: 0.72rem; }
.comment-text { font-size: 0.75rem; color: #64748b; line-height: 1.4; }

/* ── SQL block ── */
.sql-block { background: #1e293b; color: #94a3b8; border-radius: 8px;
             padding: 12px 16px; font-family: monospace; font-size: 0.75rem;
             white-space: pre-wrap; word-break: break-all; margin-bottom: 8px; }

/* ── Warnings ── */
.warn-box { background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px;
            padding: 10px 14px; font-size: 0.8rem; color: #92400e; }

/* ── Scrollable wrapper ── */
.table-scroll { overflow-x: auto; }

/* ── Footer ── */
.footer { text-align: center; padding: 20px; color: #94a3b8; font-size: 0.72rem; }
"""


def _e(s) -> str:
    return _html.escape(str(s))


def _cell(val, highlight: bool = False) -> str:
    if val is None or val == {}:
        return '<span class="cell-null">— null —</span>'
    if val == "":
        return '<span class="cell-null">— empty —</span>'
    cls = "cell-val" + (" highlight" if highlight else "")
    return f'<span class="{cls}">{_e(val)}</span>'


def _render_summary_table(reports: list) -> str:
    """Table 1 — one row per pipeline with counts at a glance."""
    rows = ""
    for r in reports:
        st_cls = "status-clean" if r.is_clean else "status-issues"
        st_txt = "✅ CLEAN" if r.is_clean else "❌ ISSUES"
        arrow  = "→" if r.direction == "INBOUND" else "←"
        cnt_ok = "" if r.source_count == r.target_count else ' style="color:#be123c;font-weight:700"'
        rows += f"""
        <tr>
          <td><strong>{_e(r.pipeline_name)}</strong></td>
          <td>{_e(r.source_table)} {arrow} {_e(r.target_table)}</td>
          <td><span class="badge {'inbound' if r.direction=='INBOUND' else 'outbound'}">{r.direction}</span></td>
          <td>{_e(r.run_filter or '—')}</td>
          <td>{r.source_count:,}</td>
          <td{cnt_ok}>{r.target_count:,}</td>
          <td style="color:#16a34a;font-weight:700">{r.success_count:,}</td>
          <td style="{'color:#be123c;font-weight:700' if r.error_count else ''}">{r.error_count:,}</td>
          <td>{len(r.missing_in_target):,}</td>
          <td>{len(r.extra_in_target):,}</td>
          <td>{r.total_field_mismatches:,}</td>
          <td class="status-cell {st_cls}">{st_txt}</td>
        </tr>"""
    return f"""
    <div class="card">
      <div class="card-header"><h2>📊 Reconciliation Summary</h2></div>
      <div class="card-body table-scroll">
        <table class="overview-table">
          <thead>
            <tr>
              <th>Pipeline</th><th>Tables</th><th>Direction</th><th>Run Filter</th>
              <th>Src Rows</th><th>Tgt Rows</th>
              <th>✅ Success</th><th>❌ Errors</th>
              <th>Missing</th><th>Extra</th><th>Field Mismatches</th><th>Status</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""


def _render_diff_table(r) -> str:
    """Table 2 — side-by-side source vs target with comment per discrepancy row."""
    if not r.row_diffs:
        return '<p style="color:#16a34a;padding:12px 0">✅ No discrepancies found — all rows matched cleanly.</p>'

    # Build column headers from mapping (source col → target col pairs)
    # Use field_results to get the column pairs
    src_cols = [f.source_column for f in r.field_results]
    tgt_cols = [f.target_column for f in r.field_results]

    # Key column header
    key_src = next((f.source_column for f in r.field_results), "key")

    diff_rows = ""
    for d in r.row_diffs:
        if d.status == "missing_in_target":
            row_cls = "diff-missing"
            badge   = '<span class="status-badge">❌ Missing in target</span>'
        elif d.status == "extra_in_target":
            row_cls = "diff-extra"
            badge   = '<span class="status-badge">⚠️ Extra in target</span>'
        else:
            row_cls = "diff-mismatch"
            badge   = '<span class="status-badge">🔄 Value mismatch</span>'

        # Build source cells
        src_cells = ""
        tgt_cells = ""
        for sc, tc in zip(src_cols, tgt_cols):
            sv = d.source_row.get(sc, d.source_row.get(sc.lower()))
            tv = d.target_row.get(tc, d.target_row.get(tc.lower()))
            is_bad = (sc in d.mismatched_fields or sc.lower() in [f.lower() for f in d.mismatched_fields])
            hl_style = ' style="background:#fee2e2;border-radius:3px;padding:1px 3px"' if is_bad else ""
            src_cells += f'<div{hl_style}><small style="color:#94a3b8">{_e(sc)}: </small>{_cell(sv)}</div>'
            tgt_cells += f'<div{hl_style}><small style="color:#94a3b8">{_e(tc)}: </small>{_cell(tv)}</div>'

        if not d.source_row:
            src_cells = '<span class="cell-null">— not in source —</span>'
        if not d.target_row:
            tgt_cells = '<span class="cell-null">— not in target —</span>'

        diff_rows += f"""
        <tr class="{row_cls}">
          <td><strong>{_e(d.key)}</strong></td>
          <td>{badge}</td>
          <td>{src_cells}</td>
          <td>{tgt_cells}</td>
          <td class="comment-text">{_e(d.comment)}</td>
        </tr>"""

    total = len(r.row_diffs)
    shown = min(total, 500)
    cap_note = f'<p style="font-size:0.75rem;color:#94a3b8;padding:8px 0">Showing {shown} of {total} discrepancy rows.</p>' if total > 500 else ""

    return f"""
    <div class="card">
      <div class="card-header">
        <h2>🔎 Row-Level Discrepancy Detail</h2>
        <span class="badge issues">{total} discrepanc{'y' if total==1 else 'ies'}</span>
      </div>
      <div class="card-body">
        {cap_note}
        <div class="table-scroll">
          <table class="diff-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Status</th>
                <th>Source Values ({_e(r.source_table)})</th>
                <th>Target Values ({_e(r.target_table)})</th>
                <th>Comment / Discrepancy Reason</th>
              </tr>
            </thead>
            <tbody>{diff_rows}</tbody>
          </table>
        </div>
      </div>
    </div>"""


def _render_pipeline_card(r) -> str:
    """Detailed card for a single pipeline — stats + field table + diff table + SQL."""
    status_cls = "clean" if r.is_clean else "issues"
    status_txt = "✅ CLEAN" if r.is_clean else "❌ ISSUES"
    dir_cls    = "inbound" if r.direction == "INBOUND" else "outbound"
    arrow      = "→" if r.direction == "INBOUND" else "←"

    cnt_cls  = "" if r.source_count == r.target_count else " bad"
    miss_cls = " bad"  if r.missing_in_target else " ok"
    extra_cls= " warn" if r.extra_in_target   else " ok"
    fmm_cls  = " bad"  if r.total_field_mismatches > 0 else " ok"
    err_cls  = " bad"  if r.error_count > 0 else " ok"
    suc_cls  = " ok"

    stats_html = f"""
    <div class="stats-grid">
      <div class="stat"><div class="num">{r.source_count:,}</div><div class="lbl">Source Rows</div></div>
      <div class="stat{cnt_cls}"><div class="num">{r.target_count:,}</div><div class="lbl">Target Rows</div></div>
      <div class="stat{suc_cls}"><div class="num">{r.success_count:,}</div><div class="lbl">✅ Success</div></div>
      <div class="stat{err_cls}"><div class="num">{r.error_count:,}</div><div class="lbl">❌ Errors</div></div>
      <div class="stat{miss_cls}"><div class="num">{len(r.missing_in_target):,}</div><div class="lbl">Missing in Target</div></div>
      <div class="stat{extra_cls}"><div class="num">{len(r.extra_in_target):,}</div><div class="lbl">Extra in Target</div></div>
      <div class="stat{fmm_cls}"><div class="num">{r.total_field_mismatches:,}</div><div class="lbl">Field Mismatches</div></div>
    </div>"""

    # Field-level table
    field_rows = ""
    for f in r.field_results:
        mm_cls = " class='field-row-mismatch'" if f.mismatched else ""
        flag   = "❌ " if f.mismatched else "✅ "
        field_rows += f"""
        <tr{mm_cls}>
          <td>{flag}{_e(f.source_column)}</td>
          <td>{_e(f.target_column)}</td>
          <td>{_e(f.transformation)}</td>
          <td style="text-align:right">{f.matched:,}</td>
          <td style="text-align:right;{'color:#dc2626;font-weight:700' if f.mismatched else ''}">{f.mismatched:,}</td>
          <td style="text-align:right">{f.null_in_source:,}</td>
          <td style="text-align:right">{f.null_in_target:,}</td>
        </tr>"""

    field_section = ""
    if r.field_results:
        field_section = f"""
        <div class="section-heading">Field-Level Results</div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Source Column</th><th>Target Column</th><th>Transformation</th>
                <th style="text-align:right">Matched</th>
                <th style="text-align:right">Mismatched</th>
                <th style="text-align:right">Src Nulls</th>
                <th style="text-align:right">Tgt Nulls</th>
              </tr>
            </thead>
            <tbody>{field_rows}</tbody>
          </table>
        </div>"""

    # Diff table (Table 2)
    diff_section = f'<div class="section-heading">Row-Level Discrepancy Detail</div>{_render_diff_table(r)}'

    # SQL
    sql_blocks = "".join(f'<div class="sql-block">{_e(s)}</div>' for s in r.generated_sql)
    sql_section = f'<div class="section-heading">Generated SQL</div>{sql_blocks}'

    # Warnings
    warn_section = ""
    if r.warnings:
        items = "".join(f"<li style='margin-bottom:4px'>• {_e(w)}</li>" for w in r.warnings)
        warn_section = f'<div class="section-heading">Warnings</div><div class="warn-box"><ul style="list-style:none">{items}</ul></div>'

    run_filter_html = (
        f'<span class="badge info">Filter: {_e(r.run_filter)}</span>' if r.run_filter else ""
    )

    return f"""
    <div class="card">
      <div class="card-header">
        <h2>{_e(r.pipeline_name)}</h2>
        <span class="badge {dir_cls}">{r.direction}</span>
        <span class="badge {status_cls}">{status_txt}</span>
        {run_filter_html}
      </div>
      <div class="card-body">
        <div style="font-size:0.78rem;color:#64748b;margin-bottom:14px">
          {_e(r.source_table)} {arrow} {_e(r.target_table)}
          &nbsp;|&nbsp; Generated: {_e(r.generated_at)}
        </div>
        {stats_html}
        {field_section}
        {diff_section}
        {warn_section}
        {sql_section}
      </div>
    </div>"""


def to_html(
    reports: list["RunReconcileReport"],
    output_path: str,
    project: str = "Pipeline Reconciliation",
) -> str:
    """
    Generate a self-contained HTML reconciliation report.

    Includes:
      - Table 1: Summary overview — success/error counts per pipeline
      - Table 2: Side-by-side source vs target data with comment column per discrepancy

    Args:
        reports:     List of RunReconcileReport objects (one per pipeline/table).
        output_path: Where to write the .html file.
        project:     Project / run name shown in the report header.

    Returns:
        Path to the written HTML file.

    Example:
        from reconpilot.report import to_html
        to_html([result1, result2], "recon_report.html", project="Supplier_Migration_2026-05-27")
    """
    total    = len(reports)
    clean    = sum(1 for r in reports if r.is_clean)
    issues   = total - clean
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    overall_pill = (
        f'<span class="pill clean">✅ All {total} pipelines clean</span>'
        if issues == 0 else
        f'<span class="pill issues">❌ {issues} pipeline{"s" if issues!=1 else ""} with issues</span>'
        f'<span class="pill clean">✅ {clean} clean</span>'
    )

    summary_table = _render_summary_table(reports)
    pipeline_cards = "".join(_render_pipeline_card(r) for r in reports)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(project)} — pipe-recon Report</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <h1>🔍 {_e(project)}</h1>
    <div class="meta">pipe-recon reconciliation report &nbsp;|&nbsp; Generated: {gen_time}</div>
  </div>
  <div class="summary-banner">
    {overall_pill}
    <span class="pill info">{total} Pipeline{'s' if total!=1 else ''}</span>
  </div>
  <div class="content">
    {summary_table}
    <div class="section-heading">Pipeline Detail</div>
    {pipeline_cards}
  </div>
  <div class="footer">
    Generated by <strong>pipe-recon</strong> — github.com/bhupendra05/pipe-recon
  </div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path

"""
reconpilot.report — HTML report generator for pipeline reconciliation runs.

Produces a self-contained, professional HTML report suitable for attaching to a
JIRA ticket, emailing to stakeholders, or storing as a run artifact.
"""

from __future__ import annotations
import html as _html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reconpilot.reconciler import RunReconcileReport


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f4f6fa; color: #1a1a2e; }
.header { background: linear-gradient(135deg, #1e3a5f, #2563eb); color: white; padding: 32px 40px; }
.header h1 { font-size: 1.6rem; font-weight: 700; }
.header .meta { font-size: 0.85rem; opacity: 0.8; margin-top: 6px; }
.summary-bar { display: flex; gap: 12px; padding: 20px 40px; background: white; border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }
.pill { padding: 6px 16px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }
.pill.clean  { background: #d1fae5; color: #065f46; }
.pill.issues { background: #fee2e2; color: #991b1b; }
.pill.info   { background: #dbeafe; color: #1e40af; }
.content { padding: 24px 40px; }
.pipeline-card { background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; overflow: hidden; border: 1px solid #e2e8f0; }
.pipeline-header { padding: 16px 20px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #f1f5f9; background: #f8fafc; }
.pipeline-header h2 { font-size: 1rem; font-weight: 700; flex: 1; }
.badge { padding: 3px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.badge.clean  { background: #d1fae5; color: #065f46; }
.badge.issues { background: #fee2e2; color: #991b1b; }
.badge.inbound  { background: #dbeafe; color: #1e40af; }
.badge.outbound { background: #ede9fe; color: #5b21b6; }
.pipeline-body { padding: 20px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat { background: #f8fafc; border-radius: 8px; padding: 12px; text-align: center; border: 1px solid #e2e8f0; }
.stat .num  { font-size: 1.5rem; font-weight: 700; color: #1e3a5f; }
.stat .lbl  { font-size: 0.72rem; color: #64748b; margin-top: 2px; }
.stat.bad   { background: #fff1f2; border-color: #fecdd3; }
.stat.bad .num { color: #be123c; }
.section-title { font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #64748b; margin: 16px 0 8px; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th { background: #f1f5f9; padding: 8px 12px; text-align: left; font-weight: 600; color: #475569; }
td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; }
tr.mismatch td { background: #fff7ed; }
tr:hover td { background: #f8fafc; }
.key-list { background: #fff1f2; border-radius: 6px; padding: 10px 14px; font-family: monospace; font-size: 0.8rem; color: #be123c; }
.sql-block { background: #1e293b; color: #94a3b8; border-radius: 8px; padding: 14px; font-family: monospace; font-size: 0.78rem; white-space: pre-wrap; word-break: break-all; margin-bottom: 8px; }
.warn-list { background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 10px 14px; font-size: 0.82rem; color: #92400e; }
.footer { text-align: center; padding: 20px; color: #94a3b8; font-size: 0.75rem; }
"""


def to_html(
    reports: list["RunReconcileReport"],
    output_path: str,
    project: str = "Pipeline Reconciliation",
) -> str:
    """
    Generate a self-contained HTML reconciliation report.

    Args:
        reports:     List of RunReconcileReport objects (one per pipeline/table).
        output_path: Where to write the .html file.
        project:     Project / run name shown in the report header.

    Returns:
        Path to the written HTML file.

    Example:
        from reconpilot.report import to_html
        to_html([result1, result2], "recon_report.html", project="CRM_Migration_2026-05-27")
    """
    total    = len(reports)
    clean    = sum(1 for r in reports if r.is_clean)
    issues   = total - clean
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _e(s): return _html.escape(str(s))

    cards = []
    for r in reports:
        status_cls = "clean" if r.is_clean else "issues"
        status_txt = "✅ CLEAN" if r.is_clean else "❌ ISSUES"
        dir_cls    = "inbound" if r.direction == "INBOUND" else "outbound"
        arrow      = "→" if r.direction == "INBOUND" else "←"

        # Stats row
        cnt_cls = "" if r.source_count == r.target_count else " bad"
        miss_cls = " bad" if r.missing_in_target else ""
        extra_cls = " bad" if r.extra_in_target else ""
        fmm_cls  = " bad" if r.total_field_mismatches > 0 else ""

        stats_html = f"""
        <div class="stats-grid">
          <div class="stat"><div class="num">{r.source_count:,}</div><div class="lbl">Source Rows</div></div>
          <div class="stat{cnt_cls}"><div class="num">{r.target_count:,}</div><div class="lbl">Target Rows</div></div>
          <div class="stat"><div class="num">{r.matched_keys:,}</div><div class="lbl">Matched Keys</div></div>
          <div class="stat{miss_cls}"><div class="num">{len(r.missing_in_target):,}</div><div class="lbl">Missing in Target</div></div>
          <div class="stat{extra_cls}"><div class="num">{len(r.extra_in_target):,}</div><div class="lbl">Extra in Target</div></div>
          <div class="stat{fmm_cls}"><div class="num">{r.total_field_mismatches:,}</div><div class="lbl">Field Mismatches</div></div>
        </div>
        """

        # Field table
        field_rows = ""
        for f in r.field_results:
            mm_cls = " class='mismatch'" if f.mismatched else ""
            flag   = "❌ " if f.mismatched else ""
            field_rows += f"""
            <tr{mm_cls}>
              <td>{flag}{_e(f.source_column)}</td>
              <td>{_e(f.target_column)}</td>
              <td>{_e(f.transformation)}</td>
              <td style="text-align:right">{f.matched:,}</td>
              <td style="text-align:right; color:{'#dc2626' if f.mismatched else 'inherit'}">{f.mismatched:,}</td>
              <td style="text-align:right">{f.null_in_source:,}</td>
              <td style="text-align:right">{f.null_in_target:,}</td>
            </tr>"""
            for d in f.sample_diffs[:3]:
                field_rows += f"""
            <tr style="font-size:0.75rem; background:#fff7ed">
              <td colspan="2" style="padding-left:24px; color:#9a3412">
                key={_e(d['key'])}
              </td>
              <td colspan="2" style="color:#166534">src: {_e(d['source'])!r}</td>
              <td colspan="3" style="color:#991b1b">tgt: {_e(d['target'])!r}</td>
            </tr>"""

        field_section = ""
        if r.field_results:
            field_section = f"""
            <div class="section-title">Field-Level Results</div>
            <table>
              <thead>
                <tr>
                  <th>Source Column</th><th>Target Column</th><th>Transform</th>
                  <th style="text-align:right">Matched</th>
                  <th style="text-align:right">Mismatch</th>
                  <th style="text-align:right">Src Null</th>
                  <th style="text-align:right">Tgt Null</th>
                </tr>
              </thead>
              <tbody>{field_rows}</tbody>
            </table>"""

        # Missing keys
        missing_section = ""
        if r.missing_in_target:
            keys_str = ", ".join(_e(str(k)) for k in r.missing_in_target[:20])
            more = f"  … and {len(r.missing_in_target)-20} more" if len(r.missing_in_target) > 20 else ""
            missing_section = f"""
            <div class="section-title">Missing in Target ({len(r.missing_in_target):,} keys)</div>
            <div class="key-list">{keys_str}{more}</div>"""

        # Extra in target
        extra_section = ""
        if r.extra_in_target:
            keys_str = ", ".join(_e(str(k)) for k in r.extra_in_target[:20])
            more = f"  … and {len(r.extra_in_target)-20} more" if len(r.extra_in_target) > 20 else ""
            extra_section = f"""
            <div class="section-title">Extra in Target — possible double-load ({len(r.extra_in_target):,} keys)</div>
            <div class="key-list">{keys_str}{more}</div>"""

        # Generated SQL
        sql_section = ""
        if r.generated_sql:
            sql_blocks = "".join(f'<div class="sql-block">{_e(s)}</div>' for s in r.generated_sql)
            sql_section = f'<div class="section-title">Generated SQL</div>{sql_blocks}'

        # Warnings
        warn_section = ""
        if r.warnings:
            items = "".join(f"<li>• {_e(w)}</li>" for w in r.warnings)
            warn_section = f'<div class="section-title">Warnings</div><div class="warn-list"><ul style="list-style:none">{items}</ul></div>'

        run_filter_html = f'<span class="badge info">Filter: {_e(r.run_filter)}</span>' if r.run_filter else ""

        cards.append(f"""
        <div class="pipeline-card">
          <div class="pipeline-header">
            <h2>{_e(r.pipeline_name)}</h2>
            <span class="badge {dir_cls}">{r.direction}</span>
            <span class="badge {status_cls}">{status_txt}</span>
            {run_filter_html}
          </div>
          <div class="pipeline-body">
            <div style="font-size:0.82rem; color:#64748b; margin-bottom:12px">
              {_e(r.source_table)} {arrow} {_e(r.target_table)} &nbsp;|&nbsp; Generated: {_e(r.generated_at)}
            </div>
            {stats_html}
            {field_section}
            {missing_section}
            {extra_section}
            {warn_section}
            {sql_section}
          </div>
        </div>""")

    overall_pill = f'<span class="pill clean">✅ {clean}/{total} Clean</span>' if issues == 0 else \
                   f'<span class="pill issues">❌ {issues}/{total} Issues</span><span class="pill clean">✅ {clean}/{total} Clean</span>'

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
  <div class="summary-bar">
    {overall_pill}
    <span class="pill info">{total} Pipeline{'s' if total != 1 else ''}</span>
  </div>
  <div class="content">
    {''.join(cards)}
  </div>
  <div class="footer">
    Generated by <strong>pipe-recon</strong> — github.com/bhupendra05/pipe-recon
  </div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path

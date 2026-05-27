"""
reconpilot.reconciler — mapping-aware, run-based reconciliation engine.

Supports:
  - INBOUND  (source → target): data flowing from source system to target/DW
  - OUTBOUND (target → source): data flowing back from DW to source system
  - Run-scoped: reconcile only the latest batch/run, not the whole table
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from reconpilot.mapping import MappingDocument, FieldMapping
from reconpilot.connection import Connection


@dataclass
class FieldResult:
    source_column: str
    target_column: str
    transformation: str
    matched: int
    mismatched: int
    null_in_source: int
    null_in_target: int
    sample_diffs: list[dict]  # [{key, source_value, target_value}]


@dataclass
class RunReconcileReport:
    pipeline_name: str
    direction: str           # INBOUND | OUTBOUND
    source_table: str
    target_table: str
    run_filter: Optional[str]
    generated_at: str

    source_count: int
    target_count: int
    matched_keys: int
    missing_in_target: list
    extra_in_target: list
    field_results: list[FieldResult]

    warnings: list[str] = field(default_factory=list)
    generated_sql: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return (
            self.source_count == self.target_count
            and not self.missing_in_target
            and not self.extra_in_target
            and all(f.mismatched == 0 for f in self.field_results)
        )

    @property
    def total_field_mismatches(self) -> int:
        return sum(f.mismatched for f in self.field_results)

    def print(self):
        status = "✅ CLEAN" if self.is_clean else "❌ ISSUES FOUND"
        arrow = "→" if self.direction == "INBOUND" else "←"
        print(f"\n🔍  {self.pipeline_name}  [{self.direction}]  [{status}]")
        print(f"    {self.source_table} {arrow} {self.target_table}")
        if self.run_filter:
            print(f"    Filter: {self.run_filter}")
        print(f"    Generated: {self.generated_at}")
        print()
        print(f"    Source rows : {self.source_count:,}")
        print(f"    Target rows : {self.target_count:,}  {'✅' if self.source_count == self.target_count else '❌ COUNT MISMATCH'}")
        print(f"    Matched keys: {self.matched_keys:,}")

        if self.missing_in_target:
            print(f"\n    ❌ Missing in target: {len(self.missing_in_target):,}")
            for k in self.missing_in_target[:5]:
                print(f"       key = {k}")

        if self.extra_in_target:
            print(f"\n    ⚠️  Extra in target (possible double-load): {len(self.extra_in_target):,}")

        if self.field_results:
            print(f"\n    {'Field (src→tgt)':<35} {'Transform':<25} {'Matched':>8} {'Mismatch':>9} {'Src-Null':>9} {'Tgt-Null':>9}")
            print("    " + "-" * 100)
            for f in self.field_results:
                flag = "❌ " if f.mismatched else "   "
                label = f"{f.source_column}→{f.target_column}"
                print(
                    f"    {flag}{label:<33} {f.transformation[:24]:<25} "
                    f"{f.matched:>8,} {f.mismatched:>8,}  "
                    f"{f.null_in_source:>8,} {f.null_in_target:>8,}"
                )
                for d in f.sample_diffs[:2]:
                    print(f"         key={d['key']}  src={d['source']!r}  tgt={d['target']!r}")

        if self.warnings:
            print(f"\n    ⚠️  Warnings:")
            for w in self.warnings:
                print(f"       • {w}")

    def to_dict(self) -> dict:
        return {
            "pipeline_name": self.pipeline_name,
            "direction": self.direction,
            "source_table": self.source_table,
            "target_table": self.target_table,
            "run_filter": self.run_filter,
            "generated_at": self.generated_at,
            "is_clean": self.is_clean,
            "source_count": self.source_count,
            "target_count": self.target_count,
            "matched_keys": self.matched_keys,
            "missing_in_target_count": len(self.missing_in_target),
            "extra_in_target_count": len(self.extra_in_target),
            "total_field_mismatches": self.total_field_mismatches,
            "missing_in_target": [str(k) for k in self.missing_in_target[:50]],
            "extra_in_target": [str(k) for k in self.extra_in_target[:50]],
            "fields": [
                {
                    "source_column": f.source_column,
                    "target_column": f.target_column,
                    "transformation": f.transformation,
                    "matched": f.matched,
                    "mismatched": f.mismatched,
                    "null_in_source": f.null_in_source,
                    "null_in_target": f.null_in_target,
                    "sample_diffs": f.sample_diffs[:5],
                }
                for f in self.field_results
            ],
            "generated_sql": self.generated_sql,
            "warnings": self.warnings,
        }


def _apply_transform_check(src_val, tgt_val, transform: str) -> bool:
    """
    Check if source value matches target value after transformation.
    Returns True if values are reconciled (match after transform).
    """
    transform_lower = transform.strip().lower()

    if transform_lower in ("direct", "none", "", "as-is", "as is"):
        return str(src_val) == str(tgt_val)

    if transform_lower in ("trim",):
        return str(src_val).strip() == str(tgt_val).strip()

    if transform_lower in ("upper",):
        return str(src_val).upper() == str(tgt_val).upper()

    if transform_lower in ("lower",):
        return str(src_val).lower() == str(tgt_val).lower()

    if "date_format" in transform_lower:
        # Best effort: compare as string after stripping separators
        clean_src = re.sub(r'[-/.]', '', str(src_val))
        clean_tgt = re.sub(r'[-/.]', '', str(tgt_val))
        return clean_src == clean_tgt

    if "lookup" in transform_lower:
        # lookup: A=Active,I=Inactive — check the reverse mapping
        try:
            lookup_map = {}
            _, pairs = transform.split(":", 1)
            for pair in pairs.split(","):
                k, v = pair.strip().split("=", 1)
                lookup_map[k.strip()] = v.strip()
            expected = lookup_map.get(str(src_val), str(src_val))
            return expected == str(tgt_val)
        except Exception:
            pass

    # Unknown transform — fall back to string compare
    return str(src_val) == str(tgt_val)


import re  # needed by _apply_transform_check


def reconcile_from_mapping(
    mapping_doc: MappingDocument,
    source_conn: Connection,
    target_conn: Connection,
    source_table: str,
    direction: str = "INBOUND",
    pipeline_name: str = "",
    run_filter: str | None = None,
    sample: int | None = None,
) -> RunReconcileReport:
    """
    Reconcile a table using its field mapping document.

    Args:
        mapping_doc:   Parsed MappingDocument from load_mapping().
        source_conn:   Connection to source system.
        target_conn:   Connection to target system.
        source_table:  Which source table to reconcile.
        direction:     "INBOUND" (src→tgt) or "OUTBOUND" (tgt→src).
        pipeline_name: Display name for this pipeline.
        run_filter:    Optional WHERE clause to scope to latest run.
                       e.g. "load_date = '2026-05-27'" or "batch_id = 1042"
        sample:        If set, only sample N rows.

    Returns:
        RunReconcileReport with full field-level diff.

    Example:
        from reconpilot import load_mapping, connect_dsn, reconcile_from_mapping

        doc = load_mapping("mapping/CRM_Field_Mapping.csv")
        src = connect_dsn("postgresql://user:pass@source/crm", name="CRM")
        tgt = connect_dsn("postgresql://user:pass@target/dw",  name="DW")

        result = reconcile_from_mapping(
            doc, src, tgt,
            source_table="CUSTOMER",
            direction="INBOUND",
            pipeline_name="CRM_Customer_Load",
            run_filter="load_date = CURRENT_DATE",
        )
        result.print()
    """
    mappings = mapping_doc.for_table(source_table)
    if not mappings:
        raise ValueError(
            f"No mappings found for source table '{source_table}'. "
            f"Available tables: {mapping_doc.tables}"
        )

    target_table = mappings[0].target_table
    src_keys = [m.source_column for m in mappings if m.is_key]
    tgt_keys = [m.target_column for m in mappings if m.is_key]

    if not src_keys:
        raise ValueError(
            f"No key field defined in mapping for '{source_table}'. "
            f"Mark at least one field as is_key=yes in the mapping document."
        )

    name = pipeline_name or f"{source_table}→{target_table}"
    warnings = []

    # Build SELECT queries from mapping
    src_select_cols = [m.source_column for m in mappings]
    tgt_select_cols = [m.target_column for m in mappings]

    src_cols_sql  = ", ".join(src_select_cols)
    tgt_cols_sql  = ", ".join(tgt_select_cols)
    src_key_col   = src_keys[0]
    tgt_key_col   = tgt_keys[0]

    # run_filter is scoped to the source table columns.
    # For INBOUND: filter the source side (CRM/Oracle) by batch marker.
    # For OUTBOUND: filter the target side (DW) by batch marker — connections swap below.
    src_where = f" WHERE {run_filter}" if run_filter else ""
    tgt_where = ""   # target filter only if caller needs it (use run_filter on src side)

    src_sql = f"SELECT {src_cols_sql} FROM {source_table}{src_where}"
    tgt_sql = f"SELECT {tgt_cols_sql} FROM {target_table}{tgt_where}"

    generated_sql = [
        f"-- Source reconciliation query\n{src_sql};",
        f"-- Target reconciliation query\n{tgt_sql};",
        f"-- Count check\nSELECT COUNT(*) FROM {source_table}{src_where};",
        f"SELECT COUNT(*) FROM {target_table}{tgt_where};",
    ]

    # For OUTBOUND: target is the authoritative side that pushes data back to source.
    # Swap which connection is queried with which SQL so each DB gets its own column names.
    # After swapping, src_rows will contain target-table data, tgt_rows will contain source-table data.
    if direction.upper() == "OUTBOUND":
        # Swap BOTH connections and SQL so each DB receives queries with its own column names.
        # After swap: source_conn (now old target) queries tgt_sql (target columns) ✓
        #             target_conn (now old source) queries src_sql (source columns) ✓
        source_conn, target_conn = target_conn, source_conn
        src_sql, tgt_sql = tgt_sql, src_sql
        src_key_col, tgt_key_col = tgt_key_col, src_key_col
        mappings = [
            FieldMapping(
                source_table=m.target_table, source_column=m.target_column,
                target_table=m.source_table, target_column=m.source_column,
                transformation=m.transformation, is_key=m.is_key,
                nullable=m.nullable, data_type=m.data_type,
            )
            for m in mappings
        ]

    # Fetch data
    try:
        src_rows = source_conn.query(src_sql)
    except Exception as e:
        raise RuntimeError(f"Failed to query source ({source_conn.name}): {e}")

    try:
        tgt_rows = target_conn.query(tgt_sql)
    except Exception as e:
        raise RuntimeError(f"Failed to query target ({target_conn.name}): {e}")

    if sample and sample < len(src_rows):
        import random
        src_rows = random.sample(src_rows, sample)

    src_index = {str(r.get(src_key_col, r.get(src_key_col.lower(), ""))): r for r in src_rows}
    tgt_index = {str(r.get(tgt_key_col, r.get(tgt_key_col.lower(), ""))): r for r in tgt_rows}

    src_keys_set = set(src_index)
    tgt_keys_set = set(tgt_index)

    missing_in_target = sorted(src_keys_set - tgt_keys_set)
    extra_in_target   = sorted(tgt_keys_set - src_keys_set)
    matched_keys      = src_keys_set & tgt_keys_set

    # Field-level reconciliation
    field_results = []
    for m in mappings:
        if m.is_key:
            continue

        src_c = m.source_column.lower()
        tgt_c = m.target_column.lower()

        matched = mismatched = null_src = null_tgt = 0
        sample_diffs = []

        for key in matched_keys:
            sr = src_index[key]
            tr = tgt_index[key]
            sv = sr.get(m.source_column) or sr.get(src_c)
            tv = tr.get(m.target_column) or tr.get(tgt_c)

            if sv is None:
                null_src += 1
            if tv is None:
                null_tgt += 1

            if sv is None and tv is None:
                matched += 1
                continue

            if _apply_transform_check(sv, tv, m.transformation):
                matched += 1
            else:
                mismatched += 1
                if len(sample_diffs) < 5:
                    sample_diffs.append({"key": key, "source": sv, "target": tv})

        field_results.append(FieldResult(
            source_column=m.source_column,
            target_column=m.target_column,
            transformation=m.transformation,
            matched=matched,
            mismatched=mismatched,
            null_in_source=null_src,
            null_in_target=null_tgt,
            sample_diffs=sample_diffs,
        ))

        if mismatched > 0 and not m.nullable and null_tgt > 0:
            warnings.append(f"Field {m.target_column}: NOT NULL in mapping but {null_tgt} nulls in target")

    return RunReconcileReport(
        pipeline_name=name,
        direction=direction.upper(),
        source_table=source_table,
        target_table=target_table,
        run_filter=run_filter,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source_count=len(src_rows),
        target_count=len(tgt_rows),
        matched_keys=len(matched_keys),
        missing_in_target=missing_in_target,
        extra_in_target=extra_in_target,
        field_results=field_results,
        warnings=warnings,
        generated_sql=generated_sql,
    )

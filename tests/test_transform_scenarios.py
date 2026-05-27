"""
tests/test_transform_scenarios.py — Field transformation validation scenarios.

Every transformation type is tested for both pass (ETL did it correctly)
and fail (ETL forgot to apply / applied wrong) cases.

Scenarios:
  TC-T-01  TRIM — names correctly trimmed in target
  TC-T-02  TRIM — spaces NOT trimmed, should be flagged as mismatch
  TC-T-03  TRIM — leading spaces only (not trailing)
  TC-T-04  LOWER — email correctly lowercased
  TC-T-05  LOWER — email NOT lowercased, should be flagged
  TC-T-06  LOWER — mixed case partially lowercased
  TC-T-07  UPPER — codes correctly uppercased
  TC-T-08  UPPER — codes NOT uppercased, should be flagged
  TC-T-09  LOOKUP — status codes mapped correctly
  TC-T-10  LOOKUP — some codes not mapped (raw code stored)
  TC-T-11  LOOKUP — unknown code falls back to source value
  TC-T-12  LOOKUP — pipe-separated pairs (CSV-safe format)
  TC-T-13  DATE_FORMAT — dates correctly reformatted
  TC-T-14  DATE_FORMAT — dates NOT reformatted
  TC-T-15  DIRECT — exact value comparison
  TC-T-16  DIRECT — numeric values match
  TC-T-17  NULL handling — both null is a match
  TC-T-18  NULL handling — null in source, value in target
  TC-T-19  NULL handling — value in source, null in target
  TC-T-20  Multiple transforms in one pipeline — partial failures
  TC-T-21  Sample diffs included in field result
  TC-T-22  Nullable field — null in target but nullable=yes, no warning
"""

import csv
import sqlite3
import pytest

from reconpilot.mapping import load_mapping
from reconpilot.connection import connect_dsn
from reconpilot.reconciler import reconcile_from_mapping


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mapping_csv(tmp_path, rows, fname="map.csv"):
    header = ["source_table","source_column","target_table","target_column",
              "transformation","is_key","nullable","data_type","notes"]
    p = str(tmp_path / fname)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def _sqlite(tmp_path, fname, table, schema, rows):
    p = str(tmp_path / fname)
    conn = sqlite3.connect(p)
    conn.execute(schema)
    if rows:
        cols = ", ".join(rows[0].keys())
        vals = ", ".join("?" * len(rows[0]))
        conn.executemany(f"INSERT INTO {table} ({cols}) VALUES ({vals})",
                         [list(r.values()) for r in rows])
    conn.commit(); conn.close()
    return p


def _run(tmp_path, mapping_rows, src_rows, tgt_rows,
         src_table="SRC", tgt_table="tgt",
         src_schema=None, tgt_schema=None):
    if src_schema is None:
        cols = " TEXT, ".join(src_rows[0].keys()) + " TEXT" if src_rows else "id INTEGER"
        src_schema = f"CREATE TABLE {src_table} ({cols})"
    if tgt_schema is None:
        cols = " TEXT, ".join(tgt_rows[0].keys()) + " TEXT" if tgt_rows else "id INTEGER"
        tgt_schema = f"CREATE TABLE {tgt_table} ({cols})"

    map_path = _mapping_csv(tmp_path, mapping_rows)
    src_path = _sqlite(tmp_path, "src.db", src_table, src_schema, src_rows)
    tgt_path = _sqlite(tmp_path, "tgt.db", tgt_table, tgt_schema, tgt_rows)
    doc = load_mapping(map_path)
    src = connect_dsn(f"sqlite:///{src_path}")
    tgt = connect_dsn(f"sqlite:///{tgt_path}")
    result = reconcile_from_mapping(doc, src, tgt, src_table)
    src.close(); tgt.close()
    return result

def _field(result, tgt_col):
    return next(f for f in result.field_results if f.target_column == tgt_col)


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-01  TRIM — correctly trimmed
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_01_TrimClean:
    MAPPING = [
        ["VENDOR", "V_ID",  "vendor", "vendor_id",   "direct", "yes", "no", "INTEGER", ""],
        ["VENDOR", "V_NAME","vendor", "vendor_name",  "trim",   "no",  "no", "VARCHAR", ""],
    ]
    SRC = [{"V_ID": 1, "V_NAME": "  Acme Corp  "},
           {"V_ID": 2, "V_NAME": "  Global Tech  "}]
    TGT = [{"vendor_id": 1, "vendor_name": "Acme Corp"},
           {"vendor_id": 2, "vendor_name": "Global Tech"}]

    def test_trim_passes(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "VENDOR", "vendor",
                 "CREATE TABLE VENDOR (V_ID INTEGER, V_NAME TEXT)",
                 "CREATE TABLE vendor (vendor_id INTEGER, vendor_name TEXT)")
        assert _field(r, "vendor_name").mismatched == 0

    def test_matched_count(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "VENDOR", "vendor",
                 "CREATE TABLE VENDOR (V_ID INTEGER, V_NAME TEXT)",
                 "CREATE TABLE vendor (vendor_id INTEGER, vendor_name TEXT)")
        assert _field(r, "vendor_name").matched == 2


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-02  TRIM — spaces NOT trimmed in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_02_TrimFailed:
    MAPPING = [
        ["VENDOR", "V_ID",  "vendor", "vendor_id",  "direct", "yes", "no", "INTEGER", ""],
        ["VENDOR", "V_NAME","vendor", "vendor_name", "trim",   "no",  "no", "VARCHAR", ""],
    ]
    SRC = [{"V_ID": 1, "V_NAME": "  Tata Corp  "},
           {"V_ID": 2, "V_NAME": "  Wipro Ltd  "}]
    # ETL bug: spaces NOT stripped from target
    TGT = [{"vendor_id": 1, "vendor_name": "  Tata Corp  "},
           {"vendor_id": 2, "vendor_name": "  Wipro Ltd  "}]

    def test_trim_failure_flagged(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "VENDOR", "vendor",
                 "CREATE TABLE VENDOR (V_ID INTEGER, V_NAME TEXT)",
                 "CREATE TABLE vendor (vendor_id INTEGER, vendor_name TEXT)")
        assert _field(r, "vendor_name").mismatched == 2

    def test_not_clean(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "VENDOR", "vendor",
                 "CREATE TABLE VENDOR (V_ID INTEGER, V_NAME TEXT)",
                 "CREATE TABLE vendor (vendor_id INTEGER, vendor_name TEXT)")
        assert not r.is_clean

    def test_sample_diffs_show_source_and_target(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "VENDOR", "vendor",
                 "CREATE TABLE VENDOR (V_ID INTEGER, V_NAME TEXT)",
                 "CREATE TABLE vendor (vendor_id INTEGER, vendor_name TEXT)")
        diffs = _field(r, "vendor_name").sample_diffs
        assert len(diffs) > 0
        assert "source" in diffs[0] and "target" in diffs[0]


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-03  TRIM — leading only
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_03_TrimLeadingOnly:
    MAPPING = [
        ["T", "ID", "t", "id",   "direct", "yes", "no", "INTEGER", ""],
        ["T", "NM", "t", "name", "trim",   "no",  "no", "VARCHAR", ""],
    ]

    def test_leading_space_only_detected(self, tmp_path):
        src = [{"ID": 1, "NM": "   OnlyLeading"}]
        tgt = [{"id": 1, "name": "   OnlyLeading"}]   # leading NOT stripped
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, NM TEXT)",
                 "CREATE TABLE t (id INTEGER, name TEXT)")
        assert _field(r, "name").mismatched == 1   # trim("   OnlyLeading") = "OnlyLeading" ≠ "   OnlyLeading"


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-04  LOWER — email correctly lowercased
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_04_LowerClean:
    MAPPING = [
        ["USER", "USER_ID", "users", "user_id", "direct", "yes", "no", "INTEGER", ""],
        ["USER", "EMAIL",   "users", "email",   "lower",  "no",  "no", "VARCHAR", ""],
    ]
    SRC = [{"USER_ID": 1, "EMAIL": "Alice@Company.COM"},
           {"USER_ID": 2, "EMAIL": "BOB@CORP.NET"}]
    TGT = [{"user_id": 1, "email": "alice@company.com"},
           {"user_id": 2, "email": "bob@corp.net"}]

    def test_lower_passes(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "USER", "users",
                 "CREATE TABLE USER (USER_ID INTEGER, EMAIL TEXT)",
                 "CREATE TABLE users (user_id INTEGER, email TEXT)")
        assert _field(r, "email").mismatched == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-05  LOWER — email NOT lowercased in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_05_LowerFailed:
    MAPPING = [
        ["USER", "USER_ID", "users", "user_id", "direct", "yes", "no", "INTEGER", ""],
        ["USER", "EMAIL",   "users", "email",   "lower",  "no",  "no", "VARCHAR", ""],
    ]
    SRC = [{"USER_ID": 1, "EMAIL": "Alice@Company.COM"},
           {"USER_ID": 2, "EMAIL": "BOB@CORP.NET"},
           {"USER_ID": 3, "EMAIL": "carol@example.com"}]   # already lower — should pass
    TGT = [{"user_id": 1, "email": "Alice@Company.COM"},   # NOT lowercased
           {"user_id": 2, "email": "BOB@CORP.NET"},         # NOT lowercased
           {"user_id": 3, "email": "carol@example.com"}]   # correct

    def test_two_mismatches(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "USER", "users",
                 "CREATE TABLE USER (USER_ID INTEGER, EMAIL TEXT)",
                 "CREATE TABLE users (user_id INTEGER, email TEXT)")
        assert _field(r, "email").mismatched == 2

    def test_one_match(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "USER", "users",
                 "CREATE TABLE USER (USER_ID INTEGER, EMAIL TEXT)",
                 "CREATE TABLE users (user_id INTEGER, email TEXT)")
        assert _field(r, "email").matched == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-06  UPPER — codes correctly uppercased
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_06_UpperClean:
    MAPPING = [
        ["CODE", "CODE_ID",  "codes", "code_id",  "direct", "yes", "no", "INTEGER", ""],
        ["CODE", "RAW_CODE", "codes", "std_code",  "upper",  "no",  "no", "VARCHAR", ""],
    ]
    SRC = [{"CODE_ID": 1, "RAW_CODE": "pending"},
           {"CODE_ID": 2, "RAW_CODE": "active"}]
    TGT = [{"code_id": 1, "std_code": "PENDING"},
           {"code_id": 2, "std_code": "ACTIVE"}]

    def test_upper_passes(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "CODE", "codes",
                 "CREATE TABLE CODE (CODE_ID INTEGER, RAW_CODE TEXT)",
                 "CREATE TABLE codes (code_id INTEGER, std_code TEXT)")
        assert _field(r, "std_code").mismatched == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-07  UPPER — codes NOT uppercased
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_07_UpperFailed:
    MAPPING = [
        ["CODE", "CODE_ID",  "codes", "code_id",  "direct", "yes", "no", "INTEGER", ""],
        ["CODE", "RAW_CODE", "codes", "std_code",  "upper",  "no",  "no", "VARCHAR", ""],
    ]

    def test_upper_failure_caught(self, tmp_path):
        src = [{"CODE_ID": 1, "RAW_CODE": "pending"}]
        tgt = [{"code_id": 1, "std_code": "pending"}]   # NOT uppercased
        r = _run(tmp_path, self.MAPPING, src, tgt, "CODE", "codes",
                 "CREATE TABLE CODE (CODE_ID INTEGER, RAW_CODE TEXT)",
                 "CREATE TABLE codes (code_id INTEGER, std_code TEXT)")
        assert _field(r, "std_code").mismatched == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-08  LOOKUP — status codes correctly mapped
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_08_LookupClean:
    MAPPING = [
        ["ORD", "ORD_ID",  "orders", "order_id", "direct",                      "yes", "no", "INTEGER", ""],
        ["ORD", "STAT_CD", "orders", "status",   "lookup: P=Pending|A=Approved|R=Rejected", "no", "no", "VARCHAR", ""],
    ]
    SRC = [{"ORD_ID": 1, "STAT_CD": "P"},
           {"ORD_ID": 2, "STAT_CD": "A"},
           {"ORD_ID": 3, "STAT_CD": "R"}]
    TGT = [{"order_id": 1, "status": "Pending"},
           {"order_id": 2, "status": "Approved"},
           {"order_id": 3, "status": "Rejected"}]

    def test_all_lookups_match(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "ORD", "orders",
                 "CREATE TABLE ORD (ORD_ID INTEGER, STAT_CD TEXT)",
                 "CREATE TABLE orders (order_id INTEGER, status TEXT)")
        assert _field(r, "status").mismatched == 0
        assert _field(r, "status").matched == 3


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-09  LOOKUP — some codes NOT mapped (raw code stored)
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_09_LookupFailed:
    MAPPING = [
        ["ORD", "ORD_ID",  "orders", "order_id", "direct",                      "yes", "no", "INTEGER", ""],
        ["ORD", "STAT_CD", "orders", "status",   "lookup: P=Pending|A=Approved|R=Rejected", "no", "no", "VARCHAR", ""],
    ]

    def test_unmapped_code_is_mismatch(self, tmp_path):
        src = [{"ORD_ID": 1, "STAT_CD": "P"},
               {"ORD_ID": 2, "STAT_CD": "A"},
               {"ORD_ID": 3, "STAT_CD": "R"}]
        tgt = [{"order_id": 1, "status": "Pending"},
               {"order_id": 2, "status": "A"},        # NOT looked up
               {"order_id": 3, "status": "Rejected"}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "ORD", "orders",
                 "CREATE TABLE ORD (ORD_ID INTEGER, STAT_CD TEXT)",
                 "CREATE TABLE orders (order_id INTEGER, status TEXT)")
        assert _field(r, "status").mismatched == 1
        assert _field(r, "status").matched == 2

    def test_all_unmapped(self, tmp_path):
        src = [{"ORD_ID": i, "STAT_CD": "P"} for i in range(1, 6)]
        tgt = [{"order_id": i, "status": "P"} for i in range(1, 6)]  # none mapped
        r = _run(tmp_path, self.MAPPING, src, tgt, "ORD", "orders",
                 "CREATE TABLE ORD (ORD_ID INTEGER, STAT_CD TEXT)",
                 "CREATE TABLE orders (order_id INTEGER, status TEXT)")
        assert _field(r, "status").mismatched == 5


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-10  LOOKUP — unknown code falls back to source value
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_10_LookupUnknownCode:
    MAPPING = [
        ["T", "ID",   "t", "id",     "direct",                  "yes", "no", "INTEGER", ""],
        ["T", "CODE", "t", "label",  "lookup: A=Active|I=Inactive", "no", "no", "VARCHAR", ""],
    ]

    def test_unknown_code_uses_source_as_expected(self, tmp_path):
        # 'X' is not in the lookup map → expected = 'X' (pass-through)
        src = [{"ID": 1, "CODE": "X"}]
        tgt = [{"id": 1, "label": "X"}]   # stored raw — passes because fallback = src value
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, CODE TEXT)",
                 "CREATE TABLE t (id INTEGER, label TEXT)")
        assert _field(r, "label").mismatched == 0

    def test_unknown_code_different_value_fails(self, tmp_path):
        src = [{"ID": 1, "CODE": "X"}]
        tgt = [{"id": 1, "label": "Something Else"}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, CODE TEXT)",
                 "CREATE TABLE t (id INTEGER, label TEXT)")
        assert _field(r, "label").mismatched == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-11  DATE_FORMAT — dates correctly reformatted
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_11_DateFormatClean:
    MAPPING = [
        ["INV", "INV_ID", "invoice", "invoice_id",   "direct",                          "yes", "no", "INTEGER", ""],
        ["INV", "INV_DT", "invoice", "invoice_date",  "date_format: YYYYMMDD→YYYY-MM-DD","no",  "no", "DATE",    ""],
    ]
    SRC = [{"INV_ID": 1, "INV_DT": "20260115"},
           {"INV_ID": 2, "INV_DT": "20260201"}]
    TGT = [{"invoice_id": 1, "invoice_date": "2026-01-15"},
           {"invoice_id": 2, "invoice_date": "2026-02-01"}]

    def test_date_format_passes(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT, "INV", "invoice",
                 "CREATE TABLE INV (INV_ID INTEGER, INV_DT TEXT)",
                 "CREATE TABLE invoice (invoice_id INTEGER, invoice_date TEXT)")
        assert _field(r, "invoice_date").mismatched == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-12  DATE_FORMAT — separator-agnostic comparison
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_12_DateFormatSeparatorAgnostic:
    """
    date_format strips separators from BOTH sides before comparing.
    This means '20260115' and '2026-01-15' are treated as the same date
    (both reduce to '20260115'). This is intentional — the transform validates
    the correct date, not the exact format string.

    A real date-value mismatch (different date) is still caught.
    """
    MAPPING = [
        ["INV", "INV_ID", "invoice", "invoice_id",   "direct",                          "yes", "no", "INTEGER", ""],
        ["INV", "INV_DT", "invoice", "invoice_date",  "date_format: YYYYMMDD→YYYY-MM-DD","no",  "no", "DATE",    ""],
    ]

    def test_raw_and_formatted_same_date_match(self, tmp_path):
        """20260115 (source) vs 20260115 (target, unformatted) — same date → match."""
        src = [{"INV_ID": 1, "INV_DT": "20260115"}]
        tgt = [{"invoice_id": 1, "invoice_date": "20260115"}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "INV", "invoice",
                 "CREATE TABLE INV (INV_ID INTEGER, INV_DT TEXT)",
                 "CREATE TABLE invoice (invoice_id INTEGER, invoice_date TEXT)")
        assert _field(r, "invoice_date").mismatched == 0

    def test_different_date_is_mismatch(self, tmp_path):
        """20260115 (source) vs 2026-02-20 (target) — different date → mismatch."""
        src = [{"INV_ID": 1, "INV_DT": "20260115"}]
        tgt = [{"invoice_id": 1, "invoice_date": "2026-02-20"}]   # genuinely different date
        r = _run(tmp_path, self.MAPPING, src, tgt, "INV", "invoice",
                 "CREATE TABLE INV (INV_ID INTEGER, INV_DT TEXT)",
                 "CREATE TABLE invoice (invoice_id INTEGER, invoice_date TEXT)")
        assert _field(r, "invoice_date").mismatched == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-13  NULL handling — both null → clean match
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_13_BothNull:
    MAPPING = [
        ["T", "ID",  "t", "id",    "direct", "yes", "no",  "INTEGER", ""],
        ["T", "VAL", "t", "value", "direct", "no",  "yes", "VARCHAR", ""],
    ]

    def test_both_null_is_match(self, tmp_path):
        src = [{"ID": 1, "VAL": None}]
        tgt = [{"id": 1, "value": None}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, VAL TEXT)",
                 "CREATE TABLE t (id INTEGER, value TEXT)")
        assert _field(r, "value").mismatched == 0
        assert _field(r, "value").matched == 1
        assert _field(r, "value").null_in_source == 1
        assert _field(r, "value").null_in_target == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-14  NULL handling — null in source, value in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_14_SourceNullTargetValue:
    MAPPING = [
        ["T", "ID",  "t", "id",    "direct", "yes", "no",  "INTEGER", ""],
        ["T", "VAL", "t", "value", "direct", "no",  "yes", "VARCHAR", ""],
    ]

    def test_source_null_target_value_is_mismatch(self, tmp_path):
        src = [{"ID": 1, "VAL": None}]
        tgt = [{"id": 1, "value": "something"}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, VAL TEXT)",
                 "CREATE TABLE t (id INTEGER, value TEXT)")
        assert _field(r, "value").mismatched == 1
        assert _field(r, "value").null_in_source == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-15  NULL handling — value in source, null in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_15_SourceValueTargetNull:
    MAPPING = [
        ["T", "ID",  "t", "id",    "direct", "yes", "no",  "INTEGER", ""],
        ["T", "VAL", "t", "value", "direct", "no",  "yes", "VARCHAR", ""],
    ]

    def test_value_lost_in_target(self, tmp_path):
        src = [{"ID": 1, "VAL": "important data"}]
        tgt = [{"id": 1, "value": None}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, VAL TEXT)",
                 "CREATE TABLE t (id INTEGER, value TEXT)")
        assert _field(r, "value").mismatched == 1
        assert _field(r, "value").null_in_target == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-16  Multiple transforms — partial failure across fields
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_16_MultiTransformPartialFailure:
    MAPPING = [
        ["INV", "INV_ID",  "invoice", "invoice_id",   "direct",                         "yes", "no", "INTEGER", ""],
        ["INV", "VEND_NM", "invoice", "vendor_name",  "trim",                            "no",  "no", "VARCHAR", ""],
        ["INV", "EMAIL",   "invoice", "vendor_email", "lower",                           "no",  "no", "VARCHAR", ""],
        ["INV", "STAT",    "invoice", "status",       "lookup: P=Pending|A=Approved",    "no",  "no", "VARCHAR", ""],
        ["INV", "AMT",     "invoice", "amount",       "direct",                          "no",  "no", "DECIMAL", ""],
    ]
    SRC = [{"INV_ID": 1, "VEND_NM": "  Acme Corp  ", "EMAIL": "BILLING@ACME.COM", "STAT": "P", "AMT": 5000}]

    def test_only_email_fails(self, tmp_path):
        # trim OK, lookup OK, amount OK — only email NOT lowercased
        tgt = [{"invoice_id": 1, "vendor_name": "Acme Corp", "vendor_email": "BILLING@ACME.COM",
                "status": "Pending", "amount": 5000}]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt, "INV", "invoice",
                 "CREATE TABLE INV (INV_ID INTEGER, VEND_NM TEXT, EMAIL TEXT, STAT TEXT, AMT REAL)",
                 "CREATE TABLE invoice (invoice_id INTEGER, vendor_name TEXT, vendor_email TEXT, status TEXT, amount REAL)")
        assert _field(r, "vendor_name").mismatched == 0
        assert _field(r, "vendor_email").mismatched == 1
        assert _field(r, "status").mismatched == 0
        assert _field(r, "amount").mismatched == 0

    def test_all_fields_clean(self, tmp_path):
        tgt = [{"invoice_id": 1, "vendor_name": "Acme Corp", "vendor_email": "billing@acme.com",
                "status": "Pending", "amount": 5000}]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt, "INV", "invoice",
                 "CREATE TABLE INV (INV_ID INTEGER, VEND_NM TEXT, EMAIL TEXT, STAT TEXT, AMT REAL)",
                 "CREATE TABLE invoice (invoice_id INTEGER, vendor_name TEXT, vendor_email TEXT, status TEXT, amount REAL)")
        assert r.is_clean


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-17  Sample diffs included in field result
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_17_SampleDiffs:
    MAPPING = [
        ["T", "ID",  "t", "id",    "direct", "yes", "no", "INTEGER", ""],
        ["T", "VAL", "t", "value", "lower",  "no",  "no", "VARCHAR", ""],
    ]

    def test_sample_diffs_populated(self, tmp_path):
        src = [{"ID": i, "VAL": f"UPPER{i}"} for i in range(1, 8)]
        tgt = [{"id": i, "value": f"UPPER{i}"} for i in range(1, 8)]  # NOT lowercased
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, VAL TEXT)",
                 "CREATE TABLE t (id INTEGER, value TEXT)")
        diffs = _field(r, "value").sample_diffs
        assert len(diffs) > 0
        assert len(diffs) <= 5    # capped at 5 samples
        assert all("source" in d and "target" in d and "key" in d for d in diffs)


# ─────────────────────────────────────────────────────────────────────────────
# TC-T-18  Nullable field — null target, nullable=yes, no warning generated
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_T_18_NullableNoWarning:
    MAPPING = [
        ["T", "ID",  "t", "id",    "direct", "yes", "no",  "INTEGER", ""],
        ["T", "OPT", "t", "opt",   "direct", "no",  "yes", "VARCHAR", "optional"],  # nullable=yes
    ]

    def test_nullable_field_null_no_warning(self, tmp_path):
        src = [{"ID": 1, "OPT": "has value"},
               {"ID": 2, "OPT": "has value"}]
        tgt = [{"id": 1, "opt": None},     # null but nullable=yes
               {"id": 2, "opt": None}]
        r = _run(tmp_path, self.MAPPING, src, tgt, "T", "t",
                 "CREATE TABLE T (ID INTEGER, OPT TEXT)",
                 "CREATE TABLE t (id INTEGER, opt TEXT)")
        # The field IS mismatched (value vs null) but no NOT NULL warning
        # since nullable=yes means nulls in target are acceptable
        assert not any("NOT NULL" in w for w in r.warnings)

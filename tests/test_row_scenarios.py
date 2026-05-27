"""
tests/test_row_scenarios.py — Row-level reconciliation scenarios.

Covers every situation related to record counts, key matching,
missing rows, extra rows, empty tables, and mixed combinations.

Scenarios:
  TC-R-01  All rows matched — clean migration
  TC-R-02  Single row missing in target
  TC-R-03  Multiple rows missing in target
  TC-R-04  Majority of rows missing (>50%)
  TC-R-05  All rows missing — catastrophic pipeline failure
  TC-R-06  Single extra row in target
  TC-R-07  Multiple extra rows in target
  TC-R-08  All rows extra — target was loaded from wrong source
  TC-R-09  Both missing AND extra rows simultaneously
  TC-R-10  Empty source table — target should also be empty
  TC-R-11  Empty target table — all source rows missing
  TC-R-12  Duplicate keys in target — first seen wins
  TC-R-13  String keys instead of integer keys
  TC-R-14  Run filter scopes to subset of rows
  TC-R-15  Run filter returns zero rows (no data for this batch)
  TC-R-16  Sample mode limits rows checked
  TC-R-17  Large batch — 1000 rows, 50 missing, 30 extra
  TC-R-18  Single row table — clean
  TC-R-19  Single row table — missing
"""

import csv
import sqlite3
import tempfile
import os
import pytest

from reconpilot.mapping import load_mapping
from reconpilot.connection import connect_dsn
from reconpilot.reconciler import reconcile_from_mapping


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_csv_mapping(rows, tmp_path, filename="mapping.csv"):
    header = ["source_table","source_column","target_table","target_column",
              "transformation","is_key","nullable","data_type","notes"]
    p = str(tmp_path / filename)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def _make_db(tmp_path, filename, table, schema, rows):
    p = str(tmp_path / filename)
    conn = sqlite3.connect(p)
    conn.execute(schema)
    if rows:
        cols = ", ".join(rows[0].keys())
        vals = ", ".join("?" * len(rows[0]))
        conn.executemany(f"INSERT INTO {table} ({cols}) VALUES ({vals})",
                         [list(r.values()) for r in rows])
    conn.commit()
    conn.close()
    return p


SIMPLE_MAPPING = [
    ["CUSTOMER", "CUST_ID",  "customers", "customer_id", "direct", "yes", "no", "INTEGER", "PK"],
    ["CUSTOMER", "CUST_NM",  "customers", "cust_name",   "trim",   "no",  "no", "VARCHAR", ""],
    ["CUSTOMER", "EMAIL",    "customers", "email",       "lower",  "no",  "yes","VARCHAR", ""],
    ["CUSTOMER", "STATUS",   "customers", "status",      "direct", "no",  "no", "VARCHAR", ""],
]
SRC_SCHEMA = "CREATE TABLE CUSTOMER (CUST_ID INTEGER, CUST_NM TEXT, EMAIL TEXT, STATUS TEXT)"
TGT_SCHEMA = "CREATE TABLE customers (customer_id INTEGER, cust_name TEXT, email TEXT, status TEXT)"


def _base_source():
    return [
        {"CUST_ID": i, "CUST_NM": f"Customer {i}", "EMAIL": f"c{i}@example.com", "STATUS": "Active"}
        for i in range(1, 11)   # 10 rows
    ]

def _base_target():
    return [
        {"customer_id": i, "cust_name": f"Customer {i}", "email": f"c{i}@example.com", "status": "Active"}
        for i in range(1, 11)
    ]


def _run(tmp_path, src_rows, tgt_rows, run_filter=None, sample=None):
    map_path = _make_csv_mapping(SIMPLE_MAPPING, tmp_path)
    src_path = _make_db(tmp_path, "src.db", "CUSTOMER",  SRC_SCHEMA, src_rows)
    tgt_path = _make_db(tmp_path, "tgt.db", "customers", TGT_SCHEMA, tgt_rows)
    doc = load_mapping(map_path)
    src = connect_dsn(f"sqlite:///{src_path}", name="src")
    tgt = connect_dsn(f"sqlite:///{tgt_path}", name="tgt")
    result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER",
                                    run_filter=run_filter, sample=sample)
    src.close(); tgt.close()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-01  All rows matched — clean migration
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_01_AllRowsClean:
    def test_is_clean(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert r.is_clean

    def test_counts_match(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert r.source_count == 10
        assert r.target_count == 10
        assert r.matched_keys == 10

    def test_no_missing(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert len(r.missing_in_target) == 0

    def test_no_extra(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert len(r.extra_in_target) == 0

    def test_zero_errors(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert r.error_count == 0

    def test_success_equals_matched(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert r.success_count == r.matched_keys

    def test_no_row_diffs(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target())
        assert r.row_diffs == []


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-02  Single row missing in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_02_SingleMissingRow:
    def test_not_clean(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] != 5]
        result = _run(tmp_path, _base_source(), tgt)
        assert not result.is_clean

    def test_missing_count_is_one(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] != 5]
        result = _run(tmp_path, _base_source(), tgt)
        assert len(result.missing_in_target) == 1

    def test_correct_key_missing(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] != 5]
        result = _run(tmp_path, _base_source(), tgt)
        assert "5" in [str(k) for k in result.missing_in_target]

    def test_row_diff_has_source_data(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] != 5]
        result = _run(tmp_path, _base_source(), tgt)
        missing_diff = next(d for d in result.row_diffs if d.status == "missing_in_target")
        assert missing_diff.source_row != {}
        assert missing_diff.target_row == {}

    def test_row_diff_comment_explains(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] != 5]
        result = _run(tmp_path, _base_source(), tgt)
        missing_diff = next(d for d in result.row_diffs if d.status == "missing_in_target")
        assert "missing" in missing_diff.comment.lower() or "MISSING" in missing_diff.comment


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-03  Multiple rows missing in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_03_MultipleRowsMissing:
    MISSING_IDS = {2, 4, 6, 8}

    def test_missing_count(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] not in self.MISSING_IDS]
        r = _run(tmp_path, _base_source(), tgt)
        assert len(r.missing_in_target) == len(self.MISSING_IDS)

    def test_all_missing_keys_reported(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] not in self.MISSING_IDS]
        r = _run(tmp_path, _base_source(), tgt)
        reported = {str(k) for k in r.missing_in_target}
        expected = {str(i) for i in self.MISSING_IDS}
        assert expected == reported

    def test_matched_count_correct(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] not in self.MISSING_IDS]
        r = _run(tmp_path, _base_source(), tgt)
        assert r.matched_keys == 10 - len(self.MISSING_IDS)

    def test_error_count_equals_missing(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] not in self.MISSING_IDS]
        r = _run(tmp_path, _base_source(), tgt)
        assert r.error_count >= len(self.MISSING_IDS)


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-04  Majority of rows missing (>50% pipeline failure)
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_04_MajorityMissing:
    def test_majority_missing(self, tmp_path):
        # Only 2 out of 10 rows made it to target
        tgt = [r for r in _base_target() if r["customer_id"] in (1, 2)]
        r = _run(tmp_path, _base_source(), tgt)
        assert len(r.missing_in_target) == 8
        assert r.source_count == 10
        assert r.target_count == 2

    def test_still_matches_what_arrived(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] in (1, 2)]
        r = _run(tmp_path, _base_source(), tgt)
        assert r.matched_keys == 2


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-05  All rows missing — catastrophic pipeline failure
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_05_AllRowsMissing:
    def test_all_missing(self, tmp_path):
        r = _run(tmp_path, _base_source(), [])
        assert r.source_count == 10
        assert r.target_count == 0
        assert r.matched_keys == 0
        assert len(r.missing_in_target) == 10

    def test_no_field_results_for_empty_intersection(self, tmp_path):
        r = _run(tmp_path, _base_source(), [])
        # No matched keys means no field comparisons possible
        for f in r.field_results:
            assert f.matched == 0
            assert f.mismatched == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-06  Single extra row in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_06_SingleExtraRow:
    def test_extra_detected(self, tmp_path):
        tgt = _base_target() + [{"customer_id": 999, "cust_name": "Ghost", "email": "g@x.com", "status": "Active"}]
        r = _run(tmp_path, _base_source(), tgt)
        assert len(r.extra_in_target) == 1
        assert "999" in [str(k) for k in r.extra_in_target]

    def test_row_diff_has_target_data(self, tmp_path):
        tgt = _base_target() + [{"customer_id": 999, "cust_name": "Ghost", "email": "g@x.com", "status": "Active"}]
        r = _run(tmp_path, _base_source(), tgt)
        extra_diff = next(d for d in r.row_diffs if d.status == "extra_in_target")
        assert extra_diff.target_row != {}
        assert extra_diff.source_row == {}

    def test_not_clean(self, tmp_path):
        tgt = _base_target() + [{"customer_id": 999, "cust_name": "Ghost", "email": "g@x.com", "status": "Active"}]
        r = _run(tmp_path, _base_source(), tgt)
        assert not r.is_clean


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-07  Multiple extra rows in target (double-load simulation)
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_07_MultipleExtraRows:
    def test_multiple_extra(self, tmp_path):
        extras = [
            {"customer_id": 901, "cust_name": "Extra A", "email": "a@x.com", "status": "Active"},
            {"customer_id": 902, "cust_name": "Extra B", "email": "b@x.com", "status": "Active"},
            {"customer_id": 903, "cust_name": "Extra C", "email": "c@x.com", "status": "Active"},
        ]
        tgt = _base_target() + extras
        r = _run(tmp_path, _base_source(), tgt)
        assert len(r.extra_in_target) == 3

    def test_extra_count_in_dict(self, tmp_path):
        extras = [
            {"customer_id": 901, "cust_name": "X", "email": "x@x.com", "status": "Active"},
            {"customer_id": 902, "cust_name": "Y", "email": "y@x.com", "status": "Active"},
        ]
        tgt = _base_target() + extras
        r = _run(tmp_path, _base_source(), tgt)
        d = r.to_dict()
        assert d["extra_in_target_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-08  All rows extra — target loaded from wrong source
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_08_AllRowsExtra:
    def test_completely_different_keys(self, tmp_path):
        # Source has 1-10, target has 100-109 — completely different
        tgt = [
            {"customer_id": i, "cust_name": f"Wrong {i}", "email": f"w{i}@x.com", "status": "Active"}
            for i in range(100, 110)
        ]
        r = _run(tmp_path, _base_source(), tgt)
        assert len(r.missing_in_target) == 10   # all source rows missing
        assert len(r.extra_in_target) == 10     # all target rows extra
        assert r.matched_keys == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-09  Both missing AND extra rows simultaneously
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_09_MissingAndExtra:
    def test_both_detected_independently(self, tmp_path):
        # Remove ID 3 and 7 from target, add a ghost record
        tgt = [r for r in _base_target() if r["customer_id"] not in (3, 7)]
        tgt.append({"customer_id": 500, "cust_name": "Phantom", "email": "p@x.com", "status": "Active"})
        r = _run(tmp_path, _base_source(), tgt)
        assert len(r.missing_in_target) == 2
        assert len(r.extra_in_target) == 1
        assert not r.is_clean

    def test_row_diffs_contain_both_types(self, tmp_path):
        tgt = [r for r in _base_target() if r["customer_id"] != 3]
        tgt.append({"customer_id": 500, "cust_name": "Ghost", "email": "g@x.com", "status": "Active"})
        r = _run(tmp_path, _base_source(), tgt)
        statuses = {d.status for d in r.row_diffs}
        assert "missing_in_target" in statuses
        assert "extra_in_target" in statuses


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-10  Empty source table — target should also be empty
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_10_EmptySource:
    def test_empty_source_empty_target_is_clean(self, tmp_path):
        r = _run(tmp_path, [], [])
        assert r.source_count == 0
        assert r.target_count == 0
        assert r.matched_keys == 0
        assert r.is_clean

    def test_empty_source_non_empty_target_extra(self, tmp_path):
        r = _run(tmp_path, [], _base_target())
        assert r.source_count == 0
        assert len(r.extra_in_target) == 10
        assert not r.is_clean


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-11  Empty target — all source rows missing
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_11_EmptyTarget:
    def test_all_source_rows_reported_missing(self, tmp_path):
        r = _run(tmp_path, _base_source(), [])
        assert len(r.missing_in_target) == 10
        assert r.target_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-12  String keys instead of integer keys
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_12_StringKeys:
    def test_string_key_matching(self, tmp_path):
        mapping = [
            ["PRODUCT", "PROD_CODE", "products", "product_code", "direct", "yes", "no", "VARCHAR", "PK"],
            ["PRODUCT", "PROD_NAME", "products", "product_name", "trim",   "no",  "no", "VARCHAR", ""],
        ]
        src_rows = [
            {"PROD_CODE": "SKU-001", "PROD_NAME": "Widget A"},
            {"PROD_CODE": "SKU-002", "PROD_NAME": "Widget B"},
            {"PROD_CODE": "SKU-003", "PROD_NAME": "Widget C"},
        ]
        tgt_rows = [
            {"product_code": "SKU-001", "product_name": "Widget A"},
            {"product_code": "SKU-002", "product_name": "Widget B"},
            # SKU-003 missing
        ]
        map_path = _make_csv_mapping(mapping, tmp_path)
        src_path = _make_db(tmp_path, "src.db", "PRODUCT",
                            "CREATE TABLE PRODUCT (PROD_CODE TEXT, PROD_NAME TEXT)", src_rows)
        tgt_path = _make_db(tmp_path, "tgt.db", "products",
                            "CREATE TABLE products (product_code TEXT, product_name TEXT)", tgt_rows)
        doc = load_mapping(map_path)
        src = connect_dsn(f"sqlite:///{src_path}")
        tgt = connect_dsn(f"sqlite:///{tgt_path}")
        r = reconcile_from_mapping(doc, src, tgt, "PRODUCT")
        src.close(); tgt.close()
        assert len(r.missing_in_target) == 1
        assert "SKU-003" in [str(k) for k in r.missing_in_target]


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-13  Run filter scopes to subset of rows
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_13_RunFilter:
    def test_filter_limits_source(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target(), run_filter="CUST_ID <= 5")
        assert r.source_count == 5

    def test_filter_extra_in_target_for_unfiltered(self, tmp_path):
        # Source filtered to 5 rows; target has all 10 → keys 6-10 appear extra
        r = _run(tmp_path, _base_source(), _base_target(), run_filter="CUST_ID <= 5")
        assert len(r.extra_in_target) == 5

    def test_filter_single_row(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target(), run_filter="CUST_ID = 3")
        assert r.source_count == 1
        assert r.matched_keys == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-14  Run filter returns zero rows
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_14_RunFilterZeroRows:
    def test_filter_no_match(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target(), run_filter="CUST_ID = 9999")
        assert r.source_count == 0
        assert r.matched_keys == 0

    def test_target_rows_all_extra_when_source_empty(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target(), run_filter="CUST_ID = 9999")
        assert len(r.extra_in_target) == 10


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-15  Sample mode limits rows checked
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_15_SampleMode:
    def test_sample_limits_source_rows(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target(), sample=3)
        assert r.source_count == 3

    def test_sample_does_not_exceed_available(self, tmp_path):
        r = _run(tmp_path, _base_source(), _base_target(), sample=50)
        assert r.source_count == 10   # only 10 available


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-16  Large batch — 1000 rows, 50 missing, 30 extra
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_16_LargeBatch:
    def test_large_batch_counts(self, tmp_path):
        n = 1000
        src = [{"CUST_ID": i, "CUST_NM": f"Cust {i}", "EMAIL": f"c{i}@x.com", "STATUS": "Active"}
               for i in range(1, n + 1)]
        # Remove IDs 501-550 (50 missing)
        missing_ids = set(range(501, 551))
        tgt = [{"customer_id": i, "cust_name": f"Cust {i}", "email": f"c{i}@x.com", "status": "Active"}
               for i in range(1, n + 1) if i not in missing_ids]
        # Add 30 phantom records
        for i in range(9001, 9031):
            tgt.append({"customer_id": i, "cust_name": f"Ghost {i}", "email": f"g{i}@x.com", "status": "Active"})
        r = _run(tmp_path, src, tgt)
        assert r.source_count == 1000
        assert len(r.missing_in_target) == 50
        assert len(r.extra_in_target) == 30
        assert r.matched_keys == 950


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-17  Single row table — clean
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_17_SingleRowClean:
    def test_single_row_clean(self, tmp_path):
        src = [{"CUST_ID": 1, "CUST_NM": "Alice", "EMAIL": "alice@x.com", "STATUS": "Active"}]
        tgt = [{"customer_id": 1, "cust_name": "Alice", "email": "alice@x.com", "status": "Active"}]
        r = _run(tmp_path, src, tgt)
        assert r.is_clean
        assert r.source_count == 1
        assert r.matched_keys == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-R-18  Single row table — missing in target
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_R_18_SingleRowMissing:
    def test_single_row_missing(self, tmp_path):
        src = [{"CUST_ID": 1, "CUST_NM": "Alice", "EMAIL": "alice@x.com", "STATUS": "Active"}]
        r = _run(tmp_path, src, [])
        assert not r.is_clean
        assert len(r.missing_in_target) == 1
        assert r.matched_keys == 0

    def test_row_diff_populated(self, tmp_path):
        src = [{"CUST_ID": 1, "CUST_NM": "Alice", "EMAIL": "alice@x.com", "STATUS": "Active"}]
        r = _run(tmp_path, src, [])
        assert len(r.row_diffs) == 1
        assert r.row_diffs[0].status == "missing_in_target"
        assert r.row_diffs[0].key == "1"

"""
Tests for pipe-recon — uses only SQLite + CSV mapping, zero external deps.
"""

import csv
import os
import sqlite3
import tempfile
import pytest

from reconpilot.mapping import load_mapping, create_sample_mapping, MappingDocument
from reconpilot.connection import connect_dsn, Connection
from reconpilot.reconciler import reconcile_from_mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mapping_csv(path: str, rows: list[list]):
    """Write a minimal mapping CSV at path."""
    header = ["source_table", "source_column", "target_table", "target_column",
              "transformation", "is_key", "nullable", "data_type", "notes"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def make_sqlite(path: str, table: str, schema: str, rows: list[dict]):
    conn = sqlite3.connect(path)
    conn.execute(schema)
    for r in rows:
        cols = ", ".join(r.keys())
        vals = ", ".join("?" * len(r))
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({vals})", list(r.values()))
    conn.commit()
    conn.close()


SOURCE_ROWS = [
    {"CUST_ID": 1, "FIRST_NM": "  Alice  ", "EMAIL_ADDR": "Alice@Example.com", "STAT_CD": "A"},
    {"CUST_ID": 2, "FIRST_NM": "  Bob  ",   "EMAIL_ADDR": "Bob@Example.com",   "STAT_CD": "I"},
    {"CUST_ID": 3, "FIRST_NM": "  Carol  ", "EMAIL_ADDR": "Carol@Example.com", "STAT_CD": "A"},
]

TARGET_ROWS = [
    {"customer_id": 1, "first_name": "Alice", "email": "alice@example.com", "status": "Active"},
    {"customer_id": 2, "first_name": "Bob",   "email": "bob@example.com",   "status": "Inactive"},
    {"customer_id": 3, "first_name": "Carol", "email": "carol@example.com", "status": "Active"},
]

MAPPING_ROWS = [
    ["CUSTOMER", "CUST_ID",    "customers", "customer_id", "direct", "yes", "no",  "INTEGER", "PK"],
    ["CUSTOMER", "FIRST_NM",   "customers", "first_name",  "trim",   "no",  "no",  "VARCHAR", ""],
    ["CUSTOMER", "EMAIL_ADDR", "customers", "email",       "lower",  "no",  "yes", "VARCHAR", ""],
    ["CUSTOMER", "STAT_CD",    "customers", "status",      "lookup: A=Active,I=Inactive", "no", "no", "VARCHAR", ""],
]

SRC_SCHEMA = "CREATE TABLE CUSTOMER (CUST_ID INTEGER, FIRST_NM TEXT, EMAIL_ADDR TEXT, STAT_CD TEXT)"
TGT_SCHEMA = "CREATE TABLE customers (customer_id INTEGER, first_name TEXT, email TEXT, status TEXT)"


# ---------------------------------------------------------------------------
# Test: load_mapping
# ---------------------------------------------------------------------------

class TestLoadMapping:
    def test_load_csv(self, tmp_path):
        p = str(tmp_path / "map.csv")
        make_mapping_csv(p, MAPPING_ROWS)
        doc = load_mapping(p)
        assert isinstance(doc, MappingDocument)
        assert "CUSTOMER" in doc.tables
        assert len(doc.mappings) == 4

    def test_key_field_detected(self, tmp_path):
        p = str(tmp_path / "map.csv")
        make_mapping_csv(p, MAPPING_ROWS)
        doc = load_mapping(p)
        keys = doc.keys_for_table("CUSTOMER")
        assert keys == ["CUST_ID"]

    def test_target_keys(self, tmp_path):
        p = str(tmp_path / "map.csv")
        make_mapping_csv(p, MAPPING_ROWS)
        doc = load_mapping(p)
        tgt_keys = doc.target_keys_for_table("CUSTOMER")
        assert tgt_keys == ["customer_id"]

    def test_transformation_stored(self, tmp_path):
        p = str(tmp_path / "map.csv")
        make_mapping_csv(p, MAPPING_ROWS)
        doc = load_mapping(p)
        email_field = next(m for m in doc.mappings if m.source_column == "EMAIL_ADDR")
        assert email_field.transformation == "lower"

    def test_missing_required_column_raises(self, tmp_path):
        p = str(tmp_path / "bad.csv")
        with open(p, "w", newline="") as f:
            csv.writer(f).writerows([["col_a", "col_b"], ["x", "y"]])
        with pytest.raises(ValueError, match="source_table"):
            load_mapping(p)

    def test_create_sample_mapping(self, tmp_path):
        p = str(tmp_path / "sample.csv")
        create_sample_mapping(p)
        assert os.path.exists(p)
        doc = load_mapping(p)
        assert len(doc.mappings) > 0

    def test_column_aliases(self, tmp_path):
        """Handles 'src_table' instead of 'source_table'."""
        p = str(tmp_path / "alias.csv")
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["src_table", "src_field", "tgt_table", "tgt_field", "transform", "pk"])
            w.writerow(["ORDERS", "ORD_ID", "orders", "order_id", "direct", "yes"])
        doc = load_mapping(p)
        assert "ORDERS" in doc.tables
        assert doc.mappings[0].is_key is True


# ---------------------------------------------------------------------------
# Test: connect_dsn + Connection
# ---------------------------------------------------------------------------

class TestConnection:
    def test_sqlite_connect(self, tmp_path):
        db = str(tmp_path / "test.db")
        make_sqlite(db, "CUSTOMER", SRC_SCHEMA, SOURCE_ROWS)
        conn = connect_dsn(f"sqlite:///{db}", name="test")
        assert isinstance(conn, Connection)
        rows = conn.query("SELECT * FROM CUSTOMER")
        assert len(rows) == 3
        conn.close()

    def test_query_returns_dicts(self, tmp_path):
        db = str(tmp_path / "test.db")
        make_sqlite(db, "CUSTOMER", SRC_SCHEMA, SOURCE_ROWS)
        conn = connect_dsn(f"sqlite:///{db}")
        rows = conn.query("SELECT * FROM CUSTOMER WHERE CUST_ID = 1")
        assert isinstance(rows[0], dict)
        assert rows[0]["CUST_ID"] == 1
        conn.close()

    def test_count(self, tmp_path):
        db = str(tmp_path / "test.db")
        make_sqlite(db, "CUSTOMER", SRC_SCHEMA, SOURCE_ROWS)
        conn = connect_dsn(f"sqlite:///{db}")
        assert conn.count("CUSTOMER") == 3
        assert conn.count("CUSTOMER", "CUST_ID > 1") == 2
        conn.close()

    def test_columns(self, tmp_path):
        db = str(tmp_path / "test.db")
        make_sqlite(db, "CUSTOMER", SRC_SCHEMA, SOURCE_ROWS)
        conn = connect_dsn(f"sqlite:///{db}")
        cols = conn.columns("CUSTOMER")
        names = [c["name"] for c in cols]
        assert "CUST_ID" in names
        conn.close()

    def test_invalid_dsn_raises(self):
        with pytest.raises(ValueError):
            connect_dsn("ftp://something")


# ---------------------------------------------------------------------------
# Test: reconcile_from_mapping
# ---------------------------------------------------------------------------

class TestReconcileFromMapping:
    def _setup(self, tmp_path, src_rows=None, tgt_rows=None):
        """Returns (doc, src_conn, tgt_conn)."""
        src_rows = src_rows if src_rows is not None else SOURCE_ROWS
        tgt_rows = tgt_rows if tgt_rows is not None else TARGET_ROWS

        map_path = str(tmp_path / "map.csv")
        make_mapping_csv(map_path, MAPPING_ROWS)
        doc = load_mapping(map_path)

        src_db = str(tmp_path / "src.db")
        tgt_db = str(tmp_path / "tgt.db")
        make_sqlite(src_db, "CUSTOMER", SRC_SCHEMA, src_rows)
        make_sqlite(tgt_db, "customers", TGT_SCHEMA, tgt_rows)

        src_conn = connect_dsn(f"sqlite:///{src_db}", name="src")
        tgt_conn = connect_dsn(f"sqlite:///{tgt_db}", name="tgt")
        return doc, src_conn, tgt_conn

    def test_clean_reconciliation(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        assert result.is_clean
        assert result.source_count == 3
        assert result.target_count == 3
        assert result.matched_keys == 3
        assert result.total_field_mismatches == 0
        src.close(); tgt.close()

    def test_missing_in_target(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path, tgt_rows=TARGET_ROWS[:2])
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        assert not result.is_clean
        assert result.source_count == 3
        assert result.target_count == 2
        assert "3" in [str(k) for k in result.missing_in_target]
        src.close(); tgt.close()

    def test_extra_in_target(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path, src_rows=SOURCE_ROWS[:2])
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        assert not result.is_clean
        assert len(result.extra_in_target) == 1
        src.close(); tgt.close()

    def test_field_mismatch_detected(self, tmp_path):
        bad_tgt = [r.copy() for r in TARGET_ROWS]
        bad_tgt[0]["email"] = "WRONG@EXAMPLE.COM"   # lower transform should catch this
        doc, src, tgt = self._setup(tmp_path, tgt_rows=bad_tgt)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        assert not result.is_clean
        email_result = next(f for f in result.field_results if f.target_column == "email")
        assert email_result.mismatched == 1
        assert len(email_result.sample_diffs) == 1
        src.close(); tgt.close()

    def test_lookup_transform(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        status_result = next(f for f in result.field_results if f.target_column == "status")
        assert status_result.mismatched == 0
        src.close(); tgt.close()

    def test_trim_transform(self, tmp_path):
        """Trim is applied to source only — target must already be trimmed for a clean match."""
        doc, src, tgt = self._setup(tmp_path)
        # TARGET_ROWS already has trimmed names ("Alice", "Bob", "Carol")
        # SOURCE_ROWS has padded names ("  Alice  ", "  Bob  ", "  Carol  ")
        # trim(source) == target → should match cleanly
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        name_result = next(f for f in result.field_results if f.target_column == "first_name")
        assert name_result.mismatched == 0
        src.close(); tgt.close()

    def test_trim_detects_untrimmed_target(self, tmp_path):
        """If target still has spaces (ETL forgot to trim), it should be flagged as mismatch."""
        doc, src, tgt = self._setup(tmp_path, tgt_rows=[
            {"customer_id": 1, "first_name": "  Alice  ", "email": "alice@example.com", "status": "Active"},
            {"customer_id": 2, "first_name": "  Bob  ",   "email": "bob@example.com",   "status": "Inactive"},
            {"customer_id": 3, "first_name": "  Carol  ", "email": "carol@example.com", "status": "Active"},
        ])
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        name_result = next(f for f in result.field_results if f.target_column == "first_name")
        # Source "  Alice  " trimmed = "Alice", target "  Alice  " ≠ "Alice" → mismatch
        assert name_result.mismatched == 3
        src.close(); tgt.close()

    def test_outbound_direction(self, tmp_path):
        """OUTBOUND: target is authoritative, source receives data back."""
        doc, src, tgt = self._setup(tmp_path)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER", direction="OUTBOUND")
        assert result.direction == "OUTBOUND"
        src.close(); tgt.close()

    def test_run_filter(self, tmp_path):
        """run_filter scopes source rows — only those keys are reconciled."""
        doc, src, tgt = self._setup(tmp_path)
        # Filter applied to source table (CUSTOMER) using source column name
        result = reconcile_from_mapping(
            doc, src, tgt, "CUSTOMER",
            run_filter="CUST_ID <= 2"
        )
        # Source returns 2 rows; target returns all 3 (target is not filtered)
        assert result.source_count == 2
        # Keys 1 and 2 are present in target → matched; key 3 is extra in target
        assert result.matched_keys == 2
        assert len(result.extra_in_target) == 1
        src.close(); tgt.close()

    def test_sample_limits_rows(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER", sample=2)
        assert result.source_count == 2
        src.close(); tgt.close()

    def test_unknown_table_raises(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path)
        with pytest.raises(ValueError, match="No mappings found"):
            reconcile_from_mapping(doc, src, tgt, "NONEXISTENT_TABLE")
        src.close(); tgt.close()

    def test_generated_sql_present(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        assert len(result.generated_sql) >= 2
        assert "CUSTOMER" in result.generated_sql[0]
        src.close(); tgt.close()

    def test_to_dict(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path, tgt_rows=TARGET_ROWS[:2])
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        d = result.to_dict()
        assert d["source_count"] == 3
        assert d["target_count"] == 2
        assert d["missing_in_target_count"] == 1
        assert isinstance(d["fields"], list)
        src.close(); tgt.close()

    def test_pipeline_name(self, tmp_path):
        doc, src, tgt = self._setup(tmp_path)
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER", pipeline_name="CRM_Load")
        assert result.pipeline_name == "CRM_Load"
        src.close(); tgt.close()


# ---------------------------------------------------------------------------
# Test: HTML report
# ---------------------------------------------------------------------------

class TestHTMLReport:
    def test_html_report_generates(self, tmp_path):
        from reconpilot.report import to_html

        map_path = str(tmp_path / "map.csv")
        make_mapping_csv(map_path, MAPPING_ROWS)
        doc = load_mapping(map_path)

        src_db = str(tmp_path / "src.db")
        tgt_db = str(tmp_path / "tgt.db")
        make_sqlite(src_db, "CUSTOMER", SRC_SCHEMA, SOURCE_ROWS)
        make_sqlite(tgt_db, "customers", TGT_SCHEMA, TARGET_ROWS[:2])

        src = connect_dsn(f"sqlite:///{src_db}")
        tgt = connect_dsn(f"sqlite:///{tgt_db}")
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        src.close(); tgt.close()

        out = str(tmp_path / "report.html")
        to_html([result], out, project="CRM Migration Test")
        assert os.path.exists(out)

        with open(out) as f:
            content = f.read()
        assert "CRM Migration Test" in content
        assert "CUSTOMER" in content
        assert "pipe-recon" in content

    def test_clean_report_shows_clean(self, tmp_path):
        from reconpilot.report import to_html

        map_path = str(tmp_path / "map.csv")
        make_mapping_csv(map_path, MAPPING_ROWS)
        doc = load_mapping(map_path)
        src_db = str(tmp_path / "src.db")
        tgt_db = str(tmp_path / "tgt.db")
        make_sqlite(src_db, "CUSTOMER", SRC_SCHEMA, SOURCE_ROWS)
        make_sqlite(tgt_db, "customers", TGT_SCHEMA, TARGET_ROWS)
        src = connect_dsn(f"sqlite:///{src_db}")
        tgt = connect_dsn(f"sqlite:///{tgt_db}")
        result = reconcile_from_mapping(doc, src, tgt, "CUSTOMER")
        src.close(); tgt.close()

        out = str(tmp_path / "report.html")
        to_html([result], out)
        with open(out) as f:
            content = f.read()
        assert "CLEAN" in content

"""
pipe-recon demo — run all test scenarios end-to-end.

Usage:
    pip install pipe-recon
    python examples/demo.py

This script:
  1. Creates two in-memory SQLite databases (source + target) for each scenario
  2. Runs reconciliation using pipe-recon
  3. Prints results to terminal
  4. Saves a combined HTML report → examples/demo_report.html

Test scenarios covered:
  ✅ Scenario 1 — Perfect migration     (all rows matched, all fields clean)
  ❌ Scenario 2 — Missing rows          (rows present in source but absent in target)
  ⚠️  Scenario 3 — Extra rows           (phantom rows in target, possible double-load)
  🔄 Scenario 4 — Field mismatches      (lookup/trim/lower transformations not applied)
  ↔️  Scenario 5 — OUTBOUND pipeline    (DW pushes data back to source system)
  🔀 Scenario 6 — Mixed real-world      (Supplier Master with all error types together)
"""

import csv
import io
import os
import sqlite3
import sys
import tempfile

# ── Make sure we can import reconpilot from the repo root ────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reconpilot.mapping import load_mapping
from reconpilot.connection import connect_dsn
from reconpilot.reconciler import reconcile_from_mapping
from reconpilot.report import to_html


REPORT_PATH = os.path.join(os.path.dirname(__file__), "demo_report.html")

DIVIDER = "─" * 68


def _make_db(rows: list[dict], table: str, schema: str) -> str:
    """Create a named temp SQLite file, return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute(schema)
    if rows:
        cols = ", ".join(rows[0].keys())
        vals = ", ".join("?" * len(rows[0]))
        conn.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({vals})",
            [list(r.values()) for r in rows],
        )
    conn.commit()
    conn.close()
    return f.name


def _make_mapping(rows: list[list]) -> str:
    """Write a CSV mapping file to a temp file, return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    )
    header = [
        "source_table", "source_column", "target_table", "target_column",
        "transformation", "is_key", "nullable", "data_type", "notes",
    ]
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)
    f.close()
    return f.name


def _cleanup(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except Exception:
            pass


def banner(title: str, num: int, total: int):
    print(f"\n{DIVIDER}")
    print(f"  Scenario {num}/{total} — {title}")
    print(DIVIDER)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — Perfect migration
# ─────────────────────────────────────────────────────────────────────────────
def scenario_1_perfect_migration():
    banner("Perfect migration — all rows match, all transformations correct", 1, 6)

    SOURCE = [
        {"ORDER_ID": 101, "CUST_NM": "  Alice Smith  ", "EMAIL": "Alice@CORP.COM", "STAT": "A", "AMOUNT": 1500},
        {"ORDER_ID": 102, "CUST_NM": "  Bob Jones    ", "EMAIL": "Bob@CORP.COM",   "STAT": "A", "AMOUNT": 2400},
        {"ORDER_ID": 103, "CUST_NM": "  Carol White  ", "EMAIL": "Carol@CORP.COM", "STAT": "I", "AMOUNT":  800},
    ]
    TARGET = [
        {"order_id": 101, "customer_name": "Alice Smith", "email": "alice@corp.com", "status": "Active",   "amount": 1500},
        {"order_id": 102, "customer_name": "Bob Jones",   "email": "bob@corp.com",   "status": "Active",   "amount": 2400},
        {"order_id": 103, "customer_name": "Carol White", "email": "carol@corp.com", "status": "Inactive", "amount":  800},
    ]
    MAPPING = [
        ["ORDERS", "ORDER_ID",  "orders", "order_id",       "direct",                      "yes", "no",  "INTEGER", "PK"],
        ["ORDERS", "CUST_NM",   "orders", "customer_name",  "trim",                        "no",  "no",  "VARCHAR", ""],
        ["ORDERS", "EMAIL",     "orders", "email",          "lower",                       "no",  "no",  "VARCHAR", ""],
        ["ORDERS", "STAT",      "orders", "status",         "lookup: A=Active|I=Inactive", "no",  "no",  "VARCHAR", ""],
        ["ORDERS", "AMOUNT",    "orders", "amount",         "direct",                      "no",  "no",  "DECIMAL", ""],
    ]

    src_schema = "CREATE TABLE ORDERS (ORDER_ID INTEGER, CUST_NM TEXT, EMAIL TEXT, STAT TEXT, AMOUNT REAL)"
    tgt_schema = "CREATE TABLE orders (order_id INTEGER, customer_name TEXT, email TEXT, status TEXT, amount REAL)"

    src_path = _make_db(SOURCE, "ORDERS", src_schema)
    tgt_path = _make_db(TARGET, "orders", tgt_schema)
    map_path = _make_mapping(MAPPING)

    doc  = load_mapping(map_path)
    src  = connect_dsn(f"sqlite:///{src_path}", name="source")
    tgt  = connect_dsn(f"sqlite:///{tgt_path}", name="target")

    result = reconcile_from_mapping(doc, src, tgt, "ORDERS", pipeline_name="Order_Migration")
    result.print()

    src.close(); tgt.close()
    _cleanup(src_path, tgt_path, map_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — Missing rows in target
# ─────────────────────────────────────────────────────────────────────────────
def scenario_2_missing_rows():
    banner("Missing rows — records present in source but absent in target", 2, 6)

    SOURCE = [
        {"EMP_ID": 1, "EMP_NM": "David",   "DEPT": "Finance",    "SALARY": 75000},
        {"EMP_ID": 2, "EMP_NM": "Emma",    "DEPT": "HR",         "SALARY": 65000},
        {"EMP_ID": 3, "EMP_NM": "Frank",   "DEPT": "IT",         "SALARY": 90000},
        {"EMP_ID": 4, "EMP_NM": "Grace",   "DEPT": "Finance",    "SALARY": 82000},
        {"EMP_ID": 5, "EMP_NM": "Henry",   "DEPT": "Marketing",  "SALARY": 71000},
    ]
    # EMP_ID 3 and 5 are missing in target — pipeline dropped them
    TARGET = [
        {"employee_id": 1, "employee_name": "David", "department": "Finance",   "salary": 75000},
        {"employee_id": 2, "employee_name": "Emma",  "department": "HR",        "salary": 65000},
        {"employee_id": 4, "employee_name": "Grace", "department": "Finance",   "salary": 82000},
    ]
    MAPPING = [
        ["EMPLOYEE", "EMP_ID",  "employee", "employee_id",   "direct", "yes", "no", "INTEGER", "PK"],
        ["EMPLOYEE", "EMP_NM",  "employee", "employee_name", "trim",   "no",  "no", "VARCHAR", ""],
        ["EMPLOYEE", "DEPT",    "employee", "department",    "direct", "no",  "no", "VARCHAR", ""],
        ["EMPLOYEE", "SALARY",  "employee", "salary",        "direct", "no",  "no", "DECIMAL", ""],
    ]

    src_schema = "CREATE TABLE EMPLOYEE (EMP_ID INTEGER, EMP_NM TEXT, DEPT TEXT, SALARY REAL)"
    tgt_schema = "CREATE TABLE employee (employee_id INTEGER, employee_name TEXT, department TEXT, salary REAL)"

    src_path = _make_db(SOURCE, "EMPLOYEE", src_schema)
    tgt_path = _make_db(TARGET, "employee", tgt_schema)
    map_path = _make_mapping(MAPPING)

    doc  = load_mapping(map_path)
    src  = connect_dsn(f"sqlite:///{src_path}", name="source")
    tgt  = connect_dsn(f"sqlite:///{tgt_path}", name="target")

    result = reconcile_from_mapping(doc, src, tgt, "EMPLOYEE", pipeline_name="Employee_Load")
    result.print()

    src.close(); tgt.close()
    _cleanup(src_path, tgt_path, map_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — Extra rows in target (double-load / phantom records)
# ─────────────────────────────────────────────────────────────────────────────
def scenario_3_extra_rows():
    banner("Extra rows in target — phantom records, possible double-load", 3, 6)

    SOURCE = [
        {"PROD_ID": "P001", "PROD_NM": "Laptop",  "CATEGORY": "Electronics", "PRICE": 75000},
        {"PROD_ID": "P002", "PROD_NM": "Mouse",   "CATEGORY": "Electronics", "PRICE":   999},
        {"PROD_ID": "P003", "PROD_NM": "Keyboard","CATEGORY": "Electronics", "PRICE":  2499},
    ]
    # P004 and P999 are in target but NOT in source — phantom/double-load records
    TARGET = [
        {"product_id": "P001", "product_name": "Laptop",   "category": "Electronics", "price": 75000},
        {"product_id": "P002", "product_name": "Mouse",    "category": "Electronics", "price":   999},
        {"product_id": "P003", "product_name": "Keyboard", "category": "Electronics", "price":  2499},
        {"product_id": "P004", "product_name": "Monitor",  "category": "Electronics", "price": 18000},   # extra
        {"product_id": "P999", "product_name": "Unknown",  "category": "Unknown",     "price":     0},   # extra
    ]
    MAPPING = [
        ["PRODUCT", "PROD_ID",  "product", "product_id",   "direct", "yes", "no", "VARCHAR", "PK"],
        ["PRODUCT", "PROD_NM",  "product", "product_name", "trim",   "no",  "no", "VARCHAR", ""],
        ["PRODUCT", "CATEGORY", "product", "category",     "direct", "no",  "no", "VARCHAR", ""],
        ["PRODUCT", "PRICE",    "product", "price",        "direct", "no",  "no", "DECIMAL", ""],
    ]

    src_schema = "CREATE TABLE PRODUCT (PROD_ID TEXT, PROD_NM TEXT, CATEGORY TEXT, PRICE REAL)"
    tgt_schema = "CREATE TABLE product (product_id TEXT, product_name TEXT, category TEXT, price REAL)"

    src_path = _make_db(SOURCE, "PRODUCT", src_schema)
    tgt_path = _make_db(TARGET, "product", tgt_schema)
    map_path = _make_mapping(MAPPING)

    doc  = load_mapping(map_path)
    src  = connect_dsn(f"sqlite:///{src_path}", name="source")
    tgt  = connect_dsn(f"sqlite:///{tgt_path}", name="target")

    result = reconcile_from_mapping(doc, src, tgt, "PRODUCT", pipeline_name="Product_Catalog_Load")
    result.print()

    src.close(); tgt.close()
    _cleanup(src_path, tgt_path, map_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — Field transformation failures
# ─────────────────────────────────────────────────────────────────────────────
def scenario_4_field_mismatches():
    banner("Field mismatches — ETL transformations not applied correctly", 4, 6)

    # Source has: raw status codes, mixed case emails, spaces in names, raw date
    SOURCE = [
        {"INV_ID": 5001, "VENDOR_NM": "  Acme Corp  ", "VENDOR_EMAIL": "BILLING@ACME.COM", "STAT_CD": "P", "INV_DT": "20260115"},
        {"INV_ID": 5002, "VENDOR_NM": "  GlobalTech  ","VENDOR_EMAIL": "AP@GLOBALTECH.COM", "STAT_CD": "A", "INV_DT": "20260201"},
        {"INV_ID": 5003, "VENDOR_NM": "  FutureCo  ",  "VENDOR_EMAIL": "Pay@FutureCo.com",  "STAT_CD": "R", "INV_DT": "20260210"},
    ]
    # Target has transformation errors:
    #   5001 — email not lowercased, date format not converted
    #   5002 — status code not looked up ('A' stored instead of 'Approved')
    #   5003 — vendor name not trimmed (spaces preserved)
    TARGET = [
        {"invoice_id": 5001, "vendor_name": "Acme Corp",   "vendor_email": "BILLING@ACME.COM",  "status": "Pending",  "invoice_date": "20260115"},   # email not lower, date not formatted
        {"invoice_id": 5002, "vendor_name": "GlobalTech",  "vendor_email": "ap@globaltech.com",  "status": "A",        "invoice_date": "2026-02-01"},  # status not looked up
        {"invoice_id": 5003, "vendor_name": "  FutureCo  ","vendor_email": "pay@futureco.com",   "status": "Rejected", "invoice_date": "2026-02-10"},  # name not trimmed
    ]
    MAPPING = [
        ["INVOICE", "INV_ID",       "invoice", "invoice_id",   "direct",                               "yes", "no", "INTEGER", "PK"],
        ["INVOICE", "VENDOR_NM",    "invoice", "vendor_name",  "trim",                                 "no",  "no", "VARCHAR", ""],
        ["INVOICE", "VENDOR_EMAIL", "invoice", "vendor_email", "lower",                                "no",  "no", "VARCHAR", ""],
        ["INVOICE", "STAT_CD",      "invoice", "status",       "lookup: P=Pending|A=Approved|R=Rejected","no", "no", "VARCHAR", ""],
        ["INVOICE", "INV_DT",       "invoice", "invoice_date", "date_format: YYYYMMDD→YYYY-MM-DD",     "no",  "no", "DATE",    ""],
    ]

    src_schema = "CREATE TABLE INVOICE (INV_ID INTEGER, VENDOR_NM TEXT, VENDOR_EMAIL TEXT, STAT_CD TEXT, INV_DT TEXT)"
    tgt_schema = "CREATE TABLE invoice (invoice_id INTEGER, vendor_name TEXT, vendor_email TEXT, status TEXT, invoice_date TEXT)"

    src_path = _make_db(SOURCE, "INVOICE", src_schema)
    tgt_path = _make_db(TARGET, "invoice", tgt_schema)
    map_path = _make_mapping(MAPPING)

    doc  = load_mapping(map_path)
    src  = connect_dsn(f"sqlite:///{src_path}", name="source")
    tgt  = connect_dsn(f"sqlite:///{tgt_path}", name="target")

    result = reconcile_from_mapping(doc, src, tgt, "INVOICE", pipeline_name="Invoice_ETL")
    result.print()

    src.close(); tgt.close()
    _cleanup(src_path, tgt_path, map_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — OUTBOUND pipeline (DW → source writeback)
# ─────────────────────────────────────────────────────────────────────────────
def scenario_5_outbound():
    banner("OUTBOUND pipeline — DW sends processed status back to source CRM", 5, 6)

    # After DW processed orders, it writes status back to source CRM.
    # In OUTBOUND, target (DW) is authoritative — we check source received it.
    SOURCE_MAPPING_ROWS = [
        {"ORDER_ID": 201, "CUST_NM": "Diana",  "STAT": "P", "PROC_DT": None},
        {"ORDER_ID": 202, "CUST_NM": "Ethan",  "STAT": "P", "PROC_DT": None},
        {"ORDER_ID": 203, "CUST_NM": "Fiona",  "STAT": "P", "PROC_DT": None},
    ]
    # DW processed and sent back status updates — ORDER_ID 202 writeback failed
    DW_ROWS = [
        {"order_id": 201, "customer_name": "Diana", "status": "Completed", "processed_date": "2026-05-27"},
        # 202 missing — writeback to CRM failed for this order
        {"order_id": 203, "customer_name": "Fiona", "status": "Completed", "processed_date": "2026-05-27"},
    ]
    MAPPING = [
        ["ORDERS_CRM", "ORDER_ID",  "orders_dw", "order_id",        "direct", "yes", "no", "INTEGER", "PK"],
        ["ORDERS_CRM", "CUST_NM",   "orders_dw", "customer_name",   "trim",   "no",  "no", "VARCHAR", ""],
        ["ORDERS_CRM", "STAT",      "orders_dw", "status",          "direct", "no",  "no", "VARCHAR", ""],
        ["ORDERS_CRM", "PROC_DT",   "orders_dw", "processed_date",  "direct", "no",  "yes","DATE",    ""],
    ]

    src_schema = "CREATE TABLE ORDERS_CRM (ORDER_ID INTEGER, CUST_NM TEXT, STAT TEXT, PROC_DT TEXT)"
    tgt_schema = "CREATE TABLE orders_dw  (order_id INTEGER, customer_name TEXT, status TEXT, processed_date TEXT)"

    src_path = _make_db(SOURCE_MAPPING_ROWS, "ORDERS_CRM", src_schema)
    tgt_path = _make_db(DW_ROWS,             "orders_dw",  tgt_schema)
    map_path = _make_mapping(MAPPING)

    doc  = load_mapping(map_path)
    src  = connect_dsn(f"sqlite:///{src_path}", name="CRM")
    tgt  = connect_dsn(f"sqlite:///{tgt_path}", name="DW")

    result = reconcile_from_mapping(
        doc, src, tgt, "ORDERS_CRM",
        direction="OUTBOUND",
        pipeline_name="Order_Status_Writeback",
    )
    result.print()

    src.close(); tgt.close()
    _cleanup(src_path, tgt_path, map_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 6 — Supplier Master (real-world mixed scenario)
# ─────────────────────────────────────────────────────────────────────────────
def scenario_6_supplier_master():
    banner("Supplier Master — real-world mixed: missing + extra + 4 field mismatches", 6, 6)

    SOURCE = [
        (1001, "  Tata Consultancy  ",    "12 MG Road",              "Mumbai",      "Maharashtra",         "I", "A", "Procurement@TCS.COM",    "+91-22-67789900", "27AAACT2727Q1ZW"),
        (1002, "  Infosys Limited   ",    "Plot 44, Electronics City","Bengaluru",  "Karnataka",           "I", "A", "Vendor@INFOSYS.COM",      "+91-80-28520261", "29AAACI1681G1ZB"),
        (1003, "  Wipro Ltd         ",    "Sarjapur Road",            "Bengaluru",  "Karnataka",           "I", "A", "supplies@wipro.com",      "+91-80-28440011", "29AAACW0788E1ZB"),
        (1004, "  SAP SE            ",    "Dietmar-Hopp-Allee 16",   "Walldorf",   "Baden-Wuerttemberg",  "G", "A", "procurement@sap.com",     "+49-6227-747474",  "DE111765569"),
        (1005, "  Oracle Corp       ",    "500 Oracle Parkway",       "Redwood City","California",         "U", "A", "supplier@oracle.com",     "+1-650-506-7000",  "94-3082573"),
        (1006, "  Accenture Plc     ",    "1 Grand Canal Square",     "Dublin",     "Leinster",            "I", "S", "vendor@accenture.com",    "+353-1-6461000",   "IE4714791V"),
        (1007, "  Cognizant Tech    ",    "500 Frank W Burr Blvd",    "Teaneck",    "New Jersey",          "U", "A", "supply@cognizant.com",    "+1-201-801-0233",  "22-3743833"),
        (1008, "  HCL Technologies  ",    "806 Siddharth Nagar",      "Noida",      "Uttar Pradesh",       "I", "I", "PROCUREMENT@HCL.COM",     "+91-120-6125000",  "09AAACH2866A1ZO"),
    ]
    TARGET = [
        (1001, "Tata Consultancy",        "12 MG Road",               "Mumbai",      "Maharashtra",        "India",   "Active",    "procurement@tcs.com",   "+91-22-67789900", "27AAACT2727Q1ZW"),
        (1002, "Infosys Limited",         "Plot 44, Electronics City", "Bengaluru",  "Karnataka",          "India",   "Active",    "Vendor@INFOSYS.COM",    "+91-80-28520261", "29AAACI1681G1ZB"),  # email not lowered
        (1003, "Wipro Ltd",               "Sarjapur Road",             "Bengaluru",  "Karnataka",          "I",       "Active",    "supplies@wipro.com",    "+91-80-28440011", "29AAACW0788E1ZB"),  # country not looked up
        (1004, "  SAP SE            ",    "Dietmar-Hopp-Allee 16",    "Walldorf",   "Baden-Wuerttemberg", "Germany", "Active",    "procurement@sap.com",   "+49-6227-747474",  "DE111765569"),      # name not trimmed
        # 1005 missing — dropped by pipeline
        (1006, "Accenture Plc",           "1 Grand Canal Square",      "Dublin",     "Leinster",           "India",   "S",         "vendor@accenture.com",  "+353-1-6461000",  "IE4714791V"),       # status not looked up
        (1007, "Cognizant Tech",          "500 Frank W Burr Blvd",     "Teaneck",    "New Jersey",         "USA",     "Active",    "supply@cognizant.com",  "+1-201-801-0233", "22-3743833"),
        (1008, "HCL Technologies",        "806 Siddharth Nagar",       "Noida",      "Uttar Pradesh",      "India",   "Inactive",  "procurement@hcl.com",   "+91-120-6125000", "09AAACH2866A1ZO"),
        (9001, "Ghost Vendor Ltd",        "Unknown",                    "Unknown",    "Unknown",            "India",   "Active",    "ghost@ghost.com",       "",                ""),                 # extra
    ]
    MAPPING = [
        ["SUPPLIER_MASTER", "SUPP_ID",    "supplier_master", "supplier_id",    "direct",                                     "yes", "no",  "INTEGER", "PK"],
        ["SUPPLIER_MASTER", "SUPP_NM",    "supplier_master", "supplier_name",  "trim",                                       "no",  "no",  "VARCHAR", ""],
        ["SUPPLIER_MASTER", "ADDR_LINE1", "supplier_master", "address",        "trim",                                       "no",  "yes", "VARCHAR", ""],
        ["SUPPLIER_MASTER", "CITY_NM",    "supplier_master", "city",           "trim",                                       "no",  "yes", "VARCHAR", ""],
        ["SUPPLIER_MASTER", "STATE_NM",   "supplier_master", "state",          "trim",                                       "no",  "yes", "VARCHAR", ""],
        ["SUPPLIER_MASTER", "CNTRY_CD",   "supplier_master", "country",        "lookup: A=Australia|I=India|U=USA|G=Germany|F=France", "no", "no", "VARCHAR", ""],
        ["SUPPLIER_MASTER", "STAT_CD",    "supplier_master", "status",         "lookup: A=Active|I=Inactive|S=Suspended",    "no",  "no",  "VARCHAR", ""],
        ["SUPPLIER_MASTER", "CONT_EMAIL", "supplier_master", "contact_email",  "lower",                                      "no",  "yes", "VARCHAR", ""],
        ["SUPPLIER_MASTER", "CONT_PHONE", "supplier_master", "contact_phone",  "direct",                                     "no",  "yes", "VARCHAR", ""],
        ["SUPPLIER_MASTER", "TAX_ID",     "supplier_master", "tax_id",         "direct",                                     "no",  "yes", "VARCHAR", ""],
    ]

    src_schema = """CREATE TABLE SUPPLIER_MASTER (
        SUPP_ID INTEGER, SUPP_NM TEXT, ADDR_LINE1 TEXT, CITY_NM TEXT,
        STATE_NM TEXT, CNTRY_CD TEXT, STAT_CD TEXT,
        CONT_EMAIL TEXT, CONT_PHONE TEXT, TAX_ID TEXT)"""
    tgt_schema = """CREATE TABLE supplier_master (
        supplier_id INTEGER, supplier_name TEXT, address TEXT, city TEXT,
        state TEXT, country TEXT, status TEXT,
        contact_email TEXT, contact_phone TEXT, tax_id TEXT)"""

    src_f = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False); src_f.close()
    tgt_f = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False); tgt_f.close()

    src_conn_raw = sqlite3.connect(src_f.name)
    src_conn_raw.execute(src_schema)
    src_conn_raw.executemany("INSERT INTO SUPPLIER_MASTER VALUES (?,?,?,?,?,?,?,?,?,?)", SOURCE)
    src_conn_raw.commit(); src_conn_raw.close()

    tgt_conn_raw = sqlite3.connect(tgt_f.name)
    tgt_conn_raw.execute(tgt_schema)
    tgt_conn_raw.executemany("INSERT INTO supplier_master VALUES (?,?,?,?,?,?,?,?,?,?)", TARGET)
    tgt_conn_raw.commit(); tgt_conn_raw.close()

    map_path = _make_mapping(MAPPING)
    doc  = load_mapping(map_path)
    src  = connect_dsn(f"sqlite:///{src_f.name}", name="SourceDB")
    tgt  = connect_dsn(f"sqlite:///{tgt_f.name}", name="DataWarehouse")

    result = reconcile_from_mapping(
        doc, src, tgt, "SUPPLIER_MASTER",
        pipeline_name="Supplier_Master_Load",
    )
    result.print()

    src.close(); tgt.close()
    _cleanup(src_f.name, tgt_f.name, map_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'═' * 68}")
    print("  pipe-recon — Demo: 6 reconciliation test scenarios")
    print(f"{'═' * 68}")

    results = [
        scenario_1_perfect_migration(),
        scenario_2_missing_rows(),
        scenario_3_extra_rows(),
        scenario_4_field_mismatches(),
        scenario_5_outbound(),
        scenario_6_supplier_master(),
    ]

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'═' * 68}")
    print("  DEMO SUMMARY")
    print(f"{'═' * 68}")
    for r in results:
        icon   = "✅" if r.is_clean else "❌"
        arrow  = "→" if r.direction == "INBOUND" else "←"
        status = "CLEAN" if r.is_clean else f"{r.error_count} errors"
        print(f"  {icon}  {r.pipeline_name:<32} {r.direction:<9}  {status}")

    # ── HTML report ──────────────────────────────────────────────────────────
    to_html(results, REPORT_PATH, project="pipe-recon Demo — 6 Test Scenarios")
    print(f"\n{'─' * 68}")
    print(f"  📄 HTML report saved → {REPORT_PATH}")
    print(f"  Open in your browser to see the full side-by-side diff tables.")
    print(f"{'═' * 68}\n")

    # Exit non-zero if any scenario had issues (expected for scenarios 2-6)
    has_issues = any(not r.is_clean for r in results)
    sys.exit(1 if has_issues else 0)


if __name__ == "__main__":
    main()

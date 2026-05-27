"""
setup_test_dbs.py — Creates two SQLite databases to test pipe-recon end-to-end.

  source_db.sqlite  →  Simulates the legacy Oracle/CRM source system
  target_db.sqlite  →  Simulates the Data Warehouse after migration

Run this once to set up the test environment:
    python tests/fixtures/setup_test_dbs.py

Then run reconciliation:
    pipe-recon reconcile tests/fixtures/supplier_mapping.csv \\
        --source "sqlite:///tests/fixtures/source_db.sqlite" \\
        --target "sqlite:///tests/fixtures/target_db.sqlite" \\
        --table  SUPPLIER_MASTER \\
        --html   tests/fixtures/recon_report.html

Intentional discrepancies introduced (to make the test interesting):
  ❌ SUPP_ID=1005 — missing in target (pipeline dropped this record)
  ⚠️ SUPP_ID=9001 — extra in target (phantom/double-load record)
  🔄 SUPP_ID=1002 — email not lowercased in target
  🔄 SUPP_ID=1003 — country code not translated (raw 'I' instead of 'India')
  🔄 SUPP_ID=1004 — supplier name has extra spaces in target (trim issue)
  🔄 SUPP_ID=1006 — status not translated (raw 'S' instead of 'Suspended')
"""

import sqlite3
import os

BASE = os.path.dirname(__file__)
SOURCE_DB = os.path.join(BASE, "source_db.sqlite")
TARGET_DB = os.path.join(BASE, "target_db.sqlite")


# ── Source data (legacy system — raw codes, spaces, mixed case) ──────────────
SOURCE_ROWS = [
    # (SUPP_ID, SUPP_NM,            ADDR_LINE1,              CITY_NM,      STATE_NM,      CNTRY_CD, STAT_CD, CONT_EMAIL,                 CONT_PHONE,     TAX_ID)
    (1001, "  Tata Consultancy  ",   "12 MG Road",            "Mumbai",     "Maharashtra", "I",      "A",     "Procurement@TCS.COM",       "+91-22-67789900", "27AAACT2727Q1ZW"),
    (1002, "  Infosys Limited   ",   "Plot 44, Electronics City","Bengaluru","Karnataka",  "I",      "A",     "Vendor@INFOSYS.COM",         "+91-80-28520261", "29AAACI1681G1ZB"),
    (1003, "  Wipro Ltd         ",   "Sarjapur Road",         "Bengaluru",  "Karnataka",  "I",      "A",     "supplies@wipro.com",         "+91-80-28440011", "29AAACW0788E1ZB"),
    (1004, "  SAP SE            ",   "Dietmar-Hopp-Allee 16", "Walldorf",   "Baden-Wuerttemberg","G","A",     "procurement@sap.com",       "+49-6227-747474",  "DE111765569"),
    (1005, "  Oracle Corp       ",   "500 Oracle Parkway",    "Redwood City","California", "U",      "A",     "supplier@oracle.com",        "+1-650-506-7000",  "94-3082573"),
    (1006, "  Accenture Plc     ",   "1 Grand Canal Square",  "Dublin",     "Leinster",   "I",      "S",     "vendor@accenture.com",       "+353-1-6461000",   "IE4714791V"),
    (1007, "  Cognizant Tech    ",   "500 Frank W Burr Blvd", "Teaneck",    "New Jersey",  "U",      "A",     "supply@cognizant.com",       "+1-201-801-0233",  "22-3743833"),
    (1008, "  HCL Technologies  ",   "806 Siddharth Nagar",   "Noida",      "Uttar Pradesh","I",    "I",     "PROCUREMENT@HCL.COM",        "+91-120-6125000",  "09AAACH2866A1ZO"),
]

# ── Target data (DW after migration — with intentional errors) ────────────────
TARGET_ROWS = [
    # (supplier_id, supplier_name,      address,                  city,           state,                 country,    status,     contact_email,               contact_phone,     tax_id)
    # ✅ 1001 — clean migration (email lowercased, name trimmed, code translated)
    (1001, "Tata Consultancy",          "12 MG Road",             "Mumbai",       "Maharashtra",         "India",    "Active",   "procurement@tcs.com",       "+91-22-67789900", "27AAACT2727Q1ZW"),

    # ❌ 1002 — email NOT lowercased (bug in transformation)
    (1002, "Infosys Limited",           "Plot 44, Electronics City","Bengaluru",  "Karnataka",           "India",    "Active",   "Vendor@INFOSYS.COM",        "+91-80-28520261", "29AAACI1681G1ZB"),

    # ❌ 1003 — country NOT translated (raw code 'I' stored instead of 'India')
    (1003, "Wipro Ltd",                 "Sarjapur Road",           "Bengaluru",   "Karnataka",           "I",        "Active",   "supplies@wipro.com",        "+91-80-28440011", "29AAACW0788E1ZB"),

    # ❌ 1004 — supplier name NOT trimmed in target (spaces preserved, ETL failed to trim)
    (1004, "  SAP SE            ",      "Dietmar-Hopp-Allee 16",  "Walldorf",    "Baden-Wuerttemberg",  "Germany",  "Active",   "procurement@sap.com",       "+49-6227-747474",  "DE111765569"),

    # ❌ 1005 — MISSING (pipeline dropped this record entirely)
    # (skipped — not in target)

    # ❌ 1006 — status NOT translated ('S' stored instead of 'Suspended')
    (1006, "Accenture Plc",             "1 Grand Canal Square",   "Dublin",      "Leinster",            "India",    "S",        "vendor@accenture.com",       "+353-1-6461000",  "IE4714791V"),

    # ✅ 1007 — clean
    (1007, "Cognizant Tech",            "500 Frank W Burr Blvd",  "Teaneck",     "New Jersey",          "USA",      "Active",   "supply@cognizant.com",      "+1-201-801-0233", "22-3743833"),

    # ✅ 1008 — clean (email lowercased, status translated)
    (1008, "HCL Technologies",          "806 Siddharth Nagar",    "Noida",       "Uttar Pradesh",       "India",    "Inactive", "procurement@hcl.com",       "+91-120-6125000", "09AAACH2866A1ZO"),

    # ⚠️ 9001 — EXTRA record (phantom/double-load — not in source at all)
    (9001, "Ghost Vendor Ltd",          "Unknown",                 "Unknown",     "Unknown",             "India",    "Active",   "ghost@ghost.com",           "",                ""),
]


def create_source_db():
    if os.path.exists(SOURCE_DB):
        os.remove(SOURCE_DB)
    conn = sqlite3.connect(SOURCE_DB)
    conn.execute("""
        CREATE TABLE SUPPLIER_MASTER (
            SUPP_ID     INTEGER PRIMARY KEY,
            SUPP_NM     TEXT,
            ADDR_LINE1  TEXT,
            CITY_NM     TEXT,
            STATE_NM    TEXT,
            CNTRY_CD    TEXT,
            STAT_CD     TEXT,
            CONT_EMAIL  TEXT,
            CONT_PHONE  TEXT,
            TAX_ID      TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO SUPPLIER_MASTER VALUES (?,?,?,?,?,?,?,?,?,?)",
        SOURCE_ROWS
    )
    conn.commit()
    conn.close()
    print(f"✅ Source DB created : {SOURCE_DB}")
    print(f"   Table            : SUPPLIER_MASTER")
    print(f"   Rows             : {len(SOURCE_ROWS)}")


def create_target_db():
    if os.path.exists(TARGET_DB):
        os.remove(TARGET_DB)
    conn = sqlite3.connect(TARGET_DB)
    conn.execute("""
        CREATE TABLE supplier_master (
            supplier_id     INTEGER PRIMARY KEY,
            supplier_name   TEXT,
            address         TEXT,
            city            TEXT,
            state           TEXT,
            country         TEXT,
            status          TEXT,
            contact_email   TEXT,
            contact_phone   TEXT,
            tax_id          TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO supplier_master VALUES (?,?,?,?,?,?,?,?,?,?)",
        TARGET_ROWS
    )
    conn.commit()
    conn.close()
    print(f"✅ Target DB created : {TARGET_DB}")
    print(f"   Table            : supplier_master")
    print(f"   Rows             : {len(TARGET_ROWS)}")


def print_expected_issues():
    print("""
─────────────────────────────────────────────────────────
EXPECTED DISCREPANCIES IN RECONCILIATION REPORT
─────────────────────────────────────────────────────────
❌ SUPP_ID=1005  MISSING in target
   → Pipeline dropped Oracle Corp during migration

⚠️  SUPP_ID=9001  EXTRA in target (not in source)
   → Ghost vendor — possible double-load or manual insert

🔄 SUPP_ID=1002  Field mismatch: contact_email
   → Expected 'vendor@infosys.com' but got 'Vendor@INFOSYS.COM'
   → Transformation 'lower' was NOT applied

🔄 SUPP_ID=1003  Field mismatch: country
   → Expected 'India' (lookup I=India) but got 'I'
   → Lookup transformation was NOT applied

🔄 SUPP_ID=1004  Field mismatch: supplier_name
   → Expected 'SAP SE' (trim) but got '  SAP SE'
   → Trim transformation was NOT applied

🔄 SUPP_ID=1006  Field mismatch: status
   → Expected 'Suspended' (lookup S=Suspended) but got 'S'
   → Lookup transformation was NOT applied
─────────────────────────────────────────────────────────
Total issues: 1 missing + 1 extra + 4 field mismatches = 6
─────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    create_source_db()
    create_target_db()
    print_expected_issues()
    print("\nNow run:")
    print("""
  pipe-recon reconcile tests/fixtures/supplier_mapping.csv \\
      --source "sqlite:///tests/fixtures/source_db.sqlite" \\
      --target "sqlite:///tests/fixtures/target_db.sqlite" \\
      --table  SUPPLIER_MASTER \\
      --pipeline "Supplier_Master_Load" \\
      --html   tests/fixtures/recon_report.html
""")

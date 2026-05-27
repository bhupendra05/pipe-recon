# pipe-recon

**Enterprise pipeline reconciliation driven by your functional/technical mapping documents.**

Built for data engineers who reconcile pipelines manually — running SQL in target and source DBs, comparing rows in Excel, checking `load_date = CURRENT_DATE` one table at a time. `pipe-recon` automates that entire process using the mapping documents your BA team already wrote.

```bash
pip install pipe-recon
pipe-recon reconcile mapping/CRM_Mapping.csv \
  --source oracle://user:pass@crm-db:1521/CRMDB \
  --target sqlserver://user:pass@dw:1433/DataWarehouse \
  --table  CUSTOMER \
  --direction INBOUND \
  --filter "load_date = '2026-05-27'" \
  --html   report.html
```

---

## What it does

| Feature | Details |
|---------|---------|
| **Mapping-driven** | Reads your functional/technical mapping CSV or Excel — no config to rewrite |
| **INBOUND + OUTBOUND** | Source→Target AND Target→Source reconciliation in one tool |
| **Run-scoped** | `--filter "batch_id = 1042"` scopes to latest run, not whole table |
| **Field-level diff** | Checks every mapped field, respects transformations (trim, upper, lower, lookup, date_format) |
| **Enterprise DBs** | Oracle, SQL Server, PostgreSQL, MySQL, SQLite — credentials via `connections.yaml` |
| **HTML reports** | Professional run report to attach to JIRA / email stakeholders |
| **Auto-generates SQL** | Outputs the exact SQL used — paste into your SQL client to investigate |

---

## Installation

```bash
# Core (SQLite + CSV only)
pip install pipe-recon

# With Excel mapping support
pip install "pipe-recon[excel]"

# With database connectors
pip install "pipe-recon[postgres]"
pip install "pipe-recon[oracle]"
pip install "pipe-recon[sqlserver]"
pip install "pipe-recon[mysql]"

# Everything
pip install "pipe-recon[all]"
```

---

## Your Mapping Document

`pipe-recon` reads the same CSV or Excel your BA team uses. Standard columns:

| source_table | source_column | target_table | target_column | transformation | is_key | nullable | data_type |
|-------------|--------------|-------------|--------------|---------------|--------|---------|----------|
| CUSTOMER | CUST_ID | customers | customer_id | direct | yes | no | INTEGER |
| CUSTOMER | FIRST_NM | customers | first_name | trim | no | no | VARCHAR |
| CUSTOMER | EMAIL_ADDR | customers | email | lower | no | yes | VARCHAR |
| CUSTOMER | STAT_CD | customers | status | lookup: A=Active,I=Inactive | no | no | VARCHAR |

Column names are flexible — it understands `src_table`, `source table`, `from_table`, `tgt_column`, `target field`, `pk`, etc.

```bash
# Generate a sample mapping to fill in
pipe-recon sample-mapping mapping/my_mapping.csv
```

---

## Connections

### Option A — DSN string
```bash
pipe-recon reconcile mapping.csv \
  --source "postgresql://user:pass@host/crm" \
  --target "postgresql://user:pass@host/dw" \
  --table CUSTOMER
```

### Option B — `connections.yaml` (recommended for enterprise)
```yaml
# connections.yaml
source_crm:
  type: oracle
  host: db-prod-crm.corp.net
  port: 1521
  service: CRMDB
  user: recon_reader
  password: ${CRM_DB_PASSWORD}   # reads from env var — never hardcoded

target_dw:
  type: sqlserver
  host: dw-prod.corp.net
  port: 1433
  database: DataWarehouse
  user: recon_reader
  password: ${DW_DB_PASSWORD}
```

```bash
export CRM_DB_PASSWORD=...
export DW_DB_PASSWORD=...

pipe-recon reconcile mapping.csv \
  --source source_crm \
  --target target_dw \
  --table CUSTOMER \
  --direction INBOUND \
  --filter "load_date = CURRENT_DATE"
```

---

## Python API

```python
from reconpilot import load_mapping, connect_dsn, connect_from_config, reconcile_from_mapping
from reconpilot.report import to_html

# Load mapping document (CSV or Excel)
doc = load_mapping("mapping/CRM_Field_Mapping.csv")
doc.summary()

# Connect
src = connect_from_config("source_crm", "connections.yaml")
tgt = connect_from_config("target_dw",  "connections.yaml")

# Reconcile — INBOUND (source → DW)
result = reconcile_from_mapping(
    doc, src, tgt,
    source_table="CUSTOMER",
    direction="INBOUND",
    pipeline_name="CRM_Customer_Load",
    run_filter="load_date = '2026-05-27'",
)
result.print()

# Reconcile — OUTBOUND (DW → source, e.g. writeback pipeline)
result_out = reconcile_from_mapping(
    doc, src, tgt,
    source_table="CUSTOMER",
    direction="OUTBOUND",
    pipeline_name="CRM_Status_Writeback",
)

# HTML report for JIRA / email
to_html([result, result_out], "recon_report.html", project="CRM Migration — Sprint 12")

# JSON for CI/CD pipeline gate
import json
print(json.dumps(result.to_dict(), indent=2))

# Exit code 1 if issues found — use in CI
import sys
sys.exit(0 if result.is_clean else 1)
```

---

## Sample Output

```
🔍  CRM_Customer_Load  [INBOUND]  [❌ ISSUES FOUND]
    CUSTOMER → customers
    Filter: load_date = '2026-05-27'
    Generated: 2026-05-27 14:32:01

    Source rows : 45,231
    Target rows : 45,228  ❌ COUNT MISMATCH
    Matched keys: 45,228

    ❌ Missing in target: 3
       key = 10042
       key = 10891
       key = 11203

    Field (src→tgt)                   Transform                 Matched  Mismatch  Src-Null  Tgt-Null
    ----------------------------------------------------------------------------------------------------
       CUST_ID→customer_id            direct                     45,228         0         0         0
       FIRST_NM→first_name            trim                       45,228         0         0         0
    ❌ EMAIL_ADDR→email               lower                      45,105       123         0         0
         key=10001  src='Alice@Corp.com'  tgt='alice@corp.com'
       STAT_CD→status                 lookup: A=Active,I=I...    45,228         0         0         0
```

---

## Supported Transformations

| Mapping value | What it checks |
|--------------|---------------|
| `direct` / `as-is` / `none` | Exact string match |
| `trim` | Strips whitespace both sides |
| `upper` | Case-insensitive uppercase compare |
| `lower` | Case-insensitive lowercase compare |
| `date_format: YYYYMMDD→YYYY-MM-DD` | Strips separators, compares digits |
| `lookup: A=Active,I=Inactive` | Maps source code → target value |
| anything else | Falls back to string compare |

---

## CI/CD Integration

```yaml
# .github/workflows/recon.yml
- name: Reconcile CRM pipeline
  run: |
    pipe-recon reconcile mapping/CRM.csv \
      --source $SOURCE_DSN \
      --target $TARGET_DSN \
      --table CUSTOMER \
      --filter "load_date = CURRENT_DATE" \
      --html recon.html
  env:
    SOURCE_DSN: ${{ secrets.CRM_DSN }}
    TARGET_DSN: ${{ secrets.DW_DSN }}
```

---

## Who is this for?

- **Data engineers** at banks, insurance, retail who reconcile ETL pipelines daily
- **Migration teams** (Accenture, TCS, Infosys) doing source → DW cutover projects
- **DE/DW teams** who have functional mapping documents but no automated way to validate them

---

## License

MIT — [Bhupendra Tale](https://github.com/bhupendra05)

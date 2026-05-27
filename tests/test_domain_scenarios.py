"""
tests/test_domain_scenarios.py — Real-world enterprise domain scenarios.

Each class simulates a complete, realistic data migration pipeline
with domain-accurate table structures, field names, and data.

Scenarios:
  TC-D-01  Customer Master — clean CRM to DW migration
  TC-D-02  Customer Master — partial load failure (5 of 8 missing)
  TC-D-03  Supplier Master — all transformation types together
  TC-D-04  Employee Records — HR system to DW, status codes + trim
  TC-D-05  Order History — financial data, direct + lookup transforms
  TC-D-06  Product Catalog — mixed missing + extra + field errors
  TC-D-07  Invoice Data — date format + lookup + lower failures
  TC-D-08  OUTBOUND — Approved PO writeback to ERP
  TC-D-09  OUTBOUND — Customer status writeback to CRM
  TC-D-10  Bank Account Master — sensitive data, all fields direct
"""

import csv
import sqlite3
import pytest

from reconpilot.mapping import load_mapping
from reconpilot.connection import connect_dsn
from reconpilot.reconciler import reconcile_from_mapping


# ── Helpers ──────────────────────────────────────────────────────────────────

def _csv(tmp_path, rows, fname="map.csv"):
    header = ["source_table","source_column","target_table","target_column",
              "transformation","is_key","nullable","data_type","notes"]
    p = str(tmp_path / fname)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def _db(tmp_path, fname, table, schema, rows):
    p = str(tmp_path / fname)
    c = sqlite3.connect(p)
    c.execute(schema)
    if rows:
        cols = ", ".join(rows[0].keys())
        vals = ", ".join("?" * len(rows[0]))
        c.executemany(f"INSERT INTO {table} ({cols}) VALUES ({vals})",
                      [list(r.values()) for r in rows])
    c.commit(); c.close()
    return p


def _run(tmp_path, mapping_rows, src_rows, tgt_rows,
         src_table, tgt_table, src_schema, tgt_schema,
         direction="INBOUND", run_filter=None):
    mp = _csv(tmp_path, mapping_rows)
    sp = _db(tmp_path, "src.db", src_table, src_schema, src_rows)
    tp = _db(tmp_path, "tgt.db", tgt_table, tgt_schema, tgt_rows)
    doc = load_mapping(mp)
    src = connect_dsn(f"sqlite:///{sp}", name=src_table)
    tgt = connect_dsn(f"sqlite:///{tp}", name=tgt_table)
    r = reconcile_from_mapping(doc, src, tgt, src_table,
                               direction=direction, run_filter=run_filter)
    src.close(); tgt.close()
    return r


def _f(result, col):
    return next(f for f in result.field_results if f.target_column == col)


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-01  Customer Master — clean CRM → DW migration
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_01_CustomerMasterClean:
    MAPPING = [
        ["CUSTOMER","CUST_ID",   "dim_customer","customer_id",   "direct",                      "yes","no","INTEGER","PK"],
        ["CUSTOMER","CUST_FIRST","dim_customer","first_name",    "trim",                        "no", "no","VARCHAR",""],
        ["CUSTOMER","CUST_LAST", "dim_customer","last_name",     "trim",                        "no", "no","VARCHAR",""],
        ["CUSTOMER","EMAIL_ADDR","dim_customer","email",         "lower",                       "no", "no","VARCHAR",""],
        ["CUSTOMER","CUST_TYPE", "dim_customer","customer_type", "lookup: I=Individual|C=Corporate|G=Government","no","no","VARCHAR",""],
        ["CUSTOMER","CTRY_CD",   "dim_customer","country",       "lookup: IN=India|US=USA|AU=Australia","no","no","VARCHAR",""],
        ["CUSTOMER","STATUS",    "dim_customer","status",        "lookup: A=Active|I=Inactive|B=Blacklisted","no","no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE CUSTOMER (CUST_ID INTEGER, CUST_FIRST TEXT, CUST_LAST TEXT, EMAIL_ADDR TEXT, CUST_TYPE TEXT, CTRY_CD TEXT, STATUS TEXT)"
    TGT_SCHEMA = "CREATE TABLE dim_customer (customer_id INTEGER, first_name TEXT, last_name TEXT, email TEXT, customer_type TEXT, country TEXT, status TEXT)"

    SRC = [
        {"CUST_ID":1001,"CUST_FIRST":"  Priya  ","CUST_LAST":"  Sharma  ","EMAIL_ADDR":"PRIYA.S@GMAIL.COM","CUST_TYPE":"I","CTRY_CD":"IN","STATUS":"A"},
        {"CUST_ID":1002,"CUST_FIRST":"  Rahul  ","CUST_LAST":"  Verma   ","EMAIL_ADDR":"R.VERMA@CORP.IN", "CUST_TYPE":"C","CTRY_CD":"IN","STATUS":"A"},
        {"CUST_ID":1003,"CUST_FIRST":"  John   ","CUST_LAST":"  Smith   ","EMAIL_ADDR":"J.SMITH@GOV.AU",  "CUST_TYPE":"G","CTRY_CD":"AU","STATUS":"I"},
    ]
    TGT = [
        {"customer_id":1001,"first_name":"Priya","last_name":"Sharma","email":"priya.s@gmail.com","customer_type":"Individual","country":"India","status":"Active"},
        {"customer_id":1002,"first_name":"Rahul","last_name":"Verma", "email":"r.verma@corp.in",  "customer_type":"Corporate", "country":"India","status":"Active"},
        {"customer_id":1003,"first_name":"John", "last_name":"Smith", "email":"j.smith@gov.au",   "customer_type":"Government","country":"Australia","status":"Inactive"},
    ]

    def test_clean(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT,
                 "CUSTOMER", "dim_customer", self.SRC_SCHEMA, self.TGT_SCHEMA)
        assert r.is_clean

    def test_all_3_rows_matched(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT,
                 "CUSTOMER", "dim_customer", self.SRC_SCHEMA, self.TGT_SCHEMA)
        assert r.matched_keys == 3
        assert r.source_count == 3

    def test_zero_field_mismatches(self, tmp_path):
        r = _run(tmp_path, self.MAPPING, self.SRC, self.TGT,
                 "CUSTOMER", "dim_customer", self.SRC_SCHEMA, self.TGT_SCHEMA)
        assert r.total_field_mismatches == 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-02  Customer Master — partial load failure
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_02_CustomerMasterPartialLoad:
    MAPPING = [
        ["CUSTOMER","CUST_ID",   "dim_customer","customer_id","direct", "yes","no","INTEGER","PK"],
        ["CUSTOMER","CUST_FIRST","dim_customer","first_name", "trim",   "no", "no","VARCHAR",""],
        ["CUSTOMER","EMAIL_ADDR","dim_customer","email",      "lower",  "no", "no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE CUSTOMER (CUST_ID INTEGER, CUST_FIRST TEXT, EMAIL_ADDR TEXT)"
    TGT_SCHEMA = "CREATE TABLE dim_customer (customer_id INTEGER, first_name TEXT, email TEXT)"
    SRC = [{"CUST_ID": i, "CUST_FIRST": f"  Cust{i}  ", "EMAIL_ADDR": f"C{i}@TEST.COM"}
           for i in range(1, 9)]   # 8 customers

    def test_5_of_8_missing(self, tmp_path):
        # Only 3 made it to DW
        tgt = [{"customer_id":i,"first_name":f"Cust{i}","email":f"c{i}@test.com"} for i in (2,5,7)]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "CUSTOMER", "dim_customer", self.SRC_SCHEMA, self.TGT_SCHEMA)
        assert len(r.missing_in_target) == 5
        assert r.matched_keys == 3

    def test_missing_keys_are_correct(self, tmp_path):
        tgt = [{"customer_id":i,"first_name":f"Cust{i}","email":f"c{i}@test.com"} for i in (2,5,7)]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "CUSTOMER", "dim_customer", self.SRC_SCHEMA, self.TGT_SCHEMA)
        missing = {str(k) for k in r.missing_in_target}
        assert missing == {"1","3","4","6","8"}


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-03  Supplier Master — all transformation types together
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_03_SupplierMasterAllTransforms:
    MAPPING = [
        ["SUPPLIER","SUPP_ID",   "supplier_master","supplier_id",   "direct",                                "yes","no","INTEGER","PK"],
        ["SUPPLIER","SUPP_NM",   "supplier_master","supplier_name", "trim",                                  "no", "no","VARCHAR",""],
        ["SUPPLIER","CONT_EMAIL","supplier_master","contact_email", "lower",                                 "no", "yes","VARCHAR",""],
        ["SUPPLIER","CNTRY",     "supplier_master","country",       "lookup: I=India|U=USA|G=Germany",       "no", "no","VARCHAR",""],
        ["SUPPLIER","STAT",      "supplier_master","status",        "lookup: A=Active|I=Inactive|S=Suspended","no","no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE SUPPLIER (SUPP_ID INTEGER, SUPP_NM TEXT, CONT_EMAIL TEXT, CNTRY TEXT, STAT TEXT)"
    TGT_SCHEMA = "CREATE TABLE supplier_master (supplier_id INTEGER, supplier_name TEXT, contact_email TEXT, country TEXT, status TEXT)"

    def test_all_transforms_clean(self, tmp_path):
        src = [{"SUPP_ID":1,"SUPP_NM":"  Infosys  ","CONT_EMAIL":"VENDOR@INFOSYS.COM","CNTRY":"I","STAT":"A"}]
        tgt = [{"supplier_id":1,"supplier_name":"Infosys","contact_email":"vendor@infosys.com","country":"India","status":"Active"}]
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "SUPPLIER","supplier_master",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert r.is_clean

    def test_email_transform_failure(self, tmp_path):
        src = [{"SUPP_ID":1,"SUPP_NM":"  Wipro  ","CONT_EMAIL":"AP@WIPRO.COM","CNTRY":"I","STAT":"A"}]
        tgt = [{"supplier_id":1,"supplier_name":"Wipro","contact_email":"AP@WIPRO.COM","country":"India","status":"Active"}]
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "SUPPLIER","supplier_master",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"contact_email").mismatched == 1
        assert _f(r,"supplier_name").mismatched == 0

    def test_lookup_failure_country(self, tmp_path):
        src = [{"SUPP_ID":1,"SUPP_NM":"  SAP  ","CONT_EMAIL":"sap@sap.com","CNTRY":"G","STAT":"A"}]
        tgt = [{"supplier_id":1,"supplier_name":"SAP","contact_email":"sap@sap.com","country":"G","status":"Active"}]  # G not mapped
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "SUPPLIER","supplier_master",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"country").mismatched == 1

    def test_missing_supplier(self, tmp_path):
        src = [{"SUPP_ID":i,"SUPP_NM":f"  S{i}  ","CONT_EMAIL":f"s{i}@x.com","CNTRY":"I","STAT":"A"} for i in range(1,6)]
        tgt = [{"supplier_id":i,"supplier_name":f"S{i}","contact_email":f"s{i}@x.com","country":"India","status":"Active"} for i in range(1,4)]
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "SUPPLIER","supplier_master",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert len(r.missing_in_target) == 2


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-04  Employee Records — HR system to DW
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_04_EmployeeRecords:
    MAPPING = [
        ["EMPLOYEE","EMP_ID",   "dim_employee","employee_id",   "direct",                             "yes","no","INTEGER","PK"],
        ["EMPLOYEE","EMP_FIRST","dim_employee","first_name",    "trim",                               "no", "no","VARCHAR",""],
        ["EMPLOYEE","EMP_LAST", "dim_employee","last_name",     "trim",                               "no", "no","VARCHAR",""],
        ["EMPLOYEE","DEPT_CD",  "dim_employee","department",    "lookup: HR=Human Resources|IT=Information Technology|FIN=Finance|MKT=Marketing","no","no","VARCHAR",""],
        ["EMPLOYEE","EMPL_TYPE","dim_employee","employment_type","lookup: FT=Full-Time|PT=Part-Time|C=Contractor","no","no","VARCHAR",""],
        ["EMPLOYEE","EMPL_STAT","dim_employee","status",        "lookup: A=Active|R=Resigned|T=Terminated","no","no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE EMPLOYEE (EMP_ID INTEGER, EMP_FIRST TEXT, EMP_LAST TEXT, DEPT_CD TEXT, EMPL_TYPE TEXT, EMPL_STAT TEXT)"
    TGT_SCHEMA = "CREATE TABLE dim_employee (employee_id INTEGER, first_name TEXT, last_name TEXT, department TEXT, employment_type TEXT, status TEXT)"

    SRC = [
        {"EMP_ID":101,"EMP_FIRST":"  Arjun  ","EMP_LAST":"  Patel  ","DEPT_CD":"IT","EMPL_TYPE":"FT","EMPL_STAT":"A"},
        {"EMP_ID":102,"EMP_FIRST":"  Sneha  ","EMP_LAST":"  Kapoor ","DEPT_CD":"HR","EMPL_TYPE":"FT","EMPL_STAT":"A"},
        {"EMP_ID":103,"EMP_FIRST":"  Rohan  ","EMP_LAST":"  Mehta  ","DEPT_CD":"FIN","EMPL_TYPE":"C","EMPL_STAT":"R"},
        {"EMP_ID":104,"EMP_FIRST":"  Anjali ","EMP_LAST":"  Singh  ","DEPT_CD":"MKT","EMPL_TYPE":"PT","EMPL_STAT":"T"},
    ]

    def test_all_employees_clean(self, tmp_path):
        tgt = [
            {"employee_id":101,"first_name":"Arjun","last_name":"Patel","department":"Information Technology","employment_type":"Full-Time","status":"Active"},
            {"employee_id":102,"first_name":"Sneha","last_name":"Kapoor","department":"Human Resources","employment_type":"Full-Time","status":"Active"},
            {"employee_id":103,"first_name":"Rohan","last_name":"Mehta","department":"Finance","employment_type":"Contractor","status":"Resigned"},
            {"employee_id":104,"first_name":"Anjali","last_name":"Singh","department":"Marketing","employment_type":"Part-Time","status":"Terminated"},
        ]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "EMPLOYEE","dim_employee",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert r.is_clean

    def test_dept_lookup_failure(self, tmp_path):
        tgt = [
            {"employee_id":101,"first_name":"Arjun","last_name":"Patel","department":"IT","employment_type":"Full-Time","status":"Active"},  # dept not looked up
            {"employee_id":102,"first_name":"Sneha","last_name":"Kapoor","department":"Human Resources","employment_type":"Full-Time","status":"Active"},
        ]
        src = self.SRC[:2]
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "EMPLOYEE","dim_employee",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"department").mismatched == 1
        assert _f(r,"department").matched == 1

    def test_resigned_employee_missing(self, tmp_path):
        tgt = [
            {"employee_id":101,"first_name":"Arjun","last_name":"Patel","department":"Information Technology","employment_type":"Full-Time","status":"Active"},
            {"employee_id":102,"first_name":"Sneha","last_name":"Kapoor","department":"Human Resources","employment_type":"Full-Time","status":"Active"},
            # 103 (Resigned) missing — pipeline filtered out resigned employees
        ]
        src = self.SRC[:3]
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "EMPLOYEE","dim_employee",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert "103" in [str(k) for k in r.missing_in_target]


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-05  Order History — financial data
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_05_OrderHistory:
    MAPPING = [
        ["ORDERS","ORD_ID",   "fact_orders","order_id",    "direct",                       "yes","no","INTEGER","PK"],
        ["ORDERS","CUST_ID",  "fact_orders","customer_id", "direct",                       "no", "no","INTEGER","FK"],
        ["ORDERS","ORD_DT",   "fact_orders","order_date",  "date_format: YYYYMMDD→YYYY-MM-DD","no","no","DATE",""],
        ["ORDERS","ORD_STAT", "fact_orders","order_status","lookup: N=New|P=Processing|S=Shipped|D=Delivered|C=Cancelled","no","no","VARCHAR",""],
        ["ORDERS","TOT_AMT",  "fact_orders","total_amount","direct",                       "no", "no","DECIMAL",""],
        ["ORDERS","CRNCY_CD", "fact_orders","currency",    "upper",                        "no", "no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE ORDERS (ORD_ID INTEGER, CUST_ID INTEGER, ORD_DT TEXT, ORD_STAT TEXT, TOT_AMT REAL, CRNCY_CD TEXT)"
    TGT_SCHEMA = "CREATE TABLE fact_orders (order_id INTEGER, customer_id INTEGER, order_date TEXT, order_status TEXT, total_amount REAL, currency TEXT)"

    SRC = [
        {"ORD_ID":5001,"CUST_ID":101,"ORD_DT":"20260101","ORD_STAT":"D","TOT_AMT":15000.50,"CRNCY_CD":"inr"},
        {"ORD_ID":5002,"CUST_ID":102,"ORD_DT":"20260115","ORD_STAT":"S","TOT_AMT":8500.00, "CRNCY_CD":"usd"},
        {"ORD_ID":5003,"CUST_ID":103,"ORD_DT":"20260201","ORD_STAT":"N","TOT_AMT":3200.00, "CRNCY_CD":"eur"},
        {"ORD_ID":5004,"CUST_ID":101,"ORD_DT":"20260210","ORD_STAT":"C","TOT_AMT":500.00,  "CRNCY_CD":"inr"},
    ]

    def test_all_orders_clean(self, tmp_path):
        tgt = [
            {"order_id":5001,"customer_id":101,"order_date":"2026-01-01","order_status":"Delivered","total_amount":15000.50,"currency":"INR"},
            {"order_id":5002,"customer_id":102,"order_date":"2026-01-15","order_status":"Shipped",  "total_amount":8500.00, "currency":"USD"},
            {"order_id":5003,"customer_id":103,"order_date":"2026-02-01","order_status":"New",      "total_amount":3200.00, "currency":"EUR"},
            {"order_id":5004,"customer_id":101,"order_date":"2026-02-10","order_status":"Cancelled","total_amount":500.00,  "currency":"INR"},
        ]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "ORDERS","fact_orders",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert r.is_clean

    def test_date_same_value_different_format_matches(self, tmp_path):
        """date_format is separator-agnostic: 20260101 and 2026-01-01 both reduce to same digits."""
        tgt = [{"order_id":5001,"customer_id":101,"order_date":"20260101","order_status":"Delivered","total_amount":15000.50,"currency":"INR"}]
        r = _run(tmp_path, self.MAPPING, self.SRC[:1], tgt,
                 "ORDERS","fact_orders",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"order_date").mismatched == 0   # same date, just not re-formatted

    def test_different_date_is_mismatch(self, tmp_path):
        """A genuinely wrong date stored in target is caught."""
        tgt = [{"order_id":5001,"customer_id":101,"order_date":"2026-12-31","order_status":"Delivered","total_amount":15000.50,"currency":"INR"}]
        r = _run(tmp_path, self.MAPPING, self.SRC[:1], tgt,
                 "ORDERS","fact_orders",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"order_date").mismatched == 1

    def test_currency_not_uppercased(self, tmp_path):
        tgt = [{"order_id":5001,"customer_id":101,"order_date":"2026-01-01","order_status":"Delivered","total_amount":15000.50,"currency":"inr"}]
        r = _run(tmp_path, self.MAPPING, self.SRC[:1], tgt,
                 "ORDERS","fact_orders",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"currency").mismatched == 1

    def test_order_status_lookup_failure(self, tmp_path):
        tgt = [{"order_id":5003,"customer_id":103,"order_date":"2026-02-01","order_status":"N","total_amount":3200.00,"currency":"EUR"}]
        r = _run(tmp_path, self.MAPPING, self.SRC[2:3], tgt,
                 "ORDERS","fact_orders",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"order_status").mismatched == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-06  Product Catalog — missing + extra + field mismatches
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_06_ProductCatalogMixed:
    MAPPING = [
        ["PRODUCT","PROD_ID",  "dim_product","product_id",  "direct",                         "yes","no","INTEGER","PK"],
        ["PRODUCT","PROD_NM",  "dim_product","product_name","trim",                            "no", "no","VARCHAR",""],
        ["PRODUCT","CAT_CD",   "dim_product","category",    "lookup: E=Electronics|C=Clothing|F=Food|H=Home","no","no","VARCHAR",""],
        ["PRODUCT","UNIT_PRC", "dim_product","unit_price",  "direct",                         "no", "no","DECIMAL",""],
        ["PRODUCT","IS_ACTIVE","dim_product","is_active",   "lookup: Y=Yes|N=No",              "no", "no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE PRODUCT (PROD_ID INTEGER, PROD_NM TEXT, CAT_CD TEXT, UNIT_PRC REAL, IS_ACTIVE TEXT)"
    TGT_SCHEMA = "CREATE TABLE dim_product (product_id INTEGER, product_name TEXT, category TEXT, unit_price REAL, is_active TEXT)"

    SRC = [
        {"PROD_ID":1,"PROD_NM":"  Laptop Pro  ","CAT_CD":"E","UNIT_PRC":85000.0,"IS_ACTIVE":"Y"},
        {"PROD_ID":2,"PROD_NM":"  Office Chair ","CAT_CD":"H","UNIT_PRC":12000.0,"IS_ACTIVE":"Y"},
        {"PROD_ID":3,"PROD_NM":"  Rice Basmati ","CAT_CD":"F","UNIT_PRC":250.0,  "IS_ACTIVE":"Y"},
        {"PROD_ID":4,"PROD_NM":"  T-Shirt XL   ","CAT_CD":"C","UNIT_PRC":799.0,  "IS_ACTIVE":"N"},
        {"PROD_ID":5,"PROD_NM":"  Headphones   ","CAT_CD":"E","UNIT_PRC":4500.0, "IS_ACTIVE":"Y"},
    ]

    def test_mixed_errors(self, tmp_path):
        tgt = [
            {"product_id":1,"product_name":"Laptop Pro","category":"Electronics","unit_price":85000.0,"is_active":"Yes"},   # clean
            # PROD_ID=2 missing
            {"product_id":3,"product_name":"Rice Basmati","category":"F","unit_price":250.0,"is_active":"Yes"},   # category not looked up
            {"product_id":4,"product_name":"  T-Shirt XL  ","category":"Clothing","unit_price":799.0,"is_active":"No"},  # name not trimmed
            {"product_id":5,"product_name":"Headphones","category":"Electronics","unit_price":4500.0,"is_active":"Yes"},   # clean
            {"product_id":999,"product_name":"Ghost Product","category":"Electronics","unit_price":0.0,"is_active":"No"},  # extra
        ]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "PRODUCT","dim_product",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert len(r.missing_in_target) == 1
        assert "2" in [str(k) for k in r.missing_in_target]
        assert len(r.extra_in_target) == 1
        assert "999" in [str(k) for k in r.extra_in_target]
        assert _f(r,"category").mismatched == 1
        assert _f(r,"product_name").mismatched == 1
        assert not r.is_clean


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-07  Invoice Data — date + lookup + lower all failing
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_07_InvoiceAllFailing:
    MAPPING = [
        ["INVOICE","INV_ID",   "fact_invoice","invoice_id",   "direct",                          "yes","no","INTEGER","PK"],
        ["INVOICE","VEND_NM",  "fact_invoice","vendor_name",  "trim",                            "no", "no","VARCHAR",""],
        ["INVOICE","INV_DT",   "fact_invoice","invoice_date", "date_format: YYYYMMDD→YYYY-MM-DD","no", "no","DATE",""],
        ["INVOICE","PAY_STAT", "fact_invoice","payment_status","lookup: P=Paid|U=Unpaid|O=Overdue","no","no","VARCHAR",""],
        ["INVOICE","CONT_EMAIL","fact_invoice","contact_email","lower",                           "no","yes","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE INVOICE (INV_ID INTEGER, VEND_NM TEXT, INV_DT TEXT, PAY_STAT TEXT, CONT_EMAIL TEXT)"
    TGT_SCHEMA = "CREATE TABLE fact_invoice (invoice_id INTEGER, vendor_name TEXT, invoice_date TEXT, payment_status TEXT, contact_email TEXT)"

    def test_three_transforms_fail_date_is_lenient(self, tmp_path):
        """
        trim, lookup, lower failures are caught.
        date_format is separator-agnostic — 20260301 == 20260301 → match.
        """
        src = [{"INV_ID":1,"VEND_NM":"  BigSupplier  ","INV_DT":"20260301","PAY_STAT":"P","CONT_EMAIL":"AP@SUPPLIER.COM"}]
        tgt = [{"invoice_id":1,"vendor_name":"  BigSupplier  ","invoice_date":"20260301","payment_status":"P","contact_email":"AP@SUPPLIER.COM"}]
        r = _run(tmp_path, self.MAPPING, src, tgt,
                 "INVOICE","fact_invoice",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"vendor_name").mismatched == 1       # trim not applied
        assert _f(r,"invoice_date").mismatched == 0      # date_format is lenient — same digits
        assert _f(r,"payment_status").mismatched == 1    # lookup not applied
        assert _f(r,"contact_email").mismatched == 1     # lower not applied
        assert r.total_field_mismatches == 3


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-08  OUTBOUND — Purchase Order approval writeback to ERP
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_08_OutboundPOWriteback:
    """DW approves POs and writes the approval status back to the ERP source system."""
    MAPPING = [
        ["PO_ERP","PO_ID",       "po_dw", "po_id",       "direct", "yes","no","INTEGER","PK"],
        ["PO_ERP","PO_VENDOR",   "po_dw", "vendor_name", "trim",   "no", "no","VARCHAR",""],
        ["PO_ERP","APPROVAL_STAT","po_dw","approval_status","direct","no","no","VARCHAR",""],
        ["PO_ERP","APPROVAL_DT", "po_dw", "approval_date","direct", "no","yes","DATE",   ""],
    ]
    SRC_SCHEMA = "CREATE TABLE PO_ERP (PO_ID INTEGER, PO_VENDOR TEXT, APPROVAL_STAT TEXT, APPROVAL_DT TEXT)"
    TGT_SCHEMA = "CREATE TABLE po_dw  (po_id INTEGER, vendor_name TEXT, approval_status TEXT, approval_date TEXT)"

    def test_outbound_clean(self, tmp_path):
        # ERP has received all DW approvals correctly
        erp = [
            {"PO_ID":201,"PO_VENDOR":"Infosys","APPROVAL_STAT":"Approved","APPROVAL_DT":"2026-05-20"},
            {"PO_ID":202,"PO_VENDOR":"Wipro",  "APPROVAL_STAT":"Approved","APPROVAL_DT":"2026-05-21"},
        ]
        dw = [
            {"po_id":201,"vendor_name":"Infosys","approval_status":"Approved","approval_date":"2026-05-20"},
            {"po_id":202,"vendor_name":"Wipro",  "approval_status":"Approved","approval_date":"2026-05-21"},
        ]
        r = _run(tmp_path, self.MAPPING, erp, dw,
                 "PO_ERP","po_dw",self.SRC_SCHEMA,self.TGT_SCHEMA,
                 direction="OUTBOUND")
        assert r.direction == "OUTBOUND"
        assert r.is_clean

    def test_outbound_missing_writeback(self, tmp_path):
        # DW approved 3 POs but only 2 were written back to ERP
        erp = [
            {"PO_ID":201,"PO_VENDOR":"Infosys","APPROVAL_STAT":"Pending","APPROVAL_DT":None},
            {"PO_ID":202,"PO_VENDOR":"Wipro",  "APPROVAL_STAT":"Pending","APPROVAL_DT":None},
            {"PO_ID":203,"PO_VENDOR":"HCL",    "APPROVAL_STAT":"Pending","APPROVAL_DT":None},
        ]
        dw = [
            {"po_id":201,"vendor_name":"Infosys","approval_status":"Approved","approval_date":"2026-05-20"},
            {"po_id":202,"vendor_name":"Wipro",  "approval_status":"Approved","approval_date":"2026-05-21"},
            # PO 203 not written back
        ]
        r = _run(tmp_path, self.MAPPING, erp, dw,
                 "PO_ERP","po_dw",self.SRC_SCHEMA,self.TGT_SCHEMA,
                 direction="OUTBOUND")
        # In OUTBOUND, DW is authoritative. PO 203 is in ERP (source) but not in DW → extra_in_target
        assert r.direction == "OUTBOUND"
        assert not r.is_clean


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-09  OUTBOUND — Customer status writeback to CRM
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_09_OutboundCRMStatusWriteback:
    MAPPING = [
        ["CRM_CUST","CUST_ID",  "dw_cust","customer_id","direct","yes","no","INTEGER","PK"],
        ["CRM_CUST","CUST_STAT","dw_cust","status",     "direct","no", "no","VARCHAR",""],
        ["CRM_CUST","UPDATED_DT","dw_cust","updated_date","direct","no","yes","DATE",""],
    ]
    SRC_SCHEMA = "CREATE TABLE CRM_CUST (CUST_ID INTEGER, CUST_STAT TEXT, UPDATED_DT TEXT)"
    TGT_SCHEMA = "CREATE TABLE dw_cust (customer_id INTEGER, status TEXT, updated_date TEXT)"

    def test_status_writeback_clean(self, tmp_path):
        crm = [
            {"CUST_ID":1001,"CUST_STAT":"Active",    "UPDATED_DT":"2026-05-27"},
            {"CUST_ID":1002,"CUST_STAT":"Blacklisted","UPDATED_DT":"2026-05-27"},
        ]
        dw  = [
            {"customer_id":1001,"status":"Active",    "updated_date":"2026-05-27"},
            {"customer_id":1002,"status":"Blacklisted","updated_date":"2026-05-27"},
        ]
        r = _run(tmp_path, self.MAPPING, crm, dw,
                 "CRM_CUST","dw_cust",self.SRC_SCHEMA,self.TGT_SCHEMA,
                 direction="OUTBOUND")
        assert r.direction == "OUTBOUND"
        assert r.is_clean


# ─────────────────────────────────────────────────────────────────────────────
# TC-D-10  Bank Account Master — all fields direct, strict matching
# ─────────────────────────────────────────────────────────────────────────────
class TestTC_D_10_BankAccountMaster:
    MAPPING = [
        ["BANK_ACCT","ACCT_ID",    "bank_account","account_id",      "direct","yes","no","INTEGER","PK"],
        ["BANK_ACCT","ACCT_NM",    "bank_account","account_name",    "direct","no", "no","VARCHAR",""],
        ["BANK_ACCT","BANK_CD",    "bank_account","bank_code",       "direct","no", "no","VARCHAR","IFSC"],
        ["BANK_ACCT","ACCT_TYPE",  "bank_account","account_type",    "direct","no", "no","VARCHAR",""],
        ["BANK_ACCT","BRANCH_NM",  "bank_account","branch_name",     "direct","no", "no","VARCHAR",""],
    ]
    SRC_SCHEMA = "CREATE TABLE BANK_ACCT (ACCT_ID INTEGER, ACCT_NM TEXT, BANK_CD TEXT, ACCT_TYPE TEXT, BRANCH_NM TEXT)"
    TGT_SCHEMA = "CREATE TABLE bank_account (account_id INTEGER, account_name TEXT, bank_code TEXT, account_type TEXT, branch_name TEXT)"

    SRC = [
        {"ACCT_ID":1,"ACCT_NM":"Tata Steel Ltd", "BANK_CD":"HDFC0001234","ACCT_TYPE":"Current","BRANCH_NM":"Mumbai Main"},
        {"ACCT_ID":2,"ACCT_NM":"Infosys Ltd",    "BANK_CD":"ICIC0005678","ACCT_TYPE":"Current","BRANCH_NM":"Bengaluru MG Road"},
        {"ACCT_ID":3,"ACCT_NM":"Wipro Ltd",      "BANK_CD":"SBIN0009012","ACCT_TYPE":"Savings", "BRANCH_NM":"Bengaluru Electronic City"},
    ]

    def test_bank_accounts_clean(self, tmp_path):
        tgt = [
            {"account_id":1,"account_name":"Tata Steel Ltd", "bank_code":"HDFC0001234","account_type":"Current","branch_name":"Mumbai Main"},
            {"account_id":2,"account_name":"Infosys Ltd",    "bank_code":"ICIC0005678","account_type":"Current","branch_name":"Bengaluru MG Road"},
            {"account_id":3,"account_name":"Wipro Ltd",      "bank_code":"SBIN0009012","account_type":"Savings", "branch_name":"Bengaluru Electronic City"},
        ]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "BANK_ACCT","bank_account",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert r.is_clean
        assert r.matched_keys == 3

    def test_wrong_bank_code_detected(self, tmp_path):
        tgt = [
            {"account_id":1,"account_name":"Tata Steel Ltd","bank_code":"HDFC0009999","account_type":"Current","branch_name":"Mumbai Main"},  # wrong IFSC
            {"account_id":2,"account_name":"Infosys Ltd",   "bank_code":"ICIC0005678","account_type":"Current","branch_name":"Bengaluru MG Road"},
            {"account_id":3,"account_name":"Wipro Ltd",     "bank_code":"SBIN0009012","account_type":"Savings", "branch_name":"Bengaluru Electronic City"},
        ]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "BANK_ACCT","bank_account",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert _f(r,"bank_code").mismatched == 1
        assert not r.is_clean

    def test_missing_account_in_dw(self, tmp_path):
        tgt = [
            {"account_id":1,"account_name":"Tata Steel Ltd","bank_code":"HDFC0001234","account_type":"Current","branch_name":"Mumbai Main"},
            # accounts 2 and 3 missing — pipeline filter bug
        ]
        r = _run(tmp_path, self.MAPPING, self.SRC, tgt,
                 "BANK_ACCT","bank_account",self.SRC_SCHEMA,self.TGT_SCHEMA)
        assert len(r.missing_in_target) == 2
        missing = {str(k) for k in r.missing_in_target}
        assert missing == {"2","3"}

"""
reconpilot.connection — enterprise DB connection management.

Supports: PostgreSQL, MySQL, Oracle, SQL Server, SQLite, CSV.
Loads credentials from a connections.yaml / .env file — never hardcoded.

connections.yaml format:
  source_crm:
    type: oracle
    host: db-prod-crm.corp.net
    port: 1521
    service: CRMDB
    user: recon_reader
    password: ${CRM_DB_PASSWORD}   # reads from env var

  target_dw:
    type: sqlserver
    host: dw-prod.corp.net
    port: 1433
    database: DataWarehouse
    user: recon_reader
    password: ${DW_DB_PASSWORD}
"""

from __future__ import annotations
import os
import re
from typing import Any


class Connection:
    """Thin wrapper around a DB connection with a uniform query interface."""

    def __init__(self, name: str, conn_type: str, raw_conn):
        self.name = name
        self.type = conn_type
        self._conn = raw_conn

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute SQL and return list of dicts."""
        if self.type == "sqlite":
            import sqlite3
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

        elif self.type in ("postgresql", "postgres"):
            import psycopg2.extras
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]

        elif self.type == "mysql":
            cur = self._conn.cursor(dictionary=True)
            cur.execute(sql, params)
            return cur.fetchall()

        elif self.type == "oracle":
            cur = self._conn.cursor()
            cur.execute(sql)
            cols = [d[0].lower() for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

        elif self.type == "sqlserver":
            cur = self._conn.cursor()
            cur.execute(sql)
            cols = [d[0].lower() for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

        raise NotImplementedError(f"Unsupported type: {self.type}")

    def columns(self, table: str) -> list[dict]:
        """Return column metadata for a table."""
        if self.type == "sqlite":
            rows = self.query(f"PRAGMA table_info({table})")
            return [{"name": r["name"], "type": r["type"]} for r in rows]

        elif self.type in ("postgresql", "postgres"):
            rows = self.query("""
                SELECT column_name as name, data_type as type
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = 'public'
                ORDER BY ordinal_position
            """, (table.lower(),))
            return rows

        elif self.type in ("mysql",):
            rows = self.query(f"DESCRIBE {table}")
            return [{"name": r["Field"], "type": r["Type"]} for r in rows]

        elif self.type in ("oracle",):
            rows = self.query(
                "SELECT column_name as name, data_type as type FROM user_tab_columns WHERE table_name = :1",
                (table.upper(),)
            )
            return rows

        elif self.type == "sqlserver":
            rows = self.query("""
                SELECT column_name as name, data_type as type
                FROM information_schema.columns WHERE table_name = ?
            """, (table,))
            return rows

        return []

    def count(self, table: str, where: str | None = None) -> int:
        sql = f"SELECT COUNT(*) as n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        rows = self.query(sql)
        return int(rows[0].get("n", rows[0].get("count(*)", 0)))

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def _resolve_env(value: str) -> str:
    """Replace ${VAR_NAME} placeholders with environment variable values."""
    def replace(m):
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            raise EnvironmentError(
                f"Environment variable '{var}' is required for DB connection but not set.\n"
                f"Set it with: export {var}=your_password"
            )
        return val
    return re.sub(r'\$\{([^}]+)\}', replace, value)


def connect_from_config(name: str, config_path: str = "connections.yaml") -> Connection:
    """
    Load connection config from a YAML file and connect.

    Args:
        name: Connection name key in connections.yaml
        config_path: Path to the connections config file.

    Returns:
        Connection instance.

    Example:
        conn = connect_from_config("source_crm")
        rows = conn.query("SELECT * FROM CUSTOMER WHERE ROWNUM <= 10")
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("pip install pipe-recon[yaml] for YAML config support")

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    if name not in cfg:
        available = list(cfg.keys())
        raise KeyError(f"Connection '{name}' not found in {config_path}. Available: {available}")

    c = {k: (_resolve_env(str(v)) if isinstance(v, str) else v) for k, v in cfg[name].items()}
    conn_type = c.get("type", "").lower()

    if conn_type == "sqlite":
        import sqlite3
        raw = sqlite3.connect(c["path"])

    elif conn_type in ("postgresql", "postgres"):
        try:
            import psycopg2
        except ImportError:
            raise ImportError("pip install pipe-recon[postgres]")
        raw = psycopg2.connect(
            host=c.get("host"), port=c.get("port", 5432),
            dbname=c.get("database", c.get("dbname")),
            user=c.get("user"), password=c.get("password"),
        )
        raw.autocommit = True

    elif conn_type == "mysql":
        try:
            import mysql.connector
        except ImportError:
            raise ImportError("pip install pipe-recon[mysql]")
        raw = mysql.connector.connect(
            host=c.get("host"), port=c.get("port", 3306),
            database=c.get("database"), user=c.get("user"), password=c.get("password"),
        )

    elif conn_type == "oracle":
        try:
            import cx_Oracle
        except ImportError:
            raise ImportError("pip install cx_Oracle  (Oracle client libs also required)")
        dsn = cx_Oracle.makedsn(c["host"], c.get("port", 1521), service_name=c.get("service"))
        raw = cx_Oracle.connect(c["user"], c["password"], dsn)

    elif conn_type == "sqlserver":
        try:
            import pyodbc
        except ImportError:
            raise ImportError("pip install pyodbc  (ODBC driver also required)")
        cs = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={c['host']},{c.get('port', 1433)};"
            f"DATABASE={c['database']};UID={c['user']};PWD={c['password']}"
        )
        raw = pyodbc.connect(cs)

    else:
        raise ValueError(f"Unsupported connection type: '{conn_type}'. "
                         f"Supported: sqlite, postgresql, mysql, oracle, sqlserver")

    return Connection(name=name, conn_type=conn_type, raw_conn=raw)


def connect_dsn(dsn: str, name: str = "db") -> Connection:
    """
    Connect via a DSN string (same format as migra-check).

    Supported:
      sqlite:///path/to/db.sqlite
      postgresql://user:pass@host:port/dbname
      mysql://user:pass@host:port/dbname

    Args:
        dsn: DSN connection string.
        name: Display name for this connection.
    """
    if dsn.startswith("sqlite:///"):
        import sqlite3
        raw = sqlite3.connect(dsn[len("sqlite:///"):])
        return Connection(name=name, conn_type="sqlite", raw_conn=raw)

    elif dsn.startswith(("postgresql://", "postgres://")):
        try:
            import psycopg2
        except ImportError:
            raise ImportError("pip install pipe-recon[postgres]")
        raw = psycopg2.connect(dsn)
        raw.autocommit = True
        return Connection(name=name, conn_type="postgresql", raw_conn=raw)

    elif dsn.startswith("mysql://"):
        try:
            import mysql.connector
        except ImportError:
            raise ImportError("pip install pipe-recon[mysql]")
        # parse mysql://user:pass@host:port/db
        import urllib.parse
        p = urllib.parse.urlparse(dsn)
        raw = mysql.connector.connect(
            host=p.hostname, port=p.port or 3306,
            database=p.path.lstrip("/"),
            user=p.username, password=p.password,
        )
        return Connection(name=name, conn_type="mysql", raw_conn=raw)

    raise ValueError(f"Cannot parse DSN: {dsn}")

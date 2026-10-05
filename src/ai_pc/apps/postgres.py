"""PostgreSQL 18 (EDB's binaries zip in tools/postgres; they carry no signature, so its bin/ was checked byte for byte
against Maven Central's io.zonky embedded-postgres package, see tools/postgres/SOURCE.txt): a real database server run here only on
127.0.0.1, its data in tools/postgres/data, started for the job and stopped cleanly after. A database from words (a shop:
products, customers, orders, order items, with keys and checks; other tables get id + name), filled with sample rows,
a sales report, and a pg_dump backup; or a CSV/Excel sheet imported as a table (column types worked out); or a .sql file
run. Checked by the database itself: the tables, columns and foreign keys are there, a wrong row (an order for a customer
that does not exist, a negative price) is refused, and the report's sums equal the same sums done in Python.

  'postgres database for a shop with products, customers and orders'   'postgres import sales.xlsx'   'postgres run report.sql'
"""
import csv
import io
import os
import re
import socket
import time
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "postgres", "PostgreSQL: a real local database server: schemas from words, sheet imports, .sql runs, backups"
EXAMPLES = ["postgres database for a shop with products, customers and orders", "postgres import sales.xlsx", "postgres run report.sql"]
HOME = ROOT / "tools" / "postgres"
DATA = HOME / "data"

SHOP = """
CREATE TABLE customers (
  id serial PRIMARY KEY,
  name text NOT NULL,
  phone text,
  city text
);
CREATE TABLE products (
  id serial PRIMARY KEY,
  name text NOT NULL UNIQUE,
  price numeric(12,2) NOT NULL CHECK (price >= 0),
  stock integer NOT NULL DEFAULT 0 CHECK (stock >= 0)
);
CREATE TABLE orders (
  id serial PRIMARY KEY,
  customer_id integer NOT NULL REFERENCES customers(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'paid', 'shipped', 'cancelled'))
);
CREATE TABLE order_items (
  order_id integer NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id integer NOT NULL REFERENCES products(id),
  quantity integer NOT NULL CHECK (quantity > 0),
  price numeric(12,2) NOT NULL CHECK (price >= 0),
  PRIMARY KEY (order_id, product_id)
);
CREATE INDEX ON orders (customer_id);
"""
SAMPLE_CUSTOMERS = [("Ali Khan", "0300-1234567", "Lahore"), ("Sara Ahmed", "0321-7654321", "Karachi"), ("Usman Raza", "0333-1112223", "Islamabad")]
SAMPLE_PRODUCTS = [("Ceiling fan", 4500, 20), ("Steam iron", 3200, 15), ("Kettle", 2100, 30), ("LED bulb", 350, 200)]
SAMPLE_ORDERS = [(1, "paid", [(1, 2), (4, 10)]), (2, "paid", [(2, 1), (3, 2)]), (1, "shipped", [(3, 1)]), (3, "new", [(1, 1), (2, 1), (4, 4)])]
REPORT = """SELECT c.name, count(DISTINCT o.id) AS orders, sum(i.quantity * i.price) AS total
FROM customers c JOIN orders o ON o.customer_id = c.id JOIN order_items i ON i.order_id = o.id
WHERE o.status <> 'cancelled' GROUP BY c.name ORDER BY total DESC;"""


def bin_dir():
    hits = sorted(HOME.rglob("pg_ctl.exe")) if HOME.exists() else []
    return hits[0].parent if hits else None


def env():
    h = (HOME / "home").resolve()
    h.mkdir(parents=True, exist_ok=True)
    return dict(os.environ, PSQL_HISTORY=str(h / "psql_history"), PGPASSFILE=str(h / "pgpass"), PGSYSCONFDIR=str(h), PGTZ="Asia/Karachi")


class Server:
    """A local PostgreSQL started for one job on 127.0.0.1 (a free port), stopped cleanly by close()."""

    def __init__(self):
        from ai_pc.core import hidden_desktop
        b = bin_dir()
        self.b = b
        if not (DATA / "PG_VERSION").exists():
            DATA.mkdir(parents=True, exist_ok=True)
            rc, o, e, _ = hidden_desktop.run([str(b / "initdb.exe"), "-D", str(DATA), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"],
                                             timeout=300, env=env())
            if rc != 0:
                raise RuntimeError(f"initdb failed: {(e or o)[-300:]}")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.proc = hidden_desktop.start([str(b / "postgres.exe"), "-D", str(DATA), "-p", str(self.port), "-c", "listen_addresses=127.0.0.1"],
                                         env=env())
        end = time.monotonic() + 60
        while time.monotonic() < end:
            ok, _ = self.psql("SELECT 1", db="postgres")
            if ok:
                return
            if not self.proc.alive():
                break
            time.sleep(0.5)
        self.close()
        raise RuntimeError("PostgreSQL did not start")

    def psql(self, sql=None, db="postgres", file=None, csv_out=False, restrict=False):
        """restrict: a file given by the user runs in psql's restricted mode (a random key it cannot know), so its backslash
        commands (\\! runs a shell command) are refused; plain SQL and COPY data still run."""
        import secrets

        from ai_pc.core import hidden_desktop
        args = [str(self.b / "psql.exe"), "-X", "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-q"]
        if csv_out:
            args += ["--csv"]
        if file and restrict:
            args += ["-c", "\\restrict " + secrets.token_hex(16)]
        args += ["-f", str(file)] if file else ["-c", sql]
        rc, o, e, _ = hidden_desktop.run(args, timeout=300, env=env())
        return rc == 0, (o if rc == 0 else (e or o))

    def dump(self, db, dest):
        from ai_pc.core import hidden_desktop
        rc, o, e, _ = hidden_desktop.run([str(self.b / "pg_dump.exe"), "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", "-f", str(dest), db],
                                         timeout=300, env=env())
        return rc == 0

    def close(self):
        from ai_pc.core import hidden_desktop
        hidden_desktop.run([str(self.b / "pg_ctl.exe"), "stop", "-D", str(DATA), "-m", "fast", "-w"], timeout=120, env=env())
        self.proc.wait(20)
        self.proc.stop()


def rows(text):
    return list(csv.reader(io.StringIO(text.strip()))) if text.strip() else []


def sql_text(v):
    return "NULL" if v is None or v == "" else ("'" + str(v).replace("'", "''") + "'")


def infer(values):
    vals = [v for v in values if v not in (None, "")]
    if vals and all(re.fullmatch(r"-?\d+", str(v).replace(",", "")) for v in vals):
        return "bigint"
    if vals and all(re.fullmatch(r"-?\d+(?:\.\d+)?", str(v).replace(",", "")) for v in vals):
        return "numeric"
    if vals and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?", str(v)) for v in vals):
        return "timestamp"
    return "text"


def ident(name):
    s = re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower()).strip("_") or "col"
    return s if not s[0].isdigit() else "c_" + s


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bpostgres(?:ql)?\b|\bpsql\b|\bpgadmin\b", c):
        return None
    f = find_file(text, ctx, {".sql"})
    if f:
        return {"op": "sql", "file": f}
    f = find_file(text, ctx, {".csv", ".xlsx"})
    if f and re.search(r"\bimport\b|\bload\b|\btable\b", c):
        return {"op": "import", "file": f}
    if re.search(r"\bdatabase\b|\bschema\b|\bdb\b", c):
        tables = [t for t in ("customers", "products", "orders") if re.search(rf"\b{t[:-1]}s?\b", c)]
        return {"op": "shop", "tables": tables or ["customers", "products", "orders"]}
    return None


def run(op, ctx):
    if not bin_dir():
        return "PostgreSQL is not in tools/postgres."
    out = (Path(ctx["out"]) / "postgres").resolve()
    out.mkdir(parents=True, exist_ok=True)
    srv = Server()
    try:
        if op["op"] == "sql":
            db = "work"
            srv.psql(f"DROP DATABASE IF EXISTS {db}")
            srv.psql(f"CREATE DATABASE {db}")
            ok, res = srv.psql(db=db, file=Path(op["file"]).resolve(), csv_out=True, restrict=True)
            (out / (Path(op["file"]).stem + "_result.csv")).write_text(res, encoding="utf-8")
            return (f"PostgreSQL ran {Path(op['file']).name}: " + (f"done; result in {Path(op['file']).stem}_result.csv: " + " | ".join(res.strip().splitlines()[:4])
                                                                   if ok else "FAILED: " + res.strip()[-400:]))
        if op["op"] == "import":
            from ai_pc.apps import stats
            data = stats.sheet(op["file"])
            table = ident(Path(op["file"]).stem)
            cols = {ident(k): (k, infer([None if v is None else str(v) for v in vals])) for k, vals in data.items()}
            db = "imports"
            srv.psql(f"CREATE DATABASE {db}")
            ddl = f"DROP TABLE IF EXISTS {table}; CREATE TABLE {table} (id serial PRIMARY KEY, " + ", ".join(f"{c} {t}" for c, (_, t) in cols.items()) + ");"
            n = len(next(iter(data.values()), []))
            values = ",\n".join("(" + ", ".join(sql_text(None if data[k][i] is None else str(data[k][i]).replace(",", "") if t in ("bigint", "numeric")
                                                           else data[k][i]) for c, (k, t) in cols.items()) + ")" for i in range(n))
            script = out / f"import_{table}.sql"
            script.write_text(ddl + "\n" + (f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values};\n" if n else ""), encoding="utf-8")
            ok, err = srv.psql(db=db, file=script)
            okc, cnt = srv.psql(f"SELECT count(*) FROM {table}", db=db, csv_out=True)
            got = int(rows(cnt)[1][0]) if okc and len(rows(cnt)) > 1 else -1
            okt, types = srv.psql(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position",
                                  db=db, csv_out=True)
            srv.dump(db, out / f"{db}_backup.sql")
            kinds = ", ".join(f"{r[0]} {r[1]}" for r in rows(types)[1:])
            return (f"PostgreSQL table {table} made from {Path(op['file']).name} ({kinds}); backup {db}_backup.sql. " +
                    (f"Checked: all {n} rows are in it (the database counts {got})." if ok and got == n else f"NOT right: {got} of {n} rows. {err.strip()[-300:]}"))
        db = "shop"
        srv.psql(f"DROP DATABASE IF EXISTS {db}")
        srv.psql(f"CREATE DATABASE {db}")
        schema = out / "shop_schema.sql"
        schema.write_text(SHOP.strip() + "\n", encoding="utf-8")
        ok_s, err_s = srv.psql(db=db, file=schema)
        data = ["INSERT INTO customers (name, phone, city) VALUES " + ", ".join(f"({sql_text(n)}, {sql_text(p)}, {sql_text(c)})" for n, p, c in SAMPLE_CUSTOMERS) + ";",
                "INSERT INTO products (name, price, stock) VALUES " + ", ".join(f"({sql_text(n)}, {p}, {s})" for n, p, s in SAMPLE_PRODUCTS) + ";"]
        for k, (cust, status, items) in enumerate(SAMPLE_ORDERS, 1):
            data.append(f"INSERT INTO orders (customer_id, status) VALUES ({cust}, '{status}');")
            data += [f"INSERT INTO order_items (order_id, product_id, quantity, price) VALUES ({k}, {pid}, {q}, {SAMPLE_PRODUCTS[pid - 1][1]});" for pid, q in items]
        sample = out / "shop_sample_data.sql"
        sample.write_text("\n".join(data) + "\n", encoding="utf-8")
        ok_d, err_d = srv.psql(db=db, file=sample)
        ok_t, tabs = srv.psql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1", db=db, csv_out=True)
        ok_f, fks = srv.psql("SELECT count(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY'", db=db, csv_out=True)
        bad_fk, _ = srv.psql("INSERT INTO orders (customer_id) VALUES (999)", db=db)
        bad_price, _ = srv.psql("INSERT INTO products (name, price) VALUES ('Broken', -5)", db=db)
        ok_r, rep = srv.psql(REPORT, db=db, csv_out=True)
        (out / "shop_report.csv").write_text(rep, encoding="utf-8")
        srv.dump(db, out / "shop_backup.sql")
        want = {}
        for cust, status, items in SAMPLE_ORDERS:
            if status != "cancelled":
                want[SAMPLE_CUSTOMERS[cust - 1][0]] = want.get(SAMPLE_CUSTOMERS[cust - 1][0], 0) + sum(q * SAMPLE_PRODUCTS[p - 1][1] for p, q in items)
        got = {r[0]: float(r[2]) for r in rows(rep)[1:]}
        names = [r[0] for r in rows(tabs)[1:]]
        checks = [("the four tables were made with their keys", ok_s and ok_d and names == ["customers", "order_items", "orders", "products"]
                   and int(rows(fks)[1][0]) == 3),
                  ("the database refuses an order for a customer that does not exist (foreign key)", not bad_fk),
                  ("the database refuses a negative price (check)", not bad_price),
                  ("the sales report's totals equal the same sums done in Python (" + ", ".join(f"{k} Rs {v:,.0f}" for k, v in want.items()) + ")",
                   ok_r and got == {k: float(v) for k, v in want.items()}),
                  ("a pg_dump backup was made", (out / "shop_backup.sql").exists() and "CREATE TABLE public.orders" in (out / "shop_backup.sql").read_text(encoding="utf-8"))]
        bad = [w for w, good in checks if not good]
        return (f"PostgreSQL 18 database 'shop' (customers, products, orders, order_items) on a local server: schema {schema.name}, sample data, report "
                f"shop_report.csv, backup shop_backup.sql (restore with psql -f). " +
                ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + (err_s or err_d)[-300:]))
    finally:
        srv.close()

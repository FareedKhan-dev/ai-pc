"""MySQL 9.7 LTS (Oracle's MSI unpacked into tools/mysql; hash matched Scoop's manifest, MSI and programs signed by Oracle):
a real database server run here only on 127.0.0.1 (no X Protocol port, no binary log), its data in tools/mysql/data, started
for the job on the hidden desktop and shut down after; no option file is read (--no-defaults), so nothing outside the
project is used. A shop database from words (customers, products, orders, order items with keys, checks and an ENUM
status), sample rows, a sales report and a mysqldump backup; a CSV/Excel sheet imported as a table (types worked out); or
a .sql file run. Checked by the server itself: the tables and foreign keys are there, wrong rows are refused, the report's
sums equal the same sums done in Python. MySQL Workbench, DBeaver and HeidiSQL open the same scripts and backups.

  'mysql database for a shop with products, customers and orders'   'mysql import sales.xlsx'   'mysql run report.sql'
"""

import os
import re
import socket
import time
from pathlib import Path

from ai_pc.apps.postgres import REPORT, SAMPLE_CUSTOMERS, SAMPLE_ORDERS, SAMPLE_PRODUCTS, ident, infer
from ai_pc.core.config import ROOT

NAME, LABEL = "mysql", "MySQL: a real local database server: schemas from words, sheet imports, .sql runs, backups"
EXAMPLES = ["mysql database for a shop with products, customers and orders", "mysql import sales.xlsx", "mysql run report.sql"]
HOME = ROOT / "tools" / "mysql"
DATA = HOME / "data"

SHOP = """
CREATE TABLE customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  phone VARCHAR(20),
  city VARCHAR(60)
);
CREATE TABLE products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  price DECIMAL(12,2) NOT NULL CHECK (price >= 0),
  stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0)
);
CREATE TABLE orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status ENUM('new', 'paid', 'shipped', 'cancelled') NOT NULL DEFAULT 'new',
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);
CREATE TABLE order_items (
  order_id INT NOT NULL,
  product_id INT NOT NULL,
  quantity INT NOT NULL CHECK (quantity > 0),
  price DECIMAL(12,2) NOT NULL CHECK (price >= 0),
  PRIMARY KEY (order_id, product_id),
  FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
"""


def bin_dir():
    b = HOME / "bin"
    return b if (b / "mysqld.exe").exists() else None


def home():
    h = (HOME / "home").resolve()
    for d in (h, h / "tmp", h / "files"):
        d.mkdir(parents=True, exist_ok=True)
    return h


def env():
    h = home()
    return dict(os.environ, TMP=str(h / "tmp"), TEMP=str(h / "tmp"), MYSQL_HOME=str(h))


def sql_text(v):
    return "NULL" if v is None or v == "" else "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def tsv_rows(text):
    """mysql --batch output as rows (tab-separated, its escapes undone)."""
    un = {"\\t": "\t", "\\n": "\n", "\\\\": "\\", "\\0": "\0"}
    return (
        [[re.sub(r"\\[tn0\\]", lambda m: un[m.group(0)], c) for c in ln.split("\t")] for ln in text.strip("\r\n").splitlines()]
        if text.strip()
        else []
    )


class Server:
    """A local MySQL started for one job on 127.0.0.1 (a free port), shut down by close()."""

    def __init__(self):
        from ai_pc.core import hidden_desktop

        b = bin_dir()
        self.b = b
        h = home()
        common = ["--no-defaults", f"--basedir={HOME.resolve()}", f"--datadir={DATA.resolve()}", "--console", "--innodb-redo-log-capacity=8M"]
        if not (DATA / "mysql.ibd").exists():
            if DATA.exists() and not any(DATA.iterdir()):
                DATA.rmdir()
            rc, o, e, _ = hidden_desktop.run([str(b / "mysqld.exe"), *common, "--initialize-insecure"], timeout=600, env=env())
            if rc != 0 or not (DATA / "mysql.ibd").exists():
                raise RuntimeError(f"mysqld --initialize failed: {(e or o)[-400:]}")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.proc = hidden_desktop.start(
            [
                str(b / "mysqld.exe"),
                *common,
                f"--port={self.port}",
                "--bind-address=127.0.0.1",
                "--mysqlx=OFF",
                "--skip-log-bin",
                "--performance-schema=OFF",
                f"--tmpdir={h / 'tmp'}",
                f"--secure-file-priv={h / 'files'}",
            ],
            env=env(),
        )
        end = time.monotonic() + 90
        while time.monotonic() < end:
            ok, _ = self.sql("SELECT 1")
            if ok:
                return
            if not self.proc.alive():
                break
            time.sleep(0.5)
        _, out, err = self.proc.stop()
        raise RuntimeError(f"MySQL did not start: {(err or out)[-400:]}")

    def client(self):
        return ["--no-defaults", "-h", "127.0.0.1", "-P", str(self.port), "-u", "root"]

    def sql(self, text=None, db=None, file=None):
        """(ok, output or the error) for SQL text or a .sql file. A file is given on the client's input, where its own commands
        (source, system) stay off as MySQL 9 has them by default: a .sql file can only send SQL to the server."""
        from ai_pc.core import hidden_desktop

        args = [str(self.b / "mysql.exe"), *self.client(), "--batch", "--default-character-set=utf8mb4"]
        if db:
            args += ["-D", db]
        if not file:
            args += ["-e", text]
        rc, o, e, _ = hidden_desktop.run(args, timeout=300, env=env(), stdin=str(Path(file).resolve()) if file else None)
        return rc == 0, (o if rc == 0 else (e or o))

    def dump(self, db, dest):
        from ai_pc.core import hidden_desktop

        rc, o, e, _ = hidden_desktop.run(
            [str(self.b / "mysqldump.exe"), *self.client(), "--single-transaction", "--routines", f"--result-file={dest}", "--databases", db],
            timeout=300,
            env=env(),
        )
        return rc == 0

    def close(self):
        from ai_pc.core import hidden_desktop

        hidden_desktop.run([str(self.b / "mysqladmin.exe"), *self.client(), "shutdown"], timeout=120, env=env())
        self.proc.wait(60)
        self.proc.stop()


def column_type(kind, values):
    vals = [str(v) for v in values if v not in (None, "")]
    if kind == "bigint":
        return "BIGINT"
    if kind == "numeric":
        scale = min(6, max((len(v.split(".")[1]) for v in vals if "." in v), default=2))
        return f"DECIMAL(20,{scale})"
    if kind == "timestamp":
        return "DATETIME"
    return "VARCHAR(255)" if max((len(v) for v in vals), default=0) <= 255 else "TEXT"


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bmy\s?sql\b|\bmysql workbench\b", c):
        return None
    f = find_file(text, ctx, {".sql"})
    if f:
        return {"op": "sql", "file": f}
    f = find_file(text, ctx, {".csv", ".xlsx"})
    if f and re.search(r"\bimport\b|\bload\b|\btable\b|\bfrom\b", c):
        return {"op": "import", "file": f}
    if re.search(r"\bdatabase\b|\bschema\b|\bdb\b", c):
        return {"op": "shop"}
    return None


def run(op, ctx):
    if not bin_dir():
        return "MySQL is not in tools/mysql."
    out = (Path(ctx["out"]) / "mysql").resolve()
    out.mkdir(parents=True, exist_ok=True)
    srv = Server()
    try:
        if op["op"] == "sql":
            src = Path(op["file"])
            srv.sql("DROP DATABASE IF EXISTS work; CREATE DATABASE work")
            ok, res = srv.sql(db="work", file=src)
            rows = tsv_rows(res) if ok else []
            import csv

            with (out / (src.stem + "_result.csv")).open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows(rows)
            return f"MySQL ran {src.name}: " + (
                f"done; result in {src.stem}_result.csv: " + " | ".join(", ".join(r) for r in rows[:4]) if ok else "FAILED: " + res.strip()[-400:]
            )
        if op["op"] == "import":
            from ai_pc.apps import stats

            data = stats.sheet(op["file"])
            table = ident(Path(op["file"]).stem)
            cols = {}
            for k, vals in data.items():
                kind = infer([None if v is None else str(v) for v in vals])
                cols[ident(k)] = (
                    k,
                    kind,
                    column_type(kind, [None if v is None else str(v).replace(",", "") if kind in ("bigint", "numeric") else v for v in vals]),
                )
            n = len(next(iter(data.values()), []))

            def value(k, kind, i):
                v = data[k][i]
                return sql_text(None if v is None else str(v).replace(",", "") if kind in ("bigint", "numeric") else v)

            ddl = (
                f"CREATE DATABASE IF NOT EXISTS imports;\nUSE imports;\nDROP TABLE IF EXISTS `{table}`;\nCREATE TABLE `{table}` (id INT AUTO_INCREMENT PRIMARY KEY, "
                + ", ".join(f"`{c}` {t}" for c, (_, _, t) in cols.items())
                + ");"
            )
            values = ",\n".join("(" + ", ".join(value(k, kind, i) for k, kind, _ in cols.values()) + ")" for i in range(n))
            script = out / f"import_{table}.sql"
            script.write_text(
                ddl + "\n" + (f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in cols)}) VALUES\n{values};\n" if n else ""), encoding="utf-8"
            )
            ok, err = srv.sql(file=script)
            okc, cnt = srv.sql(f"SELECT count(*) FROM `{table}`", db="imports")
            got = int(tsv_rows(cnt)[1][0]) if okc and len(tsv_rows(cnt)) > 1 else -1
            okt, types = srv.sql(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'imports' "
                f"AND table_name = '{table}' ORDER BY ordinal_position"
            )
            srv.dump("imports", out / "imports_backup.sql")
            kinds = ", ".join(f"{r[0]} {r[1]}" for r in tsv_rows(types)[1:])
            return f"MySQL table {table} made from {Path(op['file']).name} ({kinds}); script {script.name}, backup imports_backup.sql. " + (
                f"Checked: all {n} rows are in it (the database counts {got})."
                if ok and got == n
                else f"NOT right: {got} of {n} rows. {err.strip()[-300:]}"
            )
        srv.sql("DROP DATABASE IF EXISTS shop; CREATE DATABASE shop")
        schema = out / "shop_schema.sql"
        schema.write_text(SHOP.strip() + "\n", encoding="utf-8")
        ok_s, err_s = srv.sql(db="shop", file=schema)
        data = [
            "INSERT INTO customers (name, phone, city) VALUES "
            + ", ".join(f"({sql_text(n)}, {sql_text(p)}, {sql_text(c)})" for n, p, c in SAMPLE_CUSTOMERS)
            + ";",
            "INSERT INTO products (name, price, stock) VALUES " + ", ".join(f"({sql_text(n)}, {p}, {s})" for n, p, s in SAMPLE_PRODUCTS) + ";",
        ]
        for k, (cust, status, items) in enumerate(SAMPLE_ORDERS, 1):
            data.append(f"INSERT INTO orders (customer_id, status) VALUES ({cust}, '{status}');")
            data += [
                f"INSERT INTO order_items (order_id, product_id, quantity, price) VALUES ({k}, {pid}, {q}, {SAMPLE_PRODUCTS[pid - 1][1]});"
                for pid, q in items
            ]
        sample = out / "shop_sample_data.sql"
        sample.write_text("\n".join(data) + "\n", encoding="utf-8")
        ok_d, err_d = srv.sql(db="shop", file=sample)
        ok_t, tabs = srv.sql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'shop' ORDER BY 1")
        ok_f, fks = srv.sql(
            "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_schema = 'shop' AND constraint_type = 'FOREIGN KEY'"
        )
        bad_fk, why_fk = srv.sql("INSERT INTO orders (customer_id) VALUES (999)", db="shop")
        bad_price, why_price = srv.sql("INSERT INTO products (name, price) VALUES ('Broken', -5)", db="shop")
        bad_status, why_status = srv.sql("INSERT INTO orders (customer_id, status) VALUES (1, 'lost')", db="shop")
        ok_r, rep = srv.sql(REPORT, db="shop")
        rep_rows = tsv_rows(rep) if ok_r else []
        import csv

        with (out / "shop_report.csv").open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rep_rows)
        srv.dump("shop", out / "shop_backup.sql")
        want = {}
        for cust, status, items in SAMPLE_ORDERS:
            if status != "cancelled":
                name = SAMPLE_CUSTOMERS[cust - 1][0]
                want[name] = want.get(name, 0) + sum(q * SAMPLE_PRODUCTS[p - 1][1] for p, q in items)
        got = {r[0]: float(r[2]) for r in rep_rows[1:]}
        names = [r[0] for r in tsv_rows(tabs)[1:]]
        fk_count = int(tsv_rows(fks)[1][0]) if ok_f and len(tsv_rows(fks)) > 1 else -1
        backup = out / "shop_backup.sql"
        checks = [
            (
                "the four tables were made with their keys",
                ok_s and ok_d and names == ["customers", "order_items", "orders", "products"] and fk_count == 3,
            ),
            ("the database refuses an order for a customer that does not exist (foreign key)", not bad_fk and "foreign key" in why_fk.lower()),
            ("the database refuses a negative price (check)", not bad_price and "check constraint" in why_price.lower()),
            ("the database refuses an order status that is not one of new/paid/shipped/cancelled", not bad_status),
            (
                "the sales report's totals equal the same sums done in Python (" + ", ".join(f"{k} Rs {v:,.0f}" for k, v in want.items()) + ")",
                ok_r and got == {k: float(v) for k, v in want.items()},
            ),
            ("a mysqldump backup was made", backup.exists() and "CREATE TABLE `orders`" in backup.read_text(encoding="utf-8")),
        ]
        bad = [w for w, good in checks if not good]
        return (
            f"MySQL 9.7 database 'shop' (customers, products, orders, order_items) on a local server: schema {schema.name}, sample data {sample.name}, "
            "report shop_report.csv, backup shop_backup.sql (restore with mysql or MySQL Workbench's Data Import). "
            + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + (err_s or err_d)[-300:])
        )
    finally:
        srv.close()

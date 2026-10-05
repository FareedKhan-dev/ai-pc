"""MongoDB Community Server 9.0 (tools/mongodb: fastdl.mongodb.org's zip, SHA-256 equal to MongoDB's downloads list, mongod.exe
signed by MongoDB, Inc.; debug symbols left out): a real NoSQL server run here only on 127.0.0.1, its data in
tools/mongodb/data, started for the job on the hidden desktop and shut down after; Python talks to it with PyMongo
(PyPI SHA-256 checked). A shop database from words (customers, products, orders with their items inside, MongoDB-style),
with the server's own rules: a JSON-schema validator (a price cannot be negative, an order status must be new, paid,
shipped or cancelled) and a unique product name; sample documents, a sales report by aggregation, and a JSON backup.
Or a CSV/Excel/JSON file imported as a collection with numbers and dates typed. Checked by the server itself: wrong
documents are refused, the report's sums equal the same sums done in Python, the backup reads back whole. MongoDB
Compass opens the same server while it runs.

  'mongodb database for a shop with products, customers and orders'   'mongodb import sales.csv'
"""
import json
import re
import socket
import time
from datetime import datetime
from pathlib import Path

from ai_pc.apps.postgres import SAMPLE_CUSTOMERS, SAMPLE_ORDERS, SAMPLE_PRODUCTS, ident
from ai_pc.core.config import ROOT

NAME, LABEL = "mongodb", "MongoDB: a real local NoSQL server: a validated shop database, imports, aggregation reports, JSON backups; checked by the server"
EXAMPLES = ["mongodb database for a shop with products, customers and orders", "mongodb import sales.csv"]
HOME = ROOT / "tools" / "mongodb"
DATA = HOME / "data"
MONGOD = HOME / "bin" / "mongod.exe"

VALIDATORS = {
    "customers": {"$jsonSchema": {"bsonType": "object", "required": ["_id", "name"],
                                  "properties": {"name": {"bsonType": "string", "minLength": 1}, "phone": {"bsonType": "string"}, "city": {"bsonType": "string"}}}},
    "products": {"$jsonSchema": {"bsonType": "object", "required": ["_id", "name", "price", "stock"],
                                 "properties": {"name": {"bsonType": "string", "minLength": 1}, "price": {"bsonType": ["int", "long", "double"], "minimum": 0},
                                                "stock": {"bsonType": ["int", "long"], "minimum": 0}}}},
    "orders": {"$jsonSchema": {"bsonType": "object", "required": ["customer_id", "status", "items"],
                               "properties": {"status": {"enum": ["new", "paid", "shipped", "cancelled"]},
                                              "items": {"bsonType": "array", "minItems": 1,
                                                        "items": {"bsonType": "object", "required": ["product_id", "quantity", "price"],
                                                                  "properties": {"quantity": {"bsonType": ["int", "long"], "minimum": 1},
                                                                                 "price": {"bsonType": ["int", "long", "double"], "minimum": 0}}}}}}}}
REPORT = [{"$match": {"status": {"$ne": "cancelled"}}}, {"$unwind": "$items"},
          {"$group": {"_id": "$customer_id", "orders": {"$addToSet": "$_id"}, "total": {"$sum": {"$multiply": ["$items.quantity", "$items.price"]}}}},
          {"$lookup": {"from": "customers", "localField": "_id", "foreignField": "_id", "as": "c"}},
          {"$project": {"_id": 0, "name": {"$first": "$c.name"}, "orders": {"$size": "$orders"}, "total": 1}}, {"$sort": {"total": -1}}]


class Server:
    """A local mongod started for one job on 127.0.0.1 (a free port), shut down by close()."""

    def __init__(self):
        import pymongo

        from ai_pc.core import hidden_desktop
        DATA.mkdir(parents=True, exist_ok=True)
        (HOME / "home").mkdir(parents=True, exist_ok=True)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.proc = hidden_desktop.start([str(MONGOD), "--dbpath", str(DATA.resolve()), "--port", str(self.port), "--bind_ip", "127.0.0.1",
                                          "--logpath", str((HOME / "home" / "mongod.log").resolve()), "--quiet", "--wiredTigerCacheSizeGB", "0.25",
                                          "--setParameter", "diagnosticDataCollectionEnabled=false"])
        self.client = pymongo.MongoClient(f"mongodb://127.0.0.1:{self.port}/", serverSelectionTimeoutMS=1500, directConnection=True)
        end = time.monotonic() + 60
        while time.monotonic() < end:
            try:
                self.client.admin.command("ping")
                return
            except pymongo.errors.PyMongoError:
                if not self.proc.alive():
                    break
                time.sleep(0.5)
        self.proc.stop()
        raise RuntimeError("mongod did not start: " + ((HOME / "home" / "mongod.log").read_text(encoding="utf-8", errors="replace")[-400:]
                                                       if (HOME / "home" / "mongod.log").exists() else ""))

    def close(self):
        import pymongo
        try:
            self.client.admin.command("shutdown")
        except pymongo.errors.PyMongoError:
            pass  # the server closes the connection as it shuts down
        self.client.close()
        self.proc.wait(30)
        self.proc.stop()


def typed(v):
    """A sheet cell as MongoDB wants it: numbers as numbers, dates as dates, the rest as text."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, datetime)):
        return v
    s = str(v).strip()
    if re.fullmatch(r"-?\d+", s.replace(",", "")):
        return int(s.replace(",", ""))
    if re.fullmatch(r"-?\d+\.\d+", s.replace(",", "")):
        return float(s.replace(",", ""))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?", s):
        return datetime.fromisoformat(s)
    return s


def backup(db, dest):
    from bson import json_util
    data = {name: list(db[name].find()) for name in sorted(db.list_collection_names())}
    dest.write_text(json_util.dumps(data, indent=1, json_options=json_util.CANONICAL_JSON_OPTIONS), encoding="utf-8")
    back = json_util.loads(dest.read_text(encoding="utf-8"))
    return all(len(back.get(n, [])) == len(docs) for n, docs in data.items()), sum(len(d) for d in data.values())


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bmongo(?:db)?\b|\bcompass\b", c):
        return None
    f = find_file(text, ctx, {".csv", ".xlsx", ".json", ".jsonl"})
    if f and re.search(r"\bimport\b|\bload\b|\bcollection\b|\bfrom\b", c):
        return {"op": "import", "file": f}
    if re.search(r"\bdatabase\b|\bdb\b|\bshop\b|\bstore\b", c):
        return {"op": "shop"}
    return None


def run(op, ctx):
    if not MONGOD.exists():
        return "MongoDB is not in tools/mongodb."
    import pymongo
    out = (Path(ctx["out"]) / "mongodb").resolve()
    out.mkdir(parents=True, exist_ok=True)
    srv = Server()
    try:
        if op["op"] == "import":
            src = Path(op["file"])
            if src.suffix.lower() in (".json", ".jsonl"):
                raw = src.read_text(encoding="utf-8")
                docs = [json.loads(ln) for ln in raw.splitlines() if ln.strip()] if src.suffix.lower() == ".jsonl" else json.loads(raw)
                docs = docs if isinstance(docs, list) else [docs]
            else:
                from ai_pc.apps import stats
                cols = stats.sheet(src)
                n = len(next(iter(cols.values()), []))
                docs = [{ident(k): typed(v[i]) for k, v in cols.items() if typed(v[i]) is not None} for i in range(n)]
            db = srv.client["imports"]
            name = ident(src.stem)
            db.drop_collection(name)
            if docs:
                db[name].insert_many(docs)
            count = db[name].count_documents({})
            kinds = list(db[name].aggregate([{"$limit": 1}, {"$project": {"_id": 0, "t": {"$objectToArray": "$$ROOT"}}}, {"$unwind": "$t"},
                                             {"$project": {"k": "$t.k", "type": {"$type": "$t.v"}}}]))
            ok_b, saved = backup(db, out / "imports_backup.json")
            return (f"MongoDB collection imports.{name} made from {src.name} (" + ", ".join(f"{k['k']} {k['type']}" for k in kinds) +
                    "); backup imports_backup.json. " + (f"Checked: all {len(docs)} documents are in it (the server counts {count}); the backup reads back whole."
                                                          if count == len(docs) and ok_b else f"NOT right: {count} of {len(docs)} documents."))
        db = srv.client["shop"]
        for name in ("orders", "products", "customers"):
            db.drop_collection(name)
        for name, rule in VALIDATORS.items():
            db.create_collection(name, validator=rule, validationLevel="strict", validationAction="error")
        db.products.create_index("name", unique=True)
        db.orders.create_index("customer_id")
        db.customers.insert_many([{"_id": i, "name": n, "phone": p, "city": c} for i, (n, p, c) in enumerate(SAMPLE_CUSTOMERS, 1)])
        db.products.insert_many([{"_id": i, "name": n, "price": p, "stock": s} for i, (n, p, s) in enumerate(SAMPLE_PRODUCTS, 1)])
        db.orders.insert_many([{"_id": k, "customer_id": cust, "status": status, "created_at": datetime.now(),
                                "items": [{"product_id": pid, "quantity": q, "price": SAMPLE_PRODUCTS[pid - 1][1]} for pid, q in items]}
                               for k, (cust, status, items) in enumerate(SAMPLE_ORDERS, 1)])

        def refused(fn):
            try:
                fn()
                return None
            except pymongo.errors.WriteError as e:
                return e.code
            except pymongo.errors.DuplicateKeyError as e:
                return e.code
        neg = refused(lambda: db.products.insert_one({"_id": 99, "name": "Broken", "price": -5, "stock": 1}))
        dup = refused(lambda: db.products.insert_one({"_id": 98, "name": "Kettle", "price": 100, "stock": 1}))
        bad_status = refused(lambda: db.orders.insert_one({"customer_id": 1, "status": "lost", "items": [{"product_id": 1, "quantity": 1, "price": 10}]}))
        rep = list(db.orders.aggregate(REPORT))
        (out / "shop_report.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
        want = {}
        for cust, status, items in SAMPLE_ORDERS:
            if status != "cancelled":
                n = SAMPLE_CUSTOMERS[cust - 1][0]
                want[n] = want.get(n, 0) + sum(q * SAMPLE_PRODUCTS[p - 1][1] for p, q in items)
        got = {r["name"]: r["total"] for r in rep}
        ok_b, saved = backup(db, out / "shop_backup.json")
        names = sorted(db.list_collection_names())
        checks = [("the three collections were made with their validators and a unique product name", names == ["customers", "orders", "products"]
                   and all(db.command("listCollections", filter={"name": n})["cursor"]["firstBatch"][0]["options"].get("validator") for n in names)
                   and any(ix.get("unique") for ix in db.products.list_indexes())),
                  ("the server refuses a negative price (its validator)", neg == 121), ("the server refuses a second product with the same name", dup == 11000),
                  ("the server refuses an order status that is not new/paid/shipped/cancelled", bad_status == 121),
                  ("the sales report (an aggregation) equals the same sums done in Python (" + ", ".join(f"{k} Rs {v:,}" for k, v in want.items()) + ")", got == want),
                  (f"a JSON backup of all {saved} documents was made and reads back whole", ok_b)]
        bad = [w for w, good in checks if not good]
        return ("MongoDB 9.0 database 'shop' (customers, products, orders with their items inside) on a local server: report shop_report.json, "
                "backup shop_backup.json (MongoDB Extended JSON). " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else
                                                                        "NOT right: " + "; ".join(bad) + "."))
    finally:
        srv.close()

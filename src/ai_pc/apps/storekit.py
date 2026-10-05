"""What the online-store programs share (Shopify, WooCommerce, Daraz): the requests read the same way for each, and every
change to the shop (a new product, a price or stock change, an order shipped) is shown first and done after a yes,
then read back from the shop. A store's client has:

  products() -> [{"sku", "title", "price", "stock"}]     find(sku) -> the product or None
  add(title, price, sku, stock, image=None) -> id        update(sku, price=None, stock=None)
  orders() -> [{"id", "number", "total", "created"}]     ship(number, company=None, tracking=None) -> what the shop said
"""

import re

from ai_pc.accounts.money import MoneyError, to_paisa

AMT = r"(?:rs\.?\s*)?\d[\d,]*(?:\.\d+)?(?:\s*(?:lakh|k))?"


def money(s):
    try:
        return f"{to_paisa(s) / 100:.2f}"
    except MoneyError:
        return None


def parse_store(text, word):
    c = text.lower().strip(" ?.")
    if not re.search(word, c):
        return None
    if (
        re.search(r"\b(?:products?|items?|listings?|catalog(?:ue)?)\b", c)
        and re.search(r"\b(?:list|show|my|what|which|all)\b|^\S+\s+products?$|products? on\b", c)
        and not re.search(r"^\s*add\b", c)
    ):
        return {"op": "products"}
    if re.search(r"\b(?:new|pending|open|unfulfilled|unshipped)?\s*orders?\b", c) and not re.search(r"\bship|\bmark\b|\bfulfil", c):
        return {"op": "orders"}
    m = re.match(r"^\s*add\s+(.+?)\s+(?:to|on)\s+(?:my\s+)?\S+(?:\s+store)?\s+(?:at|for)\s+(" + AMT + r")(.*)$", text, re.I)
    if m:
        rest = m.group(3)
        sku = re.search(r"\bsku\s*:?\s*([\w.-]+)", rest, re.I)
        qty = re.search(r"\b(\d+)\s+(?:in stock|pieces|pcs|units)\b|\bstock\s+(\d+)\b", rest, re.I)
        img = re.search(r"\b(?:image|picture|photo)\s+(https?://\S+)", rest, re.I)
        cat = re.search(r"\bcategory\s+(\d+)\b", rest, re.I)
        return {
            "op": "add",
            "title": m.group(1).strip(),
            "price": money(m.group(2)),
            "sku": sku.group(1) if sku else re.sub(r"\W+", "-", m.group(1)).strip("-").upper()[:30],
            "stock": int(qty.group(1) or qty.group(2)) if qty else 0,
            "image": img.group(1) if img else None,
            "category": cat.group(1) if cat else None,
        }
    m = re.search(r"\b(?:set|change|make)\s+(?:the\s+)?(price|stock|quantity)\s+of\s+([\w.-]+)\s+(?:on\s+\S+\s+)?to\s+(" + AMT + r")", text, re.I)
    if m:
        k = m.group(1).lower()
        return {
            "op": "update",
            "sku": m.group(2),
            "price": money(m.group(3)) if k == "price" else None,
            "stock": int(to_paisa(m.group(3)) // 100) if k != "price" else None,
        }
    m = re.search(
        r"\b(?:mark|ship|fulfil+)\s+(?:order\s+)?#?([\w-]+)\s+(?:as\s+)?(?:shipped|sent|fulfilled)?(?:.*?\b(?:with|via|by)\s+([A-Za-z][\w&.-]*)\s*(?:tracking\s*)?#?\s*([\w-]{5,}))?",
        text,
        re.I,
    )
    if m and re.search(r"\bship|\bfulfil", c):
        return {"op": "ship", "number": m.group(1).lstrip("#"), "company": m.group(2), "tracking": m.group(3)}
    return None


def preview(op, label):
    if op["op"] == "add":
        return (
            f"Ready to add '{op['title']}' (SKU {op['sku']}) to {label} at Rs {float(op['price']):,.2f} with {op['stock']} in stock"
            + (" and its picture" if op.get("image") else "")
            + "."
        )
    if op["op"] == "update":
        what = ", ".join(
            x
            for x in (f"price Rs {float(op['price']):,.2f}" if op.get("price") else "", f"stock {op['stock']}" if op.get("stock") is not None else "")
            if x
        )
        return f"Ready to set {what} for SKU {op['sku']} on {label}."
    return (
        f"Ready to mark order {op['number']} shipped on {label}"
        + (f" with {op['company']} tracking {op['tracking']}" if op.get("tracking") else "")
        + " (the customer is told)."
    )


def run(op, client, label):
    k = op["op"]
    if k == "products":
        ps = client.products()
        return (
            f"{len(ps)} products on {label}:\n"
            + "\n".join(f"- {p['sku'] or '-'}: {p['title']}, Rs {float(p['price'] or 0):,.2f}, {p['stock']} in stock" for p in ps[:30])
            if ps
            else f"No products on {label} yet."
        )
    if k == "orders":
        os_ = client.orders()
        return (
            f"{len(os_)} new orders on {label}:\n" + "\n".join(f"- {o['number']}: Rs {float(o['total']):,.2f}, {o['created'][:10]}" for o in os_[:30])
            if os_
            else f"No new orders on {label}."
        )
    if not op.get("confirmed"):
        return preview(op, label)
    if k == "add":
        if client.find(op["sku"]):
            return f"SKU {op['sku']} is already on {label}: say 'set price of {op['sku']} on ... to ...' instead."
        pid = client.add(
            op["title"], op["price"], op["sku"], op["stock"], op.get("image"), **({"category": op["category"]} if op.get("category") else {})
        )
        p = client.find(op["sku"])
        ok = p and abs(float(p["price"]) - float(op["price"])) < 0.005 and int(p["stock"] or 0) == op["stock"]
        return f"Added to {label} ({pid}): " + (
            f"read back: Rs {float(p['price']):,.2f}, {p['stock']} in stock." if ok else f"NOT as asked when read back: {p}"
        )
    if k == "update":
        if not client.find(op["sku"]):
            return f"No product with SKU {op['sku']} on {label}."
        client.update(op["sku"], op.get("price"), op.get("stock"))
        p = client.find(op["sku"])
        ok = (op.get("price") is None or abs(float(p["price"]) - float(op["price"])) < 0.005) and (
            op.get("stock") is None or int(p["stock"]) == op["stock"]
        )
        return f"SKU {op['sku']} on {label}: " + ("read back: " if ok else "NOT as asked: ") + f"Rs {float(p['price']):,.2f}, {p['stock']} in stock."
    said = client.ship(op["number"], op.get("company"), op.get("tracking"))
    return f"Order {op['number']} marked shipped on {label}: {said}."

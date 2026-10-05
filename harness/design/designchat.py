"""A conversation that designs: visiting cards, social posts, stories, YouTube thumbnails, flyers, posters,
certificates and invitations, one version per change, every version rendered (PNG, print PDF with bleed) and checked.

  c = DesignChat.start()
  c.say("make a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567, ahmed@khan.pk, khanelectronics.pk")
  c.say("classic style in green")  /  c.say("make the name bigger")  /  c.say("add a QR code")  /  c.say("change the phone to 0333-7654321")
  c.say("an instagram post for our summer sale 'Mega Summer Sale' 30% off 1-15 June, shop now")  /  c.say("make it a story")
  c.say("certificates of participation for Ali Raza, Sara Khan and Hamza Ali")  /  c.say("export the pdf for printing")  /  c.say("undo")
"""
import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path

from ..config import ROOT
from ..util import parse_json
from . import check as CK
from . import render as R
from .designparse import parse
from .kinds import DEFAULT_PALETTE, KINDS, PALETTES

CHATS = ROOT / "out" / "design" / "chats"
UNDO = re.compile(r"^\s*(?:undo|revert|go back|take (?:that|it) back)\b(?!.*\bv\d)", re.I)
REDO = re.compile(r"^\s*redo\b", re.I)
GOTO = re.compile(r"\b(?:go back to|back to|use|show me|switch to)\s+(?:version\s*|v)(\d+)\b", re.I)
HISTORY = re.compile(r"^\s*(?:history|versions)\b", re.I)
SPLIT = re.compile(r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bMrs\.)(?<!\bSt\.)(?<=[.!?;])\s+(?=[A-Z])|,?\s+(?:and then|then|also)\s+|,?\s+and\s+(?=(?:make|change|add|remove|use|put|export|save|give|turn|set|try)\b)", re.I)
DESIGN_SYSTEM = """You turn a person's request about a design into changes for a program. Reply with ONE JSON object: {"ops": [...]} or {"ask": "<short question>"}.
Ops:
 {"op": "new", "kind": "card|post|portrait|story|thumbnail|flyer|poster|certificate|invitation", "style": "...", "palette": "navy|emerald|maroon|charcoal|blue|green|black|purple|red|orange|teal|cream|white|pink|gold",
  "fields": {...}, "qr": true}
   card fields: name, title, company, phone, email, web, address, tagline
   post/portrait/story/flyer/poster fields: brand, headline (short, 2-5 words), sub, offer (e.g. "30% OFF"), dates, cta (e.g. "Shop now"), phone, web, address,
     items (flyer price list: [{"name", "price"}]); event flyers: headline, sub, date, time, address, body
   thumbnail fields: headline (3-6 punchy words), sub (a short tag)
   certificate fields: org, title ("Certificate of ..."), recipient, reason ("for ..."), date, signer1 ("Name, Role"), signer2
   invitation fields: heading, host, event, date, time, address, note, rsvp
 {"op": "set", "fields": {...}}  {"op": "drop", "fields": ["address"]}  {"op": "look", "style": "...", "palette": "...", "kind": "story"}
 {"op": "size", "role": "name|headline|offer|title|company|recipient|tagline", "by": 1.25}  {"op": "qr", "data": "url or true"}
 {"op": "batch", "names": ["..."]}  {"op": "export", "fmt": "pdf|png|both", "for": "print|whatsapp"}
Use only the person's own words and details; never invent phone numbers, emails, prices or names. Keep headlines short."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", " ", s or "").strip()[:40] or "design"


class DesignChat:
    def __init__(self, state, planner=None, log=print):
        self.state, self.planner, self.log = state, planner, log
        self.folder = Path(state["folder"])
        self.last_turn = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, log=print, files=None):
        cid = f"design_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        k = 2
        while folder.exists():
            folder = Path(chats_dir or CHATS) / f"{cid}_{k}"
            k += 1
        folder.mkdir(parents=True)
        c = cls({"id": folder.name, "folder": str(folder), "versions": [], "cur": -1, "redo": [], "turns": [], "exports": [],
                 "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in (files or [])}}, planner=planner, log=log)
        c.save()
        return c

    @classmethod
    def load(cls, cid, chats_dir=None, planner=None, log=print):
        return cls(json.loads((Path(chats_dir or CHATS) / cid / "chat.json").read_text(encoding="utf-8")), planner=planner, log=log)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def cur(self):
        return self.state["versions"][self.state["cur"]] if self.state["cur"] >= 0 else None

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "llm": False, "v_from": self.state["cur"]}
        self._turn = turn
        out = []
        m = GOTO.search(message)
        if m:
            turn["intents"].append("goto")
            out.append(self.goto(int(m.group(1))))
        elif UNDO.search(message):
            turn["intents"].append("undo")
            out.append(self.undo())
        elif REDO.search(message):
            turn["intents"].append("redo")
            out.append(self.redo())
        elif HISTORY.search(message):
            turn["intents"].append("history")
            out.append(self.history())
        else:
            ctx = {"kind": (self.cur() or {}).get("spec", {}).get("kind"), "files": self.state["files"]}
            ops = []
            r = parse(message, ctx)  # a whole request first: details spread over commas belong together
            if not (r["ops"] and r["ops"][0]["op"] in ("new", "batch")):
                ops, r = [], None
                for cl in [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")] or [message]:
                    r2 = parse(cl, ctx)
                    if not r2["ops"] and not r2.get("ask"):
                        r2 = self._llm(cl, message)
                    if r2.get("ask") and not r2["ops"]:
                        out.append(r2["ask"])
                        ops = []
                        break
                    ops += r2["ops"]
                    for o in r2["ops"]:
                        if o["op"] == "new":
                            ctx["kind"] = o["kind"]
            else:
                ops = r["ops"]
                new = ops[0]
                if new["op"] == "new" and self._thin(new) and self.planner is not None:  # the rules found the kind but few details: the model reads the rest
                    r2 = self._llm(message, message)
                    llm_new = next((o for o in r2["ops"] if o.get("op") == "new"), None)
                    if llm_new:
                        merged = dict(llm_new.get("fields") or {})
                        merged.update({k: v for k, v in new["fields"].items() if v})
                        new = dict(new, fields=merged, **{k: v for k, v in llm_new.items() if k in ("style", "palette") and k not in new})
                        ops = [new] + ops[1:]
            if ops:
                out.append(self._apply(ops, message))
        reply = "\n".join(x for x in out if x).strip() or "Tell me what to design, e.g. 'a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567'."
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), v_to=self.state["cur"])
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    @staticmethod
    def _thin(new):
        need = {"card": ("name",), "post": ("headline",), "portrait": ("headline",), "story": ("headline",), "thumbnail": ("headline",), "flyer": ("headline",),
                "poster": ("headline",), "certificate": ("recipient",), "invitation": ("event",)}[new["kind"]]
        return any(not new["fields"].get(k) for k in need)

    def _llm(self, clause, message):
        if self.planner is None:
            return {"ops": [], "ask": f"I could not read '{clause[:80]}'. Try e.g. 'a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567' "
                                      f"or 'make the name bigger'."}
        self._turn["llm"] = True
        v = self.cur()
        ctx = f"ON SCREEN: {json.dumps({k: v['spec'].get(k) for k in ('kind', 'style', 'palette', 'fields')}, ensure_ascii=False)}" if v else "ON SCREEN: nothing yet"
        try:
            r = self.planner._call("fast", [{"role": "system", "content": DESIGN_SYSTEM}, {"role": "user", "content": f"{ctx}\nMESSAGE: {message}\nREQUEST: {clause}"}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op") in ("new", "set", "drop", "look", "size", "qr", "batch", "export", "image", "logo")]
        for o in ops:
            if o["op"] == "new" and o.get("kind") not in KINDS:
                o["kind"] = "post"
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- doing
    def _apply(self, ops, said):
        v = self.cur()
        spec = json.loads(json.dumps(v["spec"])) if v else None
        lines, changed, exports, batch = [], [], [], None
        for op in ops:
            k = op["op"]
            self._turn["intents"].append(k)
            if k == "new":
                spec = {"kind": op["kind"], "style": op.get("style") if op.get("style") in KINDS[op["kind"]]["styles"] else KINDS[op["kind"]]["styles"][0],
                        "palette": op.get("palette") if op.get("palette") in PALETTES else DEFAULT_PALETTE[op["kind"]], "fields": dict(op.get("fields") or {}),
                        "qr": op.get("qr", False), "sizes": {}}
                for key in ("image", "logo", "gradient", "paper"):
                    if op.get(key):
                        spec[key] = self._file(op[key]) if key in ("image", "logo") else op[key]
                if spec.get("image") and spec["kind"] in ("post", "portrait", "story") and not op.get("style"):
                    spec["style"] = "photo"
                changed.append("new")
                continue
            if spec is None:
                lines.append("Start a design first, e.g. 'a visiting card for ...' or 'an instagram post for ...'.")
                continue
            if k == "set":
                spec["fields"].update({kk: vv for kk, vv in op["fields"].items() if vv})
                changed.append("details")
            elif k == "drop":
                for f in op["fields"]:
                    spec["fields"].pop(f, None)
                    if f == "web" and spec.get("qr") is True:
                        spec["qr"] = False
                changed.append("removed")
            elif k == "look":
                if op.get("kind") and op["kind"] in KINDS and op["kind"] != spec["kind"]:
                    spec["kind"] = op["kind"]
                    styles = KINDS[spec["kind"]]["styles"]
                    spec["style"] = spec["style"] if spec["style"] in styles else ("photo" if spec.get("image") and "photo" in styles else styles[0])
                    spec["sizes"] = {}
                if op.get("style"):
                    styles = KINDS[spec["kind"]]["styles"]
                    spec["style"] = styles[(styles.index(spec["style"]) + 1) % len(styles)] if op["style"] == "next" else (op["style"] if op["style"] in styles else spec["style"])
                    spec["sizes"] = {}
                if op.get("palette") in PALETTES:
                    spec["palette"] = op["palette"]
                    spec.pop("gradient", None)
                if op.get("gradient"):
                    spec["gradient"] = op["gradient"]
                if op.get("paper"):
                    spec["paper"] = op["paper"]
                changed.append("look")
            elif k == "size":
                fitted = (v or {}).get("fitted", {}).get(op["role"])
                if not fitted:
                    lines.append(f"There is no {op['role']} on this design.")
                    continue
                spec.setdefault("sizes", {})[op["role"]] = round(fitted * float(op["by"]), 2)
                changed.append("size")
            elif k == "qr":
                spec["qr"] = bool(op.get("data"))
                if isinstance(op.get("data"), str):
                    spec["fields"]["qr"] = op["data"]
                elif not op.get("data"):
                    spec["fields"].pop("qr", None)
                if spec["qr"] and not (spec["fields"].get("qr") or spec["fields"].get("web")):
                    lines.append("A QR code needs a link: say e.g. 'add a QR code for khanelectronics.pk'.")
                    spec["qr"] = False
                    continue
                changed.append("qr")
            elif k in ("image", "logo"):
                if op.get("path"):
                    spec[k] = self._file(op["path"])
                    if k == "image" and spec["kind"] in ("post", "portrait", "story") and spec["style"] == "headline":
                        spec["style"] = "photo"
                else:
                    spec.pop(k, None)
                    if k == "image" and spec["style"] in ("photo", "split"):
                        spec["style"] = "headline"
                spec.pop("_cutout", None)
                changed.append(k)
            elif k == "batch":
                batch = op
            elif k == "export":
                exports.append(op)
        if changed and spec is not None:
            missing = [p for p in (spec.get("image"), spec.get("logo")) if p and not Path(p).exists()]
            if missing:
                return f"I can't find {', '.join(Path(p).name for p in missing)}; give the full path (or start the chat with --with)."
            try:
                nv = self._build(spec, said)
            except Exception as e:  # noqa: BLE001
                return f"Couldn't make that: {type(e).__name__}: {e}"
            lines.append(self._words(nv, v))
        if batch:
            lines.append(self._batch(batch, said))
        for e in exports:
            lines.append(self.export(**{kk: vv for kk, vv in e.items() if kk != "op"}))
        return "\n".join(x for x in lines if x)

    def _file(self, p):
        q = Path(p)
        if q.is_file():
            return str(q.resolve())
        hit = self.state["files"].get(q.name.lower())
        return hit or str(q)

    def _build(self, spec, said):
        n = len(self.state["versions"])
        t0 = time.perf_counter()
        spec.pop("_cutout", None)
        spec.pop("_text_at", None)
        info = R.prepare(spec, self.folder)
        res = R.render(spec, self.folder, f"v{n}")
        faces = {p["name"]: R.faces_on_page(spec, info, p["measure"]) for p in res["pages"]}
        checks = CK.checks(spec, res, {k: x for k, x in faces.items() if x})
        fitted = {}
        for p in res["pages"]:
            for i in (p["measure"] or {}).get("items", []):
                if i.get("text_el") and i["role"] not in fitted:
                    fitted[i["role"]] = i.get("fitted") or i["size"]
        nv = {"v": n, "spec": spec, "files": {"png": [p["png"] for p in res["pages"]], "pdf": res["pdf"], "html": [p["html"] for p in res["pages"]]},
              "checks": checks, "fitted": fitted, "said": said, "parent": self.state["cur"], "when": _when(), "seconds": round(time.perf_counter() - t0, 1),
              "prepared": {k: x for k, x in info.items() if k != "faces"}}
        self.state["versions"].append(nv)
        self.state["cur"] = n
        self.state["redo"] = []
        return nv

    def _words(self, nv, before):
        spec, ck = nv["spec"], CK
        k = KINDS[spec["kind"]]
        bad = [c for c in nv["checks"] if not c["ok"] and c["level"] == "fail"]
        warn = [c for c in nv["checks"] if not c["ok"] and c["level"] == "warn"]
        text = f"checked {len(nv['checks']) - len(bad) - len(warn)}/{len(nv['checks'])}" + (f"; not right: {'; '.join(c['what'] for c in bad[:3])}" if bad else "") + \
            (f"; to look at: {'; '.join(c['what'] for c in warn[:2])}" if warn else "")
        from .kinds import size_of
        w, h, unit, bleed, _ = size_of(spec)
        size = f"{w:g} x {h:g} mm" + (f" + {bleed:g} mm bleed" if bleed else "") if unit == "mm" else f"{w} x {h} px"
        who = spec["fields"].get("name") or spec["fields"].get("headline") or spec["fields"].get("recipient") or spec["fields"].get("event") or ""
        extra = ""
        if nv.get("prepared", {}).get("cutout"):
            extra = f" The person was cut from the {nv['prepared']['cutout']} backdrop."
        if spec.get("_text_at") == "top":
            extra += " The words went to the top, clear of the faces."
        files = [Path(p).name for p in nv["files"]["png"]] + ([Path(nv["files"]["pdf"]).name] if nv["files"]["pdf"] else [])
        return (f"v{nv['v']}: {k['label']} ({spec['style']}, {spec.get('gradient') or spec['palette']}){' for ' + who if who else ''}, {size}"
                f"{', front and back' if len(nv['files']['png']) > 1 else ''}.{extra} Files: {', '.join(files)}. ({text})")

    # ---------------------------------------------------------------- certificates for many names
    def _batch(self, op, said):
        v = self.cur()
        if v is None or v["spec"]["kind"] != "certificate":
            return "Make the certificate first ('a certificate of achievement from Punjab Coding Academy for completing ...'), then the names."
        names = op.get("names") or self._names(op.get("file"))
        if not names:
            return f"No names found in {op.get('file')}."
        from .layouts import certificate
        spec = v["spec"]
        pages = []
        for nm in names:
            pages += certificate(spec, recipient=nm)
        stem = f"v{v['v']}_batch"
        both = R._join(pages)
        hp = self.folder / f"{stem}.html"
        hp.write_text(both, encoding="utf-8")
        from .. import headless
        dom = headless.dom(hp, wait_ms=3000)
        m = re.search(r'<script type="application/json" id="measure">(.*?)</script>', dom, re.S)
        meas = json.loads(m.group(1)) if m else {"items": []}
        pdf = self.folder / f"{stem}.pdf"
        headless.pdf(hp, pdf, wait_ms=3000)
        whos = [i for i in meas["items"] if i["role"] == "recipient"]
        bad = [i["text"] for i in whos if i.get("over")]
        shrunk = [i["text"] for i in whos if i.get("fitted") and i.get("base") and i["fitted"] < i["base"] - 0.5]
        from pypdf import PdfReader
        pages_n = len(PdfReader(str(pdf)).pages)
        chk = [{"ok": pages_n == len(names), "what": f"{pages_n} page(s) for {len(names)} name(s)", "level": "fail"},
               {"ok": len(whos) == len(names) and sorted(i["text"] for i in whos) == sorted(names), "what": "every name printed once, spelled as given", "level": "fail"},
               {"ok": not bad, "what": "every name fits its line" + (f" (not: {', '.join(bad[:3])})" if bad else ""), "level": "fail"}]
        self.state.setdefault("batches", []).append({"v": v["v"], "names": names, "pdf": str(pdf), "checks": chk})
        okn = sum(c["ok"] for c in chk)
        return (f"{len(names)} certificates in one PDF ({pdf.name}, {pages_n} pages)" + (f"; {len(shrunk)} long name(s) set smaller to fit" if shrunk else "") +
                f". (checked {okn}/{len(chk)}" + ("" if okn == len(chk) else f"; not right: {'; '.join(c['what'] for c in chk if not c['ok'])}") + ") Say 'export the pdf' to save it.")

    def _names(self, file):
        p = Path(self._file(file)) if file else None
        if not p or not p.exists():
            return []
        if p.suffix.lower() == ".xlsx":
            import openpyxl
            ws = openpyxl.load_workbook(p, read_only=True, data_only=True).active
            vals = [r[0] for r in ws.iter_rows(values_only=True) if r and r[0]]
        else:
            vals = [ln.split(",")[0] for ln in p.read_text(encoding="utf-8-sig").splitlines()]
        vals = [str(x).strip() for x in vals if str(x).strip()]
        if vals and vals[0].lower() in ("name", "names", "student", "participant", "full name"):
            vals = vals[1:]
        return vals

    # ---------------------------------------------------------------- saving
    def export(self, fmt="pdf", **kw):
        v = self.cur()
        if v is None:
            return "Nothing is designed yet."
        out_dir = self.folder / "exports"
        out_dir.mkdir(exist_ok=True)
        spec = v["spec"]
        f = spec["fields"]
        who = _slug(f.get("name") or f.get("brand") or f.get("org") or f.get("headline") or f.get("event") or f.get("recipient") or "design")
        base = f"{KINDS[spec['kind']]['label'].title()} {who} v{v['v']}"
        saved = []
        batch = next((b for b in reversed(self.state.get("batches", [])) if b["v"] == v["v"]), None)
        if fmt in ("pdf", "both"):
            src = batch["pdf"] if batch else v["files"]["pdf"]
            if not src:
                if fmt == "pdf":
                    fmt = "png"  # screen designs have no print file
            else:
                dst = out_dir / (f"{base} ({len(batch['names'])} certificates).pdf" if batch else f"{base}.pdf")
                shutil.copy2(src, dst)
                saved.append(dst)
        if fmt in ("png", "both"):
            for p in v["files"]["png"]:
                side = Path(p).stem.split("_")[-1]
                if kw.get("for") == "whatsapp":
                    from PIL import Image
                    dst = out_dir / f"{base} {side}.jpg"
                    im = Image.open(p).convert("RGB")
                    if max(im.size) > 2000:
                        im.thumbnail((2000, 2000))
                    im.save(dst, quality=90, optimize=True)
                else:
                    dst = out_dir / f"{base} {side}.png"
                    shutil.copy2(p, dst)
                saved.append(dst)
        for s in saved:
            self.state["exports"].append({"path": str(s), "v": v["v"], "fmt": s.suffix[1:]})
        note = ""
        if kw.get("for") == "print" and v["files"]["pdf"]:
            _, _, _, bleed, _ = __import__("harness.design.kinds", fromlist=["size_of"]).size_of(spec)
            note = f" (vector PDF at the exact size with {bleed:g} mm bleed: tell the print shop 'trim to size')" if bleed else " (vector PDF at the exact size)"
        return "Saved " + "; ".join(str(s) for s in saved) + note + "." if saved else "Nothing to save."

    # ---------------------------------------------------------------- history
    def undo(self):
        v = self.cur()
        if v is None or v.get("parent", -1) < 0:
            return "Nothing to undo."
        self.state["redo"].append(self.state["cur"])
        self.state["cur"] = v["parent"]
        return f"Back to v{self.state['cur']} ({self.cur()['said'][:60]})."

    def redo(self):
        if not self.state["redo"]:
            return "Nothing to redo."
        self.state["cur"] = self.state["redo"].pop()
        return f"Forward to v{self.state['cur']} ({self.cur()['said'][:60]})."

    def goto(self, n):
        if not 0 <= n < len(self.state["versions"]):
            return f"There is no v{n}."
        self.state["cur"] = n
        self.state["redo"] = []
        return f"Now at v{n} ({self.cur()['said'][:60]})."

    def history(self):
        return "\n".join(f"v{v['v']} {KINDS[v['spec']['kind']]['label']} ({v['spec']['style']}): '{v['said'][:60]}'" + (" <- now" if v["v"] == self.state["cur"] else "")
                         for v in self.state["versions"]) or "Nothing yet."

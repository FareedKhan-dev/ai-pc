"""A conversation about a photo. Every message makes one version; each edit is checked by measuring the result.

  c = PhotoChat.start("car.jpg")                      the original is never changed: versions live in the chat's folder
  c.say("it's too dark, fix it")                      -> what was done and why ("it was dark (11% average)...") and the checks
  c.say("crop to the car and add 'FOR SALE' at the top in red")
  c.say("undo")  /  c.say("go back to v1")  /  c.say("compare with the original")  /  c.say("what's in the photo?")
  c.say("save it for an Instagram story without cropping, under 500 KB")      -> a file in the chat's exports folder
  c.say("add beach.jpg and city.jpg")  then  c.say("make a collage")      several photos
Location (GPS) is taken out of every saved photo unless asked otherwise; 'remove all metadata' takes out the rest too.
"""
import datetime as dt
import io
import json
import re
import time
from pathlib import Path

from PIL import Image, ImageOps

from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json
from ai_pc.photo import analyze as A
from ai_pc.photo import ops as O
from ai_pc.photo.photoparse import parse

CHATS = ROOT / "out" / "photo" / "chats"
UNDO = re.compile(r"^\s*(?:undo|revert|go back|take (?:that|it) back|reverse (?:that|it)|undo (?:that|it|the last (?:change|one|edit)))\b(?!.*\bv\d)", re.I)
REDO = re.compile(r"^\s*redo\b|\bdo it again\b", re.I)
GOTO = re.compile(r"\b(?:go back to|back to|restore|use|show me|switch to)\s+(?:version\s*|v)(\d+)\b|\b(?:the )?original\b(?!.*\bcompare)", re.I)
HISTORY = re.compile(r"^\s*(?:history|versions|show (?:me )?(?:the )?(?:history|versions)|what (?:did you|have you) (?:do|done|change|changed))\b", re.I)
COMPARE = re.compile(r"\bcompare\b|\bbefore and after\b|\bbefore/after\b|\bside by side with the original\b", re.I)
ADD = re.compile(r"^\s*(?:add|use|include|bring in|load)\s+(.+\.(?:jpe?g|png|webp|bmp|gif|tiff?|heic)\b.*)$", re.I)
SPLIT = re.compile(r"(?<=[.!?;])\s+|,?\s+(?:and then|then|and also|also|after that)\s+|,?\s+and\s+(?=(?:make|crop|add|put|write|remove|blur|turn|rotate|flip|straighten|resize|"
                   r"sharpen|brighten|darken|increase|reduce|save|export|convert|change|replace|fix|give|apply|smooth|lift)\b)", re.I)
IMAGE_OPS = set(O.OPS) | {"collage"}
FAMILIES = [{"blur_faces"}, set(O.LOOKS), {"crop", "canvas", "trim"}, {"text"}, {"meme"}, {"watermark"}, {"replace_background", "remove_background", "blur_background"},
            {"passport"}, {"border", "polaroid", "rounded"}, {"brightness"}, {"contrast"}, {"saturation", "vibrance"}, {"warmth"}, {"resize"},
            {"rotate", "flip", "straighten"}, {"auto"}, {"vignette"}, {"sharpen", "blur"}]  # 'instead' swaps an edit for another of its kind
FRAMES = {"border", "polaroid", "rounded"}  # stay on the outside: a later crop or turn goes in before them
GEOMETRY = {"crop", "trim", "canvas", "rotate", "flip", "straighten", "resize"}

PHOTO_SYSTEM = """You turn a person's request about a photo into edits for a program. Reply with ONE JSON object: {"ops": [...]} or
{"ask": "<short question back>"}. Edits (amounts: about 0.15 small, 0.3 normal, 0.5 strong; negative = the other way):
 {"op": "auto"}  {"op": "brightness", "amount": 0.3}  {"op": "contrast", "amount": 0.25}  {"op": "saturation", "amount": 0.3}  {"op": "vibrance", "amount": 0.35}
 {"op": "warmth", "amount": 0.3}  {"op": "shadows", "amount": 0.4}  {"op": "highlights", "amount": 0.4}  {"op": "white_balance"}  {"op": "clarity", "amount": 0.5}
 looks: {"op": "bw"|"sepia"|"vintage"|"cinematic"|"dramatic"|"fade"|"soft"|"pop"|"sketch"|"cartoon"|"painting"|"hdr"|"invert"}
 {"op": "crop", "aspect": "1:1|4:5|9:16|16:9|3:2"}  {"op": "crop", "subject": true}  {"op": "trim", "amount": 0.08}  {"op": "rotate", "degrees": 90}
 {"op": "flip", "how": "horizontal"}  {"op": "straighten"}  {"op": "resize", "width": 1080}  {"op": "canvas", "aspect": "9:16", "fill": "blur|white"}
 {"op": "border", "color": "white"}  {"op": "rounded"}  {"op": "polaroid", "caption": "..."}  {"op": "vignette", "amount": 0.35}
 {"op": "denoise", "strength": 0.6}  {"op": "sharpen", "amount": 0.6}  {"op": "blur", "amount": 0.5}  {"op": "blur_faces", "style": "blur|pixelate"}
 {"op": "blur_background"}  {"op": "remove_background"}  {"op": "replace_background", "color": "white"}  {"op": "replace_background", "image": "<file>"}
 {"op": "smooth_skin"}  {"op": "brighten_faces"}  {"op": "erase", "where": "bottom-right"}
 {"op": "text", "text": "...", "where": "auto|top|bottom|center|top-left|...", "color": "auto|<colour>", "size": "small|medium|large|huge", "style": "caption|title|banner"}
 {"op": "meme", "top": "...", "bottom": "..."}  {"op": "watermark", "text": "© ...", "where": "bottom-right", "tiled": false}
 {"op": "passport", "standard": "35x45|us|uk|uae|saudi|canada", "sheet": "4x6"}  {"op": "document"}  {"op": "collage"}
 {"op": "describe"}  {"op": "export", "fmt": "jpg|png|webp|pdf", "preset": "instagram|instagram story|youtube thumbnail|...", "max_kb": 500}
Do only what was asked."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


class PhotoChat:
    def __init__(self, state, planner=None, log=print):
        self.state, self.planner, self.log = state, planner, log
        self.folder = Path(state["folder"])
        self.last_turn = None

    @classmethod
    def start(cls, src, extra=None, chats_dir=None, planner=None, log=print):
        src = Path(src).resolve()
        if not src.is_file():
            raise FileNotFoundError(src)
        raw = Image.open(src)
        exif = raw.getexif()
        im = ImageOps.exif_transpose(raw)
        im.load()
        stem = re.sub(r"[^A-Za-z0-9]+", "_", src.stem)[:24].strip("_").lower() or "photo"
        cid = f"photo_{stem}_{time.strftime('%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        keep = im if im.mode in ("RGB", "RGBA") else im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")
        keep.save(folder / "v0.png", compress_level=1)
        if exif:
            (folder / "exif.bin").write_bytes(exif.tobytes())
        state = {"id": cid, "folder": str(folder), "src": str(src), "extra": [], "cur": 0, "redo": [], "exports": [], "turns": [],
                 "gps": bool(exif.get_ifd(0x8825)) if exif else False,
                 "versions": [{"v": 0, "file": "v0.png", "said": "(the original)", "ops": [], "checks": [], "size": list(im.size), "when": _when()}]}
        c = cls(state, planner=planner, log=log)
        for e in extra or []:
            c.add(e)
        c.save()
        return c

    @classmethod
    def load(cls, cid, chats_dir=None, planner=None, log=print):
        f = Path(chats_dir or CHATS) / cid / "chat.json"
        return cls(json.loads(f.read_text(encoding="utf-8")), planner=planner, log=log)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def close(self):
        pass

    def image(self, v=None):
        v = self.state["cur"] if v is None else v
        im = Image.open(self.folder / self.state["versions"][v]["file"])
        im.load()
        return im

    def add(self, path):
        p = self._find(path)
        if p is None:
            raise FileNotFoundError(path)
        if str(p) not in self.state["extra"]:
            self.state["extra"].append(str(p))
        return p

    def _find(self, name):
        """A photo the person names: a path, or a name next to the original, among the added photos, or in the project's
        media. 'replace the background with beach.jpg' -> the longest tail of the words that is a real file."""
        words = str(name).strip().strip("'\"").split()
        for i in range(len(words)):
            n = " ".join(words[i:])
            cands = [Path(n), Path(self.state["src"]).parent / n] + [Path(e) for e in self.state["extra"] if Path(e).name.lower() == n.lower()] + \
                [ROOT / "media" / n, ROOT / n]
            hit = next((c.resolve() for c in cands if c.is_file()), None)
            if hit is None and (ROOT / "media").is_dir():
                hit = next((p.resolve() for p in (ROOT / "media").rglob("*") if p.is_file() and p.name.lower() == n.lower()), None)
            if hit is not None:
                return hit
        return None

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "llm": False, "v_from": self.state["cur"]}
        self._turn = turn
        low = message.strip()
        out = []
        m = GOTO.search(low)
        if UNDO.search(low) and not m:
            turn["intents"].append("undo")
            n = 2 if re.search(r"\b(?:two|2|last two)\b", low, re.I) else 3 if re.search(r"\b(?:three|3)\b", low, re.I) else 1
            out.append(self.undo(n))
        elif REDO.search(low):
            turn["intents"].append("redo")
            out.append(self.redo())
        elif HISTORY.search(low):
            turn["intents"].append("history")
            out.append(self.history())
        elif COMPARE.search(low):
            turn["intents"].append("compare")
            vs = [int(x) for x in re.findall(r"\bv(?:ersion\s*)?(\d+)\b", low, re.I)]
            a, b = (vs[0], vs[1]) if len(vs) >= 2 else (0 if not vs else vs[0], self.state["cur"])
            out.append(self.compare(a, b))
        elif m and re.search(r"\b(?:go back|back to|restore|use|show me|switch to|the original)\b", low, re.I) and not re.search(r"\bsave|export\b", low, re.I):
            turn["intents"].append("goto")
            out.append(self.goto(int(m.group(1)) if m.group(1) else 0))
        elif ADD.search(low):
            turn["intents"].append("add")
            names = re.findall(r"([\w][\w .()&'\-]*\.(?:jpe?g|png|webp|bmp|gif|tiff?|heic))\b", ADD.search(low).group(1), re.I)
            got, miss = [], []
            for nm in names:
                nm = re.sub(r"^(?:and|the|photo|picture)\s+", "", nm.strip(), flags=re.I)
                try:
                    got.append(self.add(nm).name)
                except FileNotFoundError:
                    miss.append(nm)
            out.append((f"Added {', '.join(got)} ({len(self.state['extra']) + 1} photos in this chat; say 'make a collage')." if got else "") +
                       (f" I can't find {', '.join(miss)}." if miss else ""))
        else:
            clauses = [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")]
            ops = []
            for cl in clauses or [message]:
                r = parse(cl, raw=cl)
                if not r["ops"] and not r.get("ask"):
                    r = self._llm(cl, message)
                if r.get("ask") and not r["ops"]:
                    out.append(r["ask"])
                    turn["intents"].append("ask")
                    ops = []
                    break
                ops += r["ops"]
            if ops:
                out.append(self._apply(ops, message))
        reply = "\n".join(x for x in out if x).strip() or "Tell me what to change, e.g. 'make it brighter', 'crop it square', 'remove the background', or 'help'."
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), v_to=self.state["cur"])
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, clause, message):
        if self.planner is None:
            return {"ops": [], "ask": f"I could not read '{clause}'. Try e.g. 'make it brighter', 'crop it square', 'blur the faces', or 'help'."}
        self._turn["llm"] = True
        im = self.image()
        user = (f"PHOTO: {A.describe(im)}\nOTHER PHOTOS IN THIS CHAT: {json.dumps([Path(e).name for e in self.state['extra']])}\n"
                f"MESSAGE: {message}\nREQUEST: {clause}")
        try:
            r = self.planner._call("fast", [{"role": "system", "content": PHOTO_SYSTEM}, {"role": "user", "content": user}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and (o.get("op") in IMAGE_OPS or o.get("op") in ("describe", "export", "help", "strip"))]
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- doing
    def _family(self, k):
        return next((i for i, f in enumerate(FAMILIES) if k in f), None)

    def _lineage(self, v=None):
        """The versions that made this one, oldest first (v0 not included)."""
        v = self.state["cur"] if v is None else v
        out = []
        while v:
            rec = self.state["versions"][v]
            out.append(rec)
            v = rec.get("parent", 0)
        return out[::-1]

    def _find_op(self, test):
        """(index in the lineage, index in that version's edits) of the latest edit that passes test, else None."""
        lin = self._lineage()
        for vi in range(len(lin) - 1, -1, -1):
            for oi in range(len(lin[vi]["ops"]) - 1, -1, -1):
                if test(lin[vi]["ops"][oi]):
                    return vi, oi
        return None

    def _replace(self, op, said, before=False):
        """'... instead' / 'move the text to the bottom': the latest edit of the same kind is swapped (or changed), and
        every edit made after it is done again on top, so nothing else is lost. before=True: the new edit goes in just
        before the latest frame instead (a crop after a border keeps the border on the outside). None when there is no
        such edit."""
        lin = self._lineage()
        if before:
            hit = self._find_op(lambda o: o.get("op") in FRAMES)
        else:
            fam = self._family(op["op"])
            hit = self._find_op(lambda o: self._family(o.get("op")) == fam)
        if hit is None:
            return None
        vi, oi = hit
        old = lin[vi]["ops"][oi]
        if before:
            return self._rebuild(lin, vi, oi, {k: v for k, v in op.items() if k not in ("instead", "modify")}, old, said, insert=True)
        clean = {k: v for k, v in op.items() if k not in ("instead", "modify", "size_rel")}
        new = dict(old, **{k: v for k, v in clean.items() if v is not None}) if op.get("modify") else clean
        if op.get("size_rel") and new.get("op") == "text":  # 'bigger' / 'smaller': a step from the size it has now
            ladder = ["tiny", "small", "medium", "large", "huge"]
            t = str(new.get("text", ""))
            now = new.get("size") or ("large" if len(t) <= 16 or new.get("style") == "title" else "medium" if len(t) <= 40 else "small")
            i = ladder.index(now) if now in ladder else 2
            new["size"] = ladder[max(0, min(len(ladder) - 1, i + int(op["size_rel"])))]
        return self._rebuild(lin, vi, oi, new, old, said, modify=bool(op.get("modify")))

    def _rebuild(self, lin, vi, oi, new, old, said, insert=False, modify=False):
        """Edits done again from the version before lin[vi]: the edit at oi swapped for new (or new put in before it), and
        everything after redone. One new version; 'undo' returns to the version that was showing."""
        base = lin[vi].get("parent", 0)
        im = self.image(base)
        chain, checks, notes, words, after_n = [], [], [], None, 0
        for j in range(vi, len(lin)):
            seq = list(lin[j]["ops"])
            if j == vi:
                seq = seq[:oi] + [new] + seq[oi:] if insert else seq[:oi] + [new] + seq[oi + 1:]
            for o in seq:
                use = o
                if use.get("op") in ("describe", "help", "export", "strip", None):
                    continue
                args = {a: b for a, b in use.items() if a not in ("op", "instead", "modify", "want")}
                try:
                    if use["op"] == "collage":
                        new_im, info = O.collage([im] + [Path(e) for e in self.state["extra"]], layout=args.get("layout", "grid"))
                    else:
                        new_im, info = O.run(use["op"], im, args)
                except O.OpError as e:
                    if use is new:
                        return f"Couldn't {new['op'].replace('_', ' ')}: {e}."
                    notes.append(f"skipped the {use['op'].replace('_', ' ')} of v{lin[j]['v']} ({e})")
                    continue
                if use is new:
                    checks = O.check(use["op"], im, new_im, args, info)
                    words = self._words(use["op"], args, info, checks, im, new_im)
                elif words is not None:
                    after_n += 1
                im = new_im
                chain.append(use)
        v = len(self.state["versions"])
        f = f"v{v}.png"
        im.save(self.folder / f, compress_level=1)
        self.state["versions"].append({"v": v, "file": f, "said": said, "ops": chain, "checks": checks, "size": list(im.size), "when": _when(), "parent": base,
                                       "undo_to": self.state["cur"], "meta": {"replaced": {"v": lin[vi]["v"], "op": old.get("op")}}})
        self.state["cur"] = v
        self.state["redo"] = []
        bad = [c for c in checks if not c["ok"]]
        if insert:
            how = f"Done before the {old['op']} of v{lin[vi]['v']}, so it stays on the outside" + (f"; {after_n} edit(s) redone after it" if after_n else "")
        else:
            how = f"{'Changed' if modify else 'Swapped'} the {old['op'].replace('_', ' ')} made in v{lin[vi]['v']}" + (f" and redid the {after_n} edit(s) after it" if after_n else "")
        return (f"{words}\n{how}" + (f"; {'; '.join(notes)}" if notes else "") + f". (v{v}; checked {len(checks) - len(bad)}/{len(checks)}. 'undo' goes back.)")

    def _apply(self, ops, said):
        im = self.image()
        start = im
        self._meta = {}
        lines, done_ops, checks = [], [], []
        for op in ops:
            k = op.get("op")
            self._turn["intents"].append(k)
            frame_last = k in GEOMETRY and not op.get("instead") and im is start and self._find_op(lambda o: o.get("op") in FRAMES) is not None
            if op.get("instead") or op.get("modify") or frame_last:
                if done_ops:
                    self._new_version(im, said, done_ops, checks)
                    done_ops, checks = [], []
                r = self._replace(op, said, before=frame_last)
                if r is None and op.get("modify"):
                    lines.append("There is no text on this photo yet to change; say e.g. 'add \"SALE\" at the top'.")
                    continue
                if r is not None:
                    lines.append(r)
                    im = start = self.image()
                    continue
                op = {a: b for a, b in op.items() if a not in ("instead",)}
            args = {a: b for a, b in op.items() if a not in ("op", "want")}
            if k == "describe":
                lines.append(self.metadata() if op.get("meta") else self.describe(im))
                continue
            if k == "help":
                lines.append(self.help(im))
                continue
            if k == "strip":
                self.state["strip"] = args.get("what", "gps")
                lines.append("Location data will be left out of saved files." if self.state["strip"] == "gps" else "All metadata (camera, date, location) will be left out of saved files.")
                continue
            if k == "export":
                if done_ops:  # the edits made in this message are kept first, then saved
                    self._new_version(im, said, done_ops, checks)
                    done_ops, checks = [], []
                lines.append(self.export(**args))
                continue
            try:
                if k == "collage":
                    if not self.state["extra"]:
                        lines.append("Which photos? Add them first, e.g. 'add beach.jpg and city.jpg', then 'make a collage'.")
                        continue
                    new, info = O.collage([im] + [Path(e) for e in self.state["extra"]], layout=args.get("layout", "grid"))
                    chk = [O._ok(info["count"] >= 2, f"{info['count']} photos in a {args.get('layout', 'grid')}, {new.width}x{new.height}")]
                else:
                    if k == "replace_background" and args.get("image"):
                        p = self._find(args["image"])
                        if p is None:
                            lines.append(f"I can't find {args['image']}.")
                            continue
                        args["image"] = str(p)
                    if k == "watermark" and args.get("logo"):
                        p = self._find(args["logo"])
                        args["logo"] = str(p) if p else None
                    if k == "passport":
                        prev = (self.state["versions"][self.state["cur"]].get("meta") or {}).get("passport") if im is start else None
                        if prev and args.get("sheet") and not prev.get("copies") and args.get("standard") in (None, prev.get("key")):
                            args["ready"] = prev  # this already is the passport photo: only lay it out on the print
                            args["standard"] = prev.get("key")
                    new, info = O.run(k, im, args)
                    if k == "passport":
                        self._meta = {"passport": {k2: v2 for k2, v2 in info.items() if k2 in ("standard", "px", "head_share", "range", "dpi", "copies")} |
                                      {"key": args.get("standard") or "35x45"}}
                    chk = O.check(k, im, new, args, info)
                    if not all(c["ok"] for c in chk) and "amount" in args and isinstance(args["amount"], (int, float)):  # once more, firmer
                        args2 = dict(args, amount=args["amount"] * 1.7)
                        new2, info2 = O.run(k, im, args2)
                        chk2 = O.check(k, im, new2, args2, info2)
                        if all(c["ok"] for c in chk2):
                            new, info, chk = new2, info2, chk2 + [O._ok(True, "(done a second time, firmer, as the first was too slight)")]
            except O.OpError as e:
                lines.append(f"Couldn't {k.replace('_', ' ')}: {e}.")
                continue
            words = self._words(k, args, info, chk, im, new)
            if k == "passport" and op.get("want") and info.get("copies") and info["copies"] < op["want"]:
                words += f" Only {info['copies']} fit on a {info['sheet']} print with room to cut; say 'on A4' for more."
            lines.append(words)
            checks += chk
            done_ops.append(op)
            im = new
        if done_ops:
            v = self._new_version(im, said, done_ops, checks)
            bad = [c for c in checks if not c["ok"]]
            lines.append(f"(v{v}; checked {len(checks) - len(bad)}/{len(checks)}" + (f" - not right: {'; '.join(c['what'] for c in bad[:3])}" if bad else "") + ". 'undo' goes back.)")
        elif start is not im:
            pass
        return "\n".join(lines)

    def _new_version(self, im, said, ops, checks):
        v = len(self.state["versions"])
        f = f"v{v}.png"
        im.save(self.folder / f, compress_level=1)
        self.state["versions"].append({"v": v, "file": f, "said": said, "ops": ops, "checks": checks, "size": list(im.size), "when": _when(), "parent": self.state["cur"],
                                       "meta": getattr(self, "_meta", {}) or {}})
        self.state["cur"] = v
        self.state["redo"] = []
        return v

    def _words(self, k, args, info, chk, before, after):
        """What one edit did, said plainly with its numbers."""
        what = "; ".join(c["what"] for c in chk)
        size = f"{after.width}x{after.height}"
        if k == "auto":
            return "Enhanced: " + "; ".join(info.get("steps", [])) + f". ({what})"
        if k == "crop":
            if args.get("subject"):
                return f"Cropped to the subject ({info.get('shape', 'its own shape')}, {size})."
            return f"Cropped to {args.get('aspect')} ({size})" + ("; the face kept in frame." if info.get("faces") else ".")
        if k == "text":
            col = "auto colour" if args.get("color") in (None, "auto") else args["color"]
            return f"Wrote '{args.get('text')}' at the {info['where']} ({col}, {info['font_px']} px" + (", outlined to read on what is behind" if info["stroke"] else "") + \
                f"; contrast {info['contrast']}:1)."
        if k == "blur_faces":
            return f"{'Pixelated' if str(args.get('style', '')).startswith('pix') else 'Blurred'} {len(info['boxes'])} face(s). ({what})"
        if k == "remove_background":
            return f"Background removed ({info.get('how')}); the subject is {info.get('fg_share', 0):.0%} of the photo. It is transparent now: save it as PNG to keep that."
        if k == "replace_background":
            bg = info.get("background")
            return f"New background: {('a ' + str(args.get('color')) + ' one') if isinstance(bg, tuple) else bg} ({info.get('how')})."
        if k == "passport":
            return f"Passport photo {info['standard']} ({info['px'][0]}x{info['px'][1]} px at {info['dpi']} dpi): head {info['head_share']:.0%} of the height " + \
                f"({info['range'][0]:.0%}-{info['range'][1]:.0%} asked), plain {args.get('bg', 'white')} background" + \
                (f"; {info['copies']} copies on a {info['sheet']} print ({info['sheet_px'][0]}x{info['sheet_px'][1]} px)." if info.get("copies") else ".")
        if k == "document":
            return f"Flattened the page into a clean scan ({size}). ({what})"
        if k == "canvas":
            return f"Fitted the whole photo into {args.get('aspect')} ({size}), the sides filled with {'a blurred copy' if args.get('fill', 'blur') == 'blur' else args.get('fill')}."
        if k == "collage":
            return f"Made a collage: {what}."
        names = {"bw": "Black and white", "sepia": "Sepia", "vintage": "A vintage look", "cinematic": "A cinematic look (teal shadows, warm highlights)",
                 "dramatic": "A dramatic look", "fade": "A faded, matte look", "soft": "A soft glow", "pop": "Colours that pop", "sketch": "A pencil sketch",
                 "cartoon": "A cartoon look", "painting": "A painted look", "hdr": "An HDR look", "invert": "A negative"}
        if k in names:
            return f"{names[k]}. ({what})"
        verbs = {"brightness": "Brighter" if float(args.get("amount", 0) or 0) >= 0 else "Darker", "contrast": "Contrast", "saturation": "Colour", "vibrance": "Vibrance",
                 "warmth": "Warmer" if float(args.get("amount", 0) or 0) >= 0 else "Cooler", "shadows": "Shadows", "highlights": "Highlights",
                 "white_balance": "Colours neutralised", "levels": "Levels", "clarity": "Clarity", "rotate": "Rotated", "flip": "Flipped", "straighten": "Straightened",
                 "resize": f"Resized to {size}", "trim": f"Trimmed the edges ({size})", "border": "Border added", "rounded": "Rounded corners", "polaroid": "A photo frame",
                 "vignette": "Darker edges", "denoise": "Less grain", "sharpen": "Sharper", "blur": "Blurred", "blur_background": "Background blurred",
                 "smooth_skin": "Skin smoothed", "brighten_faces": "Faces lifted", "erase": "Removed what was in the corner", "meme": "Meme text added",
                 "watermark": "Watermark added"}
        return f"{verbs.get(k, k)}: {what}."

    # ---------------------------------------------------------------- answers
    def describe(self, im=None):
        im = im or self.image()
        st = A.stats(im)
        fl = A.faces(im)
        bd = A.backdrop(im)
        txt = A.describe(im, st, fl, bd)
        ideas = []
        if st["brightness"] < 0.33:
            ideas.append("'fix it' would brighten it")
        if bd["kind"] in ("green", "blue"):
            ideas.append("'remove the background' keys the screen out; 'replace the background with <photo>' puts the subject anywhere")
        if fl:
            ideas.append("'blur the faces' hides them" if len(fl) > 1 else "'make a passport photo' works with this face")
        if abs(A.tilt(im)) >= 0.8:
            ideas.append("'straighten it' levels it")
        if st["noise"] > 0.025:
            ideas.append("'remove the grain'")
        return f"v{self.state['cur']}: {txt}" + (" Ideas: " + "; ".join(ideas) + "." if ideas else "")

    def metadata(self):
        """What the original file says about itself: when it was taken, with what, and where (its GPS position)."""
        ef = self.folder / "exif.bin"
        if not ef.exists():
            return "The photo carries no metadata (no date taken, camera or location)."
        ex = Image.Exif()
        ex.load(ef.read_bytes())
        sub = ex.get_ifd(0x8769)
        when = sub.get(36867) or ex.get(306)
        cam = " ".join(str(v).strip() for v in (ex.get(271), ex.get(272)) if v)
        gps = ex.get_ifd(0x8825)
        parts = [f"taken on {str(when).replace(':', '-', 2)}" if when else "taken"]
        if cam:
            parts.append(f"with a {cam}")
        if gps and 2 in gps and 4 in gps:
            def deg(v, ref):
                d, m_, s = (float(x) for x in v)
                return (d + m_ / 60 + s / 3600) * (-1 if str(ref).upper() in ("S", "W") else 1)
            lat, lon = deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
            parts.append(f"at {lat:.5f}, {lon:.5f} (its GPS position: anyone you send the original to can see where it was taken)")
            tail = " Say 'remove the location' and saved copies leave it out (they already do unless you ask otherwise)."
        else:
            tail = " It has no location in it."
        return ("The original was " + " ".join(parts) + "." if len(parts) > 1 or when else "The photo has metadata but no date, camera or location.") + tail

    def help(self, im=None):
        return ("I edit photos by code and check each change: light ('brighter', 'fix it', 'warmer', 'more contrast'), looks ('black and white', 'vintage', "
                "'cinematic', 'sketch'), shape ('crop it square', 'crop to the car', 'fit it in a story without cropping', 'straighten it'), people "
                "('blur the faces', 'blur the background', 'remove the background', 'make the background white', 'passport photo'), words ('add \"SALE\" "
                "at the top in red', 'meme \"...\" / \"...\"', 'watermark \"© Me\"'), pages ('scan this document'), several photos ('add a.jpg', 'make a "
                "collage'), and saving ('save it for Instagram under 500 KB', 'as PNG'). 'undo', 'go back to v2', 'compare with the original'.")

    # ---------------------------------------------------------------- the history
    def undo(self, n=1):
        cur = self.state["cur"]
        for _ in range(n):
            rec = self.state["versions"][cur]
            par = rec.get("undo_to", rec.get("parent"))
            if cur == 0 or par is None:
                break
            self.state["redo"].append(cur)
            cur = par
        if cur == self.state["cur"]:
            return "Nothing to undo: this is the original."
        self.state["cur"] = cur
        return f"Back to v{cur} ({self.state['versions'][cur]['said'][:60]})."

    def redo(self):
        if not self.state["redo"]:
            return "Nothing to redo."
        self.state["cur"] = self.state["redo"].pop()
        return f"Forward to v{self.state['cur']} ({self.state['versions'][self.state['cur']]['said'][:60]})."

    def goto(self, v):
        if not 0 <= v < len(self.state["versions"]):
            return f"There is no v{v} (v0 to v{len(self.state['versions']) - 1})."
        if v == self.state["cur"]:
            return f"This is already v{v}."
        self.state["cur"] = v
        self.state["redo"] = []
        return f"Now at v{v} ({self.state['versions'][v]['said'][:60]}). The newer versions are kept: 'go back to v{len(self.state['versions']) - 1}' returns."

    def history(self):
        lines = []
        for x in self.state["versions"]:
            mark = " <- now" if x["v"] == self.state["cur"] else ""
            ops = ", ".join(o.get("op", "?") for o in x["ops"]) or "the original"
            lines.append(f"v{x['v']} {x['size'][0]}x{x['size'][1]}: '{x['said'][:50]}' ({ops}){mark}")
        return "\n".join(lines)

    def compare(self, a=0, b=None):
        b = self.state["cur"] if b is None else b
        n = len(self.state["versions"])
        if not (0 <= a < n and 0 <= b < n):
            return "Compare which versions? e.g. 'compare v1 and v3'."
        img, _ = O.side_by_side(self.image(a), self.image(b), labels=(f"v{a}" if a else "Before", f"v{b}" if b != self.state["cur"] or a else "After"))
        p = self.folder / f"compare_v{a}_v{b}.jpg"
        img.save(p, quality=88)
        sa, sb = A.stats(self.image(a)), A.stats(self.image(b))
        diffs = [f"{k} {sa[k]:.0%} -> {sb[k]:.0%}" for k in ("brightness", "saturation") if abs(sa[k] - sb[k]) > 0.02] + \
                ([f"contrast {sa['contrast']:.2f} -> {sb['contrast']:.2f}"] if abs(sa["contrast"] - sb["contrast"]) > 0.01 else [])
        size = f"{sa['width']}x{sa['height']} -> {sb['width']}x{sb['height']}" if (sa["width"], sa["height"]) != (sb["width"], sb["height"]) else ""
        return f"Side by side: {p} (v{a} left, v{b} right)." + (" " + "; ".join([d for d in diffs + [size] if d]) + "." if diffs or size else "")

    # ---------------------------------------------------------------- saving
    def export(self, fmt=None, max_kb=None, preset=None, fit="crop", quality=None, strip=None, beside=False, dst=None):
        im = self.image()
        notes = []
        if preset:
            size = O.PRESETS.get(preset)
            if size is None:
                return f"I don't know the format '{preset}'."
            im = O.canvas(im, size=size)[0] if fit == "canvas" else O.cover(im, size)
            notes.append(f"{preset} {size[0]}x{size[1]}" + (" (the whole photo, the sides filled)" if fit == "canvas" else ""))
        alpha = im.mode == "RGBA" and min(im.getchannel("A").getextrema()) < 250
        fmt = (fmt or ("png" if alpha and not preset else "jpg")).lower().replace("jpeg", "jpg")  # social sites and prints have no transparency
        if alpha and fmt in ("jpg", "pdf"):
            flat = Image.new("RGB", im.size, "white")
            flat.paste(im, mask=im.getchannel("A"))
            im = flat
            notes.append("transparent parts made white (JPG has no transparency; say 'as PNG' to keep it)")
        elif fmt in ("jpg", "pdf") and im.mode != "RGB":
            im = im.convert("RGB")
        strip = strip or self.state.get("strip", "gps")
        exif = None
        ef = self.folder / "exif.bin"
        if ef.exists() and strip != "all" and fmt in ("jpg", "webp", "png"):
            ex = Image.Exif()
            ex.load(ef.read_bytes())
            if 0x8825 in ex:
                del ex[0x8825]
                if self.state.get("gps"):
                    notes.append("location removed")
            ex[0x0112] = 1  # the pixels are already upright
            exif = ex.tobytes()
        elif strip == "all":
            notes.append("all metadata removed")
        src = Path(self.state["src"])
        base = (src.parent if beside else self.folder / "exports")
        base.mkdir(parents=True, exist_ok=True)
        name = f"{src.stem} (edited).{fmt}"
        p = base / name
        k = 2
        while p.exists():
            p = base / f"{src.stem} (edited {k}).{fmt}"
            k += 1
        if dst:
            p = Path(dst)
        q = int(quality or 90)

        def write(img, qq):
            buf = io.BytesIO()
            if fmt == "jpg":
                img.save(buf, "JPEG", quality=qq, optimize=True, progressive=True, **({"exif": exif} if exif else {}))
            elif fmt == "webp":
                img.save(buf, "WEBP", quality=qq, method=5, **({"exif": exif} if exif else {}))
            elif fmt == "png":
                img.save(buf, "PNG", optimize=True, **({"exif": exif} if exif else {}))
            elif fmt == "pdf":
                img.save(buf, "PDF", resolution=300.0)
            else:
                raise O.OpError(f"I can't save as {fmt}")
            return buf.getvalue()
        data = write(im, q)
        if max_kb and len(data) > max_kb * 1024:
            if fmt in ("jpg", "webp"):
                lo, hi, best = 30, q, None
                while lo <= hi:
                    mid = (lo + hi) // 2
                    d = write(im, mid)
                    if len(d) <= max_kb * 1024:
                        best, lo = (mid, d), mid + 1
                    else:
                        hi = mid - 1
                shrink = 1.0
                while best is None and shrink > 0.3:
                    shrink *= 0.85
                    im2 = im.resize((max(1, round(im.width * shrink)), max(1, round(im.height * shrink))), Image.LANCZOS)
                    d = write(im2, 72)
                    if len(d) <= max_kb * 1024:
                        best, im = (72, d), im2
                if best:
                    q, data = best
                    notes.append(f"quality {q}" + (f", made {im.width}x{im.height} to fit" if shrink < 1 else ""))
            elif fmt == "png" and not alpha:
                d = write(im.convert("P", palette=Image.Palette.ADAPTIVE, colors=256), q)
                if len(d) < len(data):
                    data = d
                    notes.append("256 colours to make it smaller")
        p.write_bytes(data)
        kb = len(data) / 1024
        checks = []
        try:
            with Image.open(p) as chk:
                chk.load()
                checks.append(O._ok(True, f"opens: {chk.width}x{chk.height} {chk.format}"))
                if preset:
                    checks.append(O._ok(chk.size == tuple(O.PRESETS[preset]), f"{preset} size"))
                gps = chk.getexif().get_ifd(0x8825) if fmt in ("jpg", "webp", "png") else {}
                checks.append(O._ok(not gps, "no location in the file"))
        except Exception as e:  # noqa: BLE001
            checks.append(O._ok(False, f"does not open: {e}"))
        if max_kb:
            checks.append(O._ok(kb <= max_kb, f"{kb:.0f} KB (under {max_kb:.0f} KB asked)"))
        self.state["exports"].append({"path": str(p), "v": self.state["cur"], "kb": round(kb, 1), "when": _when()})
        bad = [c for c in checks if not c["ok"]]
        return f"Saved {p} ({kb:.0f} KB" + (", " + ", ".join(notes) if notes else "") + f"). Checked {len(checks) - len(bad)}/{len(checks)}" + \
            (": " + "; ".join(c["what"] for c in bad) if bad else "") + "."

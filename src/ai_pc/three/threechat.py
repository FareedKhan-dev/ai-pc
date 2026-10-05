"""A conversation in 3D (Blender in the background): houses from plans, 3D titles, product mockups, someone's 3D files.
Every change makes a version; every version is rendered and checked.

  c = ThreeChat.start()
  c.say("a 3D model of a 5 marla house with 3 bedrooms")   -> the plan (CAD lane) and its 3D floor plan and front view
  c.say("show it from above") / c.say("make a video going round it") / c.say("grey walls with wood panels")
  c.say("make the kitchen bigger")                          -> the plan changes (CAD lane), the 3D follows
  c.say("a 3D intro for Khan Electronics in gold")          -> a 5 s video and its last frame
  c.say("put card.png on a box") / c.say("show site.png on a laptop") / c.say("a mug with logo.png")
  c.say("show me chair.glb") / c.say("convert it to stl") / c.say("is it ready for 3D printing?")
  c.say("undo") / c.say("go back to v1") / c.say("history") / c.say("save it to my desktop")
"""

import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json
from ai_pc.three import blender as B
from ai_pc.three import make as MK
from ai_pc.three.threeparse import parse

CHATS = ROOT / "out" / "three" / "chats"
CAD_CHATS = ROOT / "out" / "cad" / "chats"
UNDO = re.compile(
    r"^\s*(?:please\s+)?(?:undo(?: that| it)?|revert(?: that| it)?|go back(?: one)?|take (?:that|it) back)(?:\s+please)?\s*[.!]*\s*$", re.I
)
REDO = re.compile(r"^\s*redo\b", re.I)
GOTO = re.compile(r"\b(?:go back to|back to|restore|use|switch to)\s+(?:version\s*|v)(\d+)\b", re.I)
HISTORY = re.compile(r"^\s*(?:history|versions|show (?:me )?(?:the )?(?:history|versions))\b", re.I)
SPLIT = re.compile(
    r"(?<=[.!?;])\s+|,?\s+(?:and then|then|also)\s+|,?\s+and\s+(?=(?:make|show|add|put|remove|give|turn|render|convert|save|change|use)\b)", re.I
)
HOUSE = {
    "views": ["plan3d", "front"],
    "style": "modern",
    "colors": {},
    "storey": "ground",
    "furniture": True,
    "labels": True,
    "quality": "normal",
    "big": False,
    "seconds": 6,
}
KNOWN = {
    "house_new",
    "house_from_cad",
    "cad",
    "view",
    "storey",
    "colors",
    "style",
    "furniture",
    "labels",
    "quality",
    "big",
    "seconds",
    "text_new",
    "text_style",
    "mockup",
    "mockup_image",
    "mockup_kind",
    "mockup_size",
    "angle",
    "model",
    "model_export",
    "ask",
    "save",
}
THREE_SYSTEM = """You turn a person's request about 3D work into changes for a program. Reply with ONE JSON object: {"ops": [...]}
or {"ask": "<short question back>"}. Each op is {"op": NAME, "args": {...}}:
 house_new {"brief": "<the house described, e.g. 5 marla, 3 bedrooms, double story>"}   house_from_cad {} (the plan they already drew)
 cad {"text": "<a change to the plan itself: rooms, sizes, floors>"}
 view {"kind": "plan3d|top|front|aerial|orbit", "only": false}   storey {"which": "ground|first"}
 colors {"wall": "plaster_white|plaster_cream|plaster_grey", "accent": "stone_grey|wood_light|brick_red|marble", "frame": "frame_black|frame_white|frame_brown"}
 style {"name": "modern|warm|grey|classic"}   furniture {"on": true}   labels {"on": true}   quality {"level": "high|normal"}   big {"on": true}
 seconds {"value": 8}
 text_new {"text": "<the words>"}   text_style {"material": "gold|silver|chrome|copper|glass|neon|black|white|red|blue", "sub": "<second line>",
   "anim": "dolly|spin|rise|drop", "background": "dark|white|studio|blue|navy|red|green|purple", "text": "<new words>"}
 mockup {"kind": "box|card|laptop|phone|mug|poster", "images": ["<file>"]}   mockup_kind {"kind": "..."}   mockup_size {"w": 20, "h": 30, "d": 8} (cm)
 angle {"turn": 40}   model {"file": "<3D file>"}   model_export {"fmt": "glb|gltf|obj|fbx|stl|ply|usd"}
 ask {"what": "info|print|where"}   save {"where": "desktop|downloads|documents|pictures|videos"}
Do only what was asked."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


class ThreeChat:
    def __init__(self, state, planner=None, log=print):
        self.state, self.planner, self.log = state, planner, log
        self.folder = Path(state["folder"])
        self.last_turn = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, log=print, files=None):
        base = Path(chats_dir or CHATS).resolve()
        folder = base / f"three_{time.strftime('%H%M%S')}"
        k = 2
        while folder.exists():
            folder = base / f"three_{time.strftime('%H%M%S')}_{k}"
            k += 1
        folder.mkdir(parents=True)
        state = {
            "id": folder.name,
            "folder": str(folder),
            "versions": [],
            "cur": -1,
            "redo": [],
            "turns": [],
            "exports": [],
            "subject": None,
            "params": {},
            "cad_chat": None,
            "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in (files or [])},
        }
        c = cls(state, planner=planner, log=log)
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
        if UNDO.search(message):
            turn["intents"].append("undo")
            out.append(self.undo())
        elif REDO.search(message):
            turn["intents"].append("redo")
            out.append(self.redo())
        elif m and self.state["versions"]:
            turn["intents"].append("goto")
            out.append(self.goto(int(m.group(1))))
        elif HISTORY.search(message):
            turn["intents"].append("history")
            out.append(self.history())
        else:
            self._remember_files(message)
            ops = []
            for cl in [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")] or [message]:
                r = parse(cl, {"subject": self.state["subject"], "files": self.state["files"]})
                if not r["ops"] and (self.planner is not None or not r.get("ask")):
                    r2 = self._llm(cl, message)
                    r = r2 if (r2["ops"] or not r.get("ask")) else r
                if r.get("ask") and not r["ops"]:
                    out.append(r["ask"])
                    ops = []
                    break
                ops += r["ops"]
            if ops:
                out.append(self._apply(ops, message))
        reply = "\n".join(x for x in out if x).strip() or (
            "Tell me what to make in 3D, e.g. 'a 3D model of a 5 marla house with 3 bedrooms', 'a 3D intro "
            "for Khan Electronics in gold', 'put card.png on a box', 'show me chair.glb'."
        )
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), v_to=self.state["cur"])
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _remember_files(self, message):
        for name in re.findall(
            r"([A-Za-z]:\\[^\"'<>|]+?\.\w{2,5}|[\w\-.()]+\.(?:png|jpe?g|webp|glb|gltf|obj|fbx|stl|ply|usdz?|blend))\b", message, re.I
        ):
            p = Path(name)
            for c in (p, Path.cwd() / name):
                if c.is_file():
                    self.state["files"][c.name.lower()] = str(c.resolve())
                    break

    def _llm(self, clause, message):
        if self.planner is None:
            return {
                "ops": [],
                "ask": f"I could not read '{clause}'. Try e.g. 'a 3D model of a 5 marla house', 'show the front', 'a 3D intro for <name>', "
                "'put logo.png on a mug', 'show me chair.glb'.",
            }
        self._turn["llm"] = True
        ctx = f"NOW: {self.state['subject'] or 'nothing yet'} {json.dumps(self.state['params'])[:400]}; files named: {list(self.state['files'])}"
        try:
            r = self.planner._call(
                "fast", [{"role": "system", "content": THREE_SYSTEM}, {"role": "user", "content": f"{ctx}\nMESSAGE: {message}\nREQUEST: {clause}"}]
            )
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [
            o if "args" in o else {"op": o.get("op"), "args": {k: v for k, v in o.items() if k != "op"}}
            for o in d.get("ops") or []
            if isinstance(o, dict)
        ]
        ops = [o for o in ops if o.get("op") in KNOWN and isinstance(o.get("args") or {}, dict)]
        for o in ops:
            o["args"] = o.get("args") or {}
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- doing
    def _apply(self, ops, said):
        lines = []
        p = json.loads(json.dumps(self.state["params"]))
        subject = self.state["subject"]
        render = False
        for o in ops:
            k, a = o["op"], o.get("args") or {}
            self._turn["intents"].append(k)
            if k == "house_new":
                reply, lay_path = self._cad(a.get("brief") or said, new=True)
                if not lay_path:
                    return reply
                lines.append(reply.splitlines()[0])
                subject, p, render = "house", dict(HOUSE, plan=lay_path), True
            elif k == "house_from_cad":
                found = self._latest_cad_plan()
                if not found:
                    return "There is no house plan yet: describe the house, e.g. 'a 3D model of a 5 marla house with 3 bedrooms'."
                self.state["cad_chat"], lay_path = found
                subject, p, render = "house", dict(HOUSE, plan=lay_path), True
                lines.append(f"Your plan from the CAD chat {found[0]}.")
            elif k == "cad":
                if subject != "house":
                    return "Start a house first, e.g. 'a 3D model of a 5 marla house with 3 bedrooms'."
                reply, lay_path = self._cad(a.get("text") or said)
                lines.append("Plan: " + reply.splitlines()[0])
                if lay_path and lay_path != p.get("plan"):
                    p["plan"], render = lay_path, True
            elif k == "view" and subject == "house":
                v = a.get("kind")
                p["views"] = [v] if a.get("only") else list(dict.fromkeys(p.get("views", []) + [v]))
                render = True
            elif k == "storey" and subject == "house":
                p["storey"], render = a.get("which", "ground"), True
            elif k == "colors" and subject == "house":
                p.setdefault("colors", {}).update({kk: vv for kk, vv in a.items() if vv})
                if "plan3d" in p["views"] and "front" not in p["views"] and any(kk in a for kk in ("wall", "accent", "frame")):
                    p["views"] = p["views"] + ["front"]  # outside colours show from outside
                render = True
            elif k == "style" and subject == "house":
                p["style"], p["colors"], render = a.get("name", "modern"), {}, True
            elif k in ("furniture", "labels", "big") and subject in ("house", "text", "mockup"):
                p[k], render = bool(a.get("on", True)), True
            elif k == "quality" and subject:
                p["quality"], render = a.get("level", "high"), True
            elif k == "seconds" and subject in ("house", "text", "model"):
                p["seconds"], render = float(a.get("value", 6)), True
                if subject == "house" and "orbit" not in p["views"]:
                    p["views"] = p["views"] + ["orbit"]
                if subject == "model":
                    p["views"] = ["orbit"]
            elif k == "text_new":
                subject, p, render = (
                    "text",
                    {"text": a.get("text", "Hello"), "material": "gold", "background": "dark", "anim": "dolly", "seconds": 5},
                    True,
                )
            elif k == "text_style" and subject == "text":
                p.update({kk: vv for kk, vv in a.items() if vv})
                render = True
            elif k == "mockup":
                imgs = [self._file(x) for x in a.get("images") or []]
                if not all(imgs):
                    return f"I can't find {', '.join(x for x, f in zip(a.get('images') or [], imgs) if not f)}."
                subject, p, render = "mockup", {"kind": a.get("kind", "box"), "images": imgs}, True
            elif k == "mockup_image" and subject == "mockup":
                imgs = [self._file(x) for x in a.get("images") or []]
                if all(imgs):
                    p["images"], render = imgs, True
            elif k == "mockup_kind" and subject == "mockup":
                p["kind"], render = a.get("kind", p["kind"]), True
            elif k == "mockup_size" and subject == "mockup":
                p["size"], render = {"w": a.get("w"), "h": a.get("h"), "d": a.get("d")}, True
            elif k == "angle" and subject in ("mockup", "model"):
                p["turn"], render = (p.get("turn") or 0) + float(a.get("turn", 40)), True
            elif k == "model":
                f = self._file(a.get("file", ""))
                if not f:
                    return f"I can't find {a.get('file')}."
                subject, p, render = "model", {"file": f, "views": ["three_quarter"]}, True
            elif k == "model_export" and subject == "model":
                p["export"], render = a.get("fmt"), True
            elif k == "ask":
                lines.append(self.answer(a.get("what", "info")))
            elif k == "save":
                lines.append(self.export(a.get("where")))
        if render:
            lines.append(self._render(subject, p, said))
        return "\n".join(x for x in lines if x)

    def _file(self, name):
        name = str(name).strip("\"'")
        for c in (Path(name), Path(self.state["files"].get(name.lower(), name)), Path.cwd() / name):
            if c.is_file():
                return str(c.resolve())
        return None

    def _cad(self, text, new=False):
        """The plan side: a CAD chat of this 3D chat's own (made on the first house), told the brief or the change."""
        from ai_pc.cad.cadchat import CadChat

        quiet = lambda *_: None  # noqa: E731
        if new or not self.state.get("cad_chat"):
            cc = CadChat.start(chats_dir=self.folder / "cad", planner=self.planner, log=quiet)
            self.state["cad_chat"] = cc.state["id"]
            self.state["cad_dir"] = str(self.folder / "cad")
        else:
            cc = CadChat.load(self.state["cad_chat"], chats_dir=self.state.get("cad_dir") or CAD_CHATS, planner=self.planner, log=quiet)
        reply = cc.say(text)
        v = cc.cur() if hasattr(cc, "cur") else None
        plan = ((v or {}).get("files") or {}).get("plan") if v and v.get("kind") == "house" else None
        return reply, plan

    def _latest_cad_plan(self):
        best = None
        for f in CAD_CHATS.glob("*/chat.json"):
            try:
                st = json.loads(f.read_text(encoding="utf-8"))
                v = st["versions"][st["cur"]]
            except (ValueError, KeyError, IndexError):
                continue
            plan = (v.get("files") or {}).get("plan")
            if v.get("kind") == "house" and plan and Path(plan).exists():
                t = f.stat().st_mtime
                if best is None or t > best[0]:
                    best = (t, st["id"], plan)
        if best:
            self.state["cad_dir"] = str(CAD_CHATS)
            return best[1], best[2]
        return None

    def _render(self, subject, p, said):
        n = len(self.state["versions"])
        name = f"v{n}"
        try:
            if subject == "house":
                lay = json.loads(Path(p["plan"]).read_text(encoding="utf-8"))
                r = MK.house(
                    lay,
                    self.folder,
                    name,
                    views=tuple(p.get("views") or HOUSE["views"]),
                    style=p.get("style", "modern"),
                    storey=p.get("storey", "ground"),
                    furniture=p.get("furniture", True),
                    labels=p.get("labels", True),
                    quality=p.get("quality", "normal"),
                    colors=p.get("colors") or None,
                    log=self.log,
                    seconds=p.get("seconds", 6),
                    big=p.get("big", False),
                )
            elif subject == "text":
                r = MK.text(p, self.folder, name, log=self.log)
            elif subject == "mockup":
                r = MK.mockup(p, self.folder, name, log=self.log)
            elif subject == "model":
                r = MK.model(p, self.folder, name, log=self.log)
            else:
                return "Tell me what to make first."
        except (B.BlenderError, OSError, ValueError, KeyError) as e:
            return f"Couldn't make it: {e}."
        nv = {
            "v": n,
            "subject": subject,
            "params": p,
            "outputs": r["outputs"],
            "checks": r["checks"],
            "said": said,
            "parent": self.state["cur"],
            "when": _when(),
            "seconds": r["seconds"],
            "engine": r.get("engine"),
            "stats": r.get("stats"),
        }
        self.state["versions"].append(nv)
        self.state["cur"], self.state["redo"] = n, []
        self.state["subject"], self.state["params"] = subject, p
        return self._words(nv)

    def _words(self, v):
        outs = v["outputs"]
        what = {"house": "house", "text": "3D title", "mockup": f"{v['params'].get('kind')} mockup", "model": Path(v["params"].get("file", "")).name}[
            v["subject"]
        ]
        names = {
            "plan3d": "3D floor plan",
            "top": "top view",
            "front": "front view",
            "aerial": "view from above",
            "orbit": "turn-around video",
            "video": "video",
            "still": "last frame",
            "three_quarter": "picture",
            "export": "converted file",
        }
        made = ", ".join(names.get(k, k) for k in outs)
        bad = [c for c in v["checks"] if not c["ok"] and c["level"] == "fail"]
        warn = [c for c in v["checks"] if not c["ok"] and c["level"] == "warn"]
        lines = [f"v{v['v']}: {what} - {made} ({v['seconds']:.0f} s, {v.get('engine')})."]
        if v["subject"] == "house" and v["params"].get("storey") == "first" and "plan3d" in outs:
            lines[0] = lines[0].replace("3D floor plan", "3D floor plan of the first floor")
        if v["subject"] == "model" and v.get("stats"):
            s = v["stats"]
            lines.append(
                f"{s['size_m'][0] * 1000:.0f} x {s['size_m'][1] * 1000:.0f} x {s['size_m'][2] * 1000:.0f} mm, {s['triangles']:,} triangles, "
                + ("watertight (ready for 3D printing)" if s["watertight"] else f"not watertight ({s['open_edges']} open edges)")
                + "."
            )
        ok = sum(1 for c in v["checks"] if c["ok"])
        lines.append(
            f"Checked: {ok} of {len(v['checks'])} passed."
            if not bad and not warn
            else "Not right: " + "; ".join(f"{c['what']} ({c['detail']})" for c in bad + warn) + "."
        )
        lines.append("Files: " + ", ".join(Path(f).name for f in outs.values()))
        return "\n".join(lines)

    # ---------------------------------------------------------------- answers, saving
    def answer(self, what):
        v = self.cur()
        if not v:
            return "Nothing has been made yet."
        if what == "where":
            return "\n".join(f"{k}: {f}" for k, f in v["outputs"].items())
        if v["subject"] == "model" and v.get("stats"):
            s = v["stats"]
            size = f"{s['size_m'][0] * 1000:.1f} x {s['size_m'][1] * 1000:.1f} x {s['size_m'][2] * 1000:.1f} mm"
            if what == "print":
                if s["watertight"]:
                    return f"Yes: it is watertight ({size}, {s['volume_m3'] * 1e6:.1f} cm3 of material) - a slicer can print it."
                return (
                    f"Not yet: it is not watertight ({s['open_edges']} open edges, {s['many_faced_edges']} edges shared by more than two faces), "
                    f"so a slicer may fail or fill it wrongly. Close the holes first."
                )
            return f"{size}, {s['objects']} part(s), {s['vertices']:,} points, {s['triangles']:,} triangles, {s['materials']} material(s)."
        return f"v{v['v']}: {v['subject']} - " + ", ".join(Path(f).name for f in v["outputs"].values())

    def export(self, where=None):
        v = self.cur()
        if not v:
            return "Nothing has been made yet."
        from ai_pc.windows import fs as WF

        dest = WF.known(
            {
                "download": "downloads",
                "document": "documents",
                "video": "videos",
                "picture": "pictures",
                "photo": "pictures",
                "photos": "pictures",
            }.get(where, where or "pictures")
        )
        if not dest:
            return f"I don't know the folder '{where}'."
        saved = []
        for f in v["outputs"].values():
            src = Path(f)
            target = dest / src.name
            k = 2
            while target.exists():
                target = dest / f"{src.stem} ({k}){src.suffix}"
                k += 1
            shutil.copy2(src, target)
            saved.append(target)
            self.state["exports"].append({"path": str(target), "v": v["v"], "when": _when()})
        return f"Saved {len(saved)} file(s) to {dest}"

    def undo(self):
        v = self.cur()
        if not v or v["parent"] < 0:
            return "There is nothing to undo."
        self.state["redo"].append(self.state["cur"])
        self.state["cur"] = v["parent"]
        nv = self.cur()
        self.state["subject"], self.state["params"] = nv["subject"], nv["params"]
        return f"Back to v{nv['v']}: " + ", ".join(Path(f).name for f in nv["outputs"].values())

    def redo(self):
        if not self.state["redo"]:
            return "There is nothing to redo."
        self.state["cur"] = self.state["redo"].pop()
        nv = self.cur()
        self.state["subject"], self.state["params"] = nv["subject"], nv["params"]
        return f"Again v{nv['v']}: " + ", ".join(Path(f).name for f in nv["outputs"].values())

    def goto(self, n):
        if not 0 <= n < len(self.state["versions"]):
            return f"There is no v{n}."
        self.state["cur"], self.state["redo"] = n, []
        nv = self.cur()
        self.state["subject"], self.state["params"] = nv["subject"], nv["params"]
        return f"Now v{n}: " + ", ".join(Path(f).name for f in nv["outputs"].values())

    def history(self):
        if not self.state["versions"]:
            return "Nothing yet."
        return "\n".join(
            f"{'*' if v['v'] == self.state['cur'] else ' '} v{v['v']}: {v['said'][:60]} -> {', '.join(Path(f).name for f in v['outputs'].values())}"
            for v in self.state["versions"]
        )

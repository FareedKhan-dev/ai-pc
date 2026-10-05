"""A conversation that drafts: a house plan for a Pakistani plot, or an engineering part, one version per change,
every version drawn (DXF), printed (PDF, PNG) and checked.

  c = CadChat.start()
  c.say("a 5 marla house with 2 bedrooms")          -> the plan, its rooms, notes ("the lounge needs a skylight") and checks
  c.say("make it double story")  /  c.say("make the kitchen bigger")  /  c.say("can I fit 3 bedrooms?")
  c.say("export the pdf")  /  c.say("undo")  /  c.say("go back to v1")
  c.say("a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners")  /  c.say("give me the laser cut file")
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
from . import draft as DR
from . import floorplan as F
from . import parts as P
from . import render as RD
from .cadparse import parse
from .units import ft_in, marla_of

CHATS = ROOT / "out" / "cad" / "chats"
UNDO = re.compile(r"^\s*(?:undo|revert|go back|take (?:that|it) back)\b(?!.*\bv\d)", re.I)
REDO = re.compile(r"^\s*redo\b", re.I)
GOTO = re.compile(r"\b(?:go back to|back to|use|show me|switch to)\s+(?:version\s*|v)(\d+)\b", re.I)
HISTORY = re.compile(r"^\s*(?:history|versions|what (?:did you|have you) (?:do|done|change|changed))\b", re.I)
SPLIT = re.compile(r"(?<=[.!?;])\s+|,?\s+(?:and then|then|also)\s+|,?\s+and\s+(?=(?:make|add|remove|put|move|export|save|give|use|round|chamfer|change)\b)", re.I)

CAD_SYSTEM = """You turn a person's request about a drawing into changes for a drafting program. Reply with ONE JSON object:
{"ops": [...]} or {"ask": "<short question back>"}. Operations:
 {"op": "house", "brief": B, "new": true}   B = {"plot": [width_ft, depth_ft], "bedrooms": n, "floors": 1|2, "dining": bool, "store": bool,
   "powder": bool, "servant": bool, "guest": bool, "porch": bool, "drawing": bool, "porch_side": "left|right", "stair_type": "dogleg|straight",
   "facing": "north|south|east|west", "corner": bool, "furniture": bool}   (5 marla = 25x45, 10 marla = 35x65, 1 kanal = 50x90)
 {"op": "set", "brief": B}  {"op": "grow", "room": "kitchen|lounge|drawing|dining|porch|bed1|bed2|...", "by": 1 or -1}
 {"op": "size", "room": "...", "w": feet, "d": feet}  {"op": "bedrooms", "by": 1 or -1}
 {"op": "part", "spec": S, "new": true}  S = {"kind": "plate", "w": mm, "h": mm, "t": mm, "corner": {"r": mm} or {"c": mm},
   "holes": [{"d": mm, "pattern": "corners|center|row|grid", "e": mm from edges, "n": count}], "material": "ms|ss|aluminium|acrylic"}
   or {"kind": "flange", "od": mm, "id": mm, "pcd": mm, "n": holes, "hole_d": mm, "t": mm}
 {"op": "export", "fmt": "pdf|dxf|dwg|png|cut"}  {"op": "paper", "paper": "A4|A3|A2|A1"}  {"op": "scale", "scale": 100}
 {"op": "ask", "what": "area|rooms|room|fit|checks", "room": "...", "bedrooms": n}
Do only what was asked."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


class CadChat:
    def __init__(self, state, planner=None, log=print):
        self.state, self.planner, self.log = state, planner, log
        self.folder = Path(state["folder"])
        self.last_turn = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, log=print):
        cid = f"cad_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        c = cls({"id": cid, "folder": str(folder), "versions": [], "cur": -1, "redo": [], "turns": [], "exports": []}, planner=planner, log=log)
        c.save()
        return c

    @classmethod
    def load(cls, cid, chats_dir=None, planner=None, log=print):
        return cls(json.loads((Path(chats_dir or CHATS) / cid / "chat.json").read_text(encoding="utf-8")), planner=planner, log=log)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def close(self):
        pass

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
            ops = []
            kind = (self.cur() or {}).get("kind")
            for cl in [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")] or [message]:
                r = parse(cl, kind)
                if not r["ops"]:  # the rules could not read it (or could only ask back): the model may
                    r2 = self._llm(cl, message) if (self.planner is not None or not r.get("ask")) else {"ops": []}
                    r = r2 if (r2["ops"] or not r.get("ask")) else r
                if r.get("ask") and not r["ops"]:
                    out.append(r["ask"])
                    turn["intents"].append("ask")
                    ops = []
                    break
                ops += r["ops"]
                for o in r["ops"]:
                    kind = o["op"] if o["op"] in ("house", "part") else kind
            if ops:
                out.append(self._apply(ops, message))
        reply = "\n".join(x for x in out if x).strip() or "Tell me what to draw, e.g. 'a 5 marla house with 3 bedrooms' or 'a 200 x 100 x 10 plate with 4 holes of 12 mm'."
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), v_to=self.state["cur"])
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, clause, message):
        if self.planner is None:
            return {"ops": [], "ask": f"I could not read '{clause}'. Try e.g. 'a 10 marla house with 3 bedrooms', 'make the kitchen bigger', 'export the pdf'."}
        self._turn["llm"] = True
        cur = self.cur()
        user = f"NOW DRAWING: {json.dumps(cur['spec']) if cur else 'nothing yet'} ({cur['kind'] if cur else '-'})\nMESSAGE: {message}\nREQUEST: {clause}"
        try:
            r = self.planner._call("fast", [{"role": "system", "content": CAD_SYSTEM}, {"role": "user", "content": user}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op") in ("house", "set", "grow", "size", "bedrooms", "part", "export", "paper",
                                                                                       "scale", "ask")]
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- doing
    def _apply(self, ops, said):
        cur = self.cur()
        kind = cur["kind"] if cur else None
        spec = json.loads(json.dumps(cur["spec"])) if cur else None
        sheet = dict(cur.get("sheet_opts") or {}) if cur else {}
        lines, changed, asks, exports = [], False, [], []
        lay = None  # a house layout already planned for the spec as it now stands
        for op in ops:
            k = op["op"]
            self._turn["intents"].append(k)
            if k == "house":
                if op.get("new") or kind != "house":
                    spec, kind, sheet = dict(op["brief"]), "house", {}
                    cur = None  # a new plan: nothing to compare it with
                else:
                    spec.update(op["brief"])
                changed, lay = True, None
            elif k in ("set", "grow", "size", "bedrooms"):
                if kind != "house":
                    lines.append("Start a plan first, e.g. 'a 5 marla house with 2 bedrooms'.")
                    continue
                if k == "set":
                    spec.update(op["brief"])
                    lay = None
                elif k == "grow":  # searched: the biggest step that keeps every door and size rule
                    base = _house_info(lay or F.plan(spec)) if (changed or cur is None) else cur["info"]
                    s2, lay2, why = self._grow(spec, op["room"], op["by"], base)
                    if s2 is None:
                        lines.append(why)
                        continue
                    spec, lay = s2, lay2
                elif k == "size":  # an exact size replaces any 'bigger' or 'smaller' asked before
                    sz = dict(spec.get("sizes") or {})
                    sz[op["room"]] = [op["w"], op["d"]]
                    spec["sizes"] = sz
                    for lk in ("min", "max"):
                        if (spec.get(lk) or {}).get(op["room"]):
                            spec[lk] = {r: v for r, v in spec[lk].items() if r != op["room"]}
                    lay = None
                else:
                    spec["bedrooms"] = max(1, int(spec.get("bedrooms", 2)) + op["by"])
                    lay = None
                changed = True
            elif k == "part":
                ps = op["spec"]
                if op.get("new") or kind != "part" or ps.get("kind") and ps.get("kind") != (spec or {}).get("kind"):
                    spec, kind, sheet = _part_defaults(ps), "part", {}
                else:
                    _part_edit(spec, ps)
                changed = True
            elif k == "paper":
                sheet["paper"] = op["paper"]
                changed = changed or kind is not None
            elif k == "scale":
                sheet["scale"] = op["scale"]
                changed = changed or kind is not None
            elif k == "export":
                exports.append(op)
            elif k == "ask":
                asks.append(op)
        if changed and spec is not None:
            try:
                if kind == "house" and lay is None:
                    lay = F.plan(spec)
                no = self._vet(lay, spec, sheet, cur, ops) if kind == "house" else None
                if no:
                    lines.append(no)
                else:
                    v = self._build(kind, spec, sheet, said, lay)
                    lines.append(self._words(v, cur))
            except (F.PlanError, P.PartError, ValueError, KeyError) as e:
                sized = [o for o in ops if o["op"] == "size"]
                if sized and isinstance(e, F.PlanError):
                    o = sized[-1]
                    lines.append(f"{o['room'].replace('bed', 'Bed Room ').title() if o['room'].startswith('bed') else o['room'].title()} can't be "
                                 f"{o['w']:g}' x {o['d']:g}' on this plot: the rooms beside it are already at their smallest. The plan stays as it is.")
                else:
                    lines.append(f"Couldn't draw that: {e}.")
        for a in asks:
            lines.append(self.answer(a))
        for e in exports:
            lines.append(self.export(e.get("fmt", "pdf"), e.get("paper")))
        return "\n".join(x for x in lines if x)

    def _vet(self, lay, spec, sheet, cur, ops=()):
        """None when the planned layout may become the next version; else why not (it changes nothing, or it breaks
        what the current plan gets right: a room loses its door, a room falls under its minimum)."""
        if cur is None or cur["kind"] != "house":
            return None
        new = _house_info(lay)
        dropped = [d for d in lay.get("dropped", []) if (spec.get(d) and not cur["spec"].get(d)) or d not in cur["info"].get("dropped", [])]
        same_sheet = sheet == (cur.get("sheet_opts") or {}) and all(spec.get(k) == cur["spec"].get(k) for k in ("name", "client", "facing", "furniture"))
        if new["sig"] == cur["info"].get("sig") and same_sheet:
            return ((new["notes"][0][0].upper() + new["notes"][0][1:] + ". ") if dropped else "") + f"The plan stays as v{cur['v']}."
        old_ids, new_ids = set(cur["info"]["rects"]["ground"]), set(new["rects"]["ground"])
        meant = {k for k in ("porch", "drawing", "dining", "store", "powder", "servant", "guest") if cur["spec"].get(k, k in ("porch", "drawing")) and not spec.get(k, True)}
        meant |= {i for i in old_ids if i.startswith("bed") and i[3:].isdigit() and int(i[3:]) > int(spec.get("bedrooms", 2))}
        lost = [cur["info"]["labels"].get(i, i).title() for i in sorted(old_ids - new_ids - meant) if i != "passage"]
        if lost:  # never a room the person did not ask to lose
            sized = [o for o in ops if o["op"] == "size"]
            if sized:
                o = sized[-1]
                return (f"{_room_words(o['room'])} can't be {o['w']:g}' x {o['d']:g}' on this plot without losing {', '.join(lost)}. "
                        f"The plan stays as v{cur['v']}.")
            return f"That would leave no room for {', '.join(lost)}, so I kept v{cur['v']}."
        was_ok = not any(c for c in cur["checks"] if not c["ok"] and c["level"] == "fail")
        bad = [c["what"] for c in CK.design(lay) if not c["ok"] and c["level"] == "fail"]
        if was_ok and bad:
            return f"That would break the plan ({_why(bad[0], lay)}), so I kept v{cur['v']}."
        return None

    def _grow(self, spec, room, by, info):
        """'Make the kitchen bigger': a foot (two for 'much') wider or deeper, else six inches, whichever keeps every
        door and minimum and leaves the best plan; smaller works the same way. Returns (spec, layout, None) or (None, None, why)."""
        rects = info["rects"]["ground"]
        ids = _ids_for(room, info)
        if not ids:
            return None, None, f"There is no {room.replace('bed', 'bedroom ')} in this plan" + (f"; say 'add a {room}'" if room in ("dining", "store", "powder", "servant", "guest") else "") + "."
        if "stairs" in ids:
            return None, None, "The stairs are sized by their flights (a dog-leg 6'-6\" x 10', a straight flight 3'-6\" x 12'-6\"); say 'straight stairs' or 'dog-leg stairs'."
        key = "bedroom" if room == "bedroom" and len(ids) > 1 else ids[0]
        label = "bedrooms" if key == "bedroom" else info["labels"][ids[0]].lower()
        lim_key, other, sign = ("min", "max", 1) if by > 0 else ("max", "min", -1)
        base = [min(rects[i][2] - rects[i][0] for i in ids), min(rects[i][3] - rects[i][1] for i in ids)]
        why, found = {}, []
        for step in ((24, 12, 6) if abs(by) > 1 else (12, 6)):
            for ax in (0, 1):
                s2 = json.loads(json.dumps(spec))
                lim = dict(s2.get(lim_key) or {})
                lv = list(lim.get(key) or [None, None])
                lv[ax] = round((base[ax] + sign * step) / 12, 3)
                lim[key] = lv
                s2[lim_key] = lim
                if (s2.get(other) or {}).get(key):  # an older cap (or floor) on that side gives way
                    ol = list(s2[other][key])
                    ol[ax] = None
                    s2[other] = {**s2[other], key: ol}
                if (s2.get("sizes") or {}).get(key):
                    s2["sizes"] = {k: v for k, v in s2["sizes"].items() if k != key}
                try:
                    lay = F.plan(s2, budget_s=1.5)
                except F.PlanError:
                    why[ax] = "the rooms around it are already at their smallest"
                    continue
                got = _house_info(lay)
                gone = [info["labels"][i].lower() for i in rects if i not in got["rects"]["ground"]]
                bad = [c["what"] for c in CK.design(lay) if not c["ok"] and c["level"] == "fail"]
                g = got["rects"]["ground"]
                gain = sign * (min(g[i][2 + ax] - g[i][ax] for i in ids if i in g) - base[ax]) if all(i in g for i in ids) else 0
                if gone:
                    why[ax] = f"the {', '.join(gone)} would no longer fit"
                elif bad:
                    why[ax] = _why(bad[0], lay)
                elif gain < 3:
                    why[ax] = "nothing around it can give way"
                else:
                    moved = sum(abs((g[i][2] - g[i][0]) - (rects[i][2] - rects[i][0])) + abs((g[i][3] - g[i][1]) - (rects[i][3] - rects[i][1]))
                                for i in rects if i in g and i not in ids) / 12  # feet the other rooms change by
                    found.append((lay["score"] + 0.5 * moved, -gain, ax, s2, lay))
            if found:
                break
        if not found:
            w = "bigger" if by > 0 else "smaller"
            return None, None, (f"The {label} can't get {w} on this plot: in width, {why.get(0, 'no change')}; in depth, {why.get(1, 'no change')}. "
                                f"The plan stays as it is.")
        _, _, _, s2, lay = min(found, key=lambda f: (round(f[0], 1), f[1]))
        return s2, lay, None

    def _build(self, kind, spec, sheet, said, lay=None):
        n = len(self.state["versions"])
        stem = self.folder / f"v{n}"
        t0 = time.perf_counter()
        if kind == "house":
            lay = lay or F.plan(spec)
            doc, sh = DR.drawing(lay, sheet.get("paper"), sheet.get("scale"), spec.get("name"), spec.get("client"))
            doc.saveas(stem.with_suffix(".dxf"))
            files = RD.render(doc, sh, stem)
            checks = CK.check(stem.with_suffix(".dxf"), lay, files, sh)
            info = dict(_house_info(lay), scale=sh["scale"], paper=sh["paper"])
            files["plan"] = str(stem.with_suffix(".plan.json"))  # the exact layout (the search can differ run to run), for the 3D lane
            Path(files["plan"]).write_text(json.dumps(lay, default=str), encoding="utf-8")
        else:
            doc, sh = P.part_drawing(spec, sheet.get("paper"))
            doc.saveas(stem.with_suffix(".dxf"))
            P.cut_file(spec).saveas(stem.with_name(stem.name + "_cut.dxf"))
            files = RD.render(doc, sh, stem)
            checks = P.part_checks(spec) + _part_file_checks(stem.with_suffix(".dxf"), spec)
            info = {"scale": "%d:%d" % sh["scale_ratio"], "paper": sh["paper"], "holes": len(P.holes_of(spec))}
        files["dxf"] = str(stem.with_suffix(".dxf"))
        if kind == "part":
            files["cut"] = str(stem.with_name(stem.name + "_cut.dxf"))
        v = {"v": n, "kind": kind, "spec": spec, "sheet_opts": sheet, "said": said, "files": files, "checks": checks, "info": info, "when": _when(),
             "seconds": round(time.perf_counter() - t0, 2), "parent": self.state["cur"]}
        self.state["versions"].append(v)
        self.state["cur"] = n
        self.state["redo"] = []
        return v

    def _words(self, v, before):
        info, checks = v["info"], v["checks"]
        ck = CK.text_of(checks)
        if v["kind"] == "part":
            s = v["spec"]
            what = (f"{s['w']:g} x {s['h']:g} x {s['t']:g} mm plate" if s["kind"] == "plate" else
                    f"flange OD {s['od']:g}, bore {s['id']:g}, {s['n']} x Ø{s['hole_d']:g} on {s['pcd']:g} PCD, {s['t']:g} thick")
            return (f"v{v['v']}: {what}, {info['holes']} hole(s), scale {info['scale']} on {info['paper']}. Files: {Path(v['files']['dxf']).name} (drawing), "
                    f"{Path(v['files']['cut']).name} (1:1 cut file for a laser), {Path(v['files']['pdf']).name}. ({ck})")
        W, D = info["plot"]
        rooms = info["summary"]["rooms"]
        head = (f"v{v['v']}: {'ground and first floor plans' if info['floors'] > 1 else 'ground floor plan'} for a {W:g}' x {D:g}' plot "
                f"({marla_of(W, D):.1f} marla), 1:{info['scale']} on {info['paper']}. Covered {info['summary']['covered_sqft']:,} sq ft"
                + (f" + {info['upper']['covered_sqft']:,} upstairs" if info.get("upper") else "") + ".")
        if before and before["kind"] == "house":
            old = {r["id"]: r for r in before["info"]["summary"]["rooms"]}
            new = {r["id"]: r for r in rooms}
            diffs = [f"{r['label'].title()} {old[i]['size']} -> {r['size']}" for i, r in new.items() if i in old and old[i]["size"] != r["size"]]
            added = [r["label"].title() for i, r in new.items() if i not in old]
            gone = [old[i]["label"].title() for i in old if i not in new]
            change = "; ".join(([f"added {', '.join(added)}"] if added else []) + ([f"removed {', '.join(gone)}"] if gone else []) + diffs[:6]
                               + ([f"{len(diffs) - 6} more"] if len(diffs) > 6 else []))
            if info.get("upper") and not before["info"].get("upper"):
                ups = [r["label"].title() for r in info["upper"]["rooms"] if not r["label"].startswith("BATH") and r["id"] != "stairs"]
                change = "; ".join(x for x in (change, f"first floor added: {', '.join(ups)}") if x)
            elif before["info"].get("upper") and not info.get("upper"):
                change = "; ".join(x for x in (change, "first floor removed") if x)
            body = f"Changed: {change}." if change else "No room changed size."
        else:
            body = "Rooms: " + "; ".join(f"{r['label'].title()} {r['size']}" for r in rooms if not r["label"].startswith("BATH")) + \
                f"; {sum(1 for r in rooms if r['label'].startswith('BATH'))} attached bath(s)."
        notes = ("Notes: " + "; ".join(info["notes"][:4]) + ".") if info["notes"] else ""
        return f"{head} {body} {notes} Files: {Path(v['files']['dxf']).name} (AutoCAD), {Path(v['files']['pdf']).name}, {Path(v['files']['png']).name}. ({ck})"

    # ---------------------------------------------------------------- answers
    def answer(self, a):
        v = self.cur()
        if v is None:
            return "Nothing is drawn yet."
        w = a["what"]
        if w == "checks":
            bad = [c for c in v["checks"] if not c["ok"]]
            return ("All checks pass: " + CK.text_of(v["checks"]) + "." if not bad else "To look at: " + "; ".join(c["what"] for c in bad) + ".") + \
                (" Notes: " + "; ".join(v["info"].get("notes", [])) + "." if v["info"].get("notes") else "")
        if v["kind"] != "house":
            return "That question is for house plans."
        info = v["info"]
        if w == "area":
            W, D = info["plot"]
            cov = info["summary"]["covered_sqft"] + (info["upper"]["covered_sqft"] if info.get("upper") else 0)
            return (f"Plot {W:g}' x {D:g}' = {W * D:,.0f} sq ft ({marla_of(W, D):.1f} marla of 225 sq ft). Covered {cov:,} sq ft"
                    + (f" on 2 floors ({info['summary']['covered_sqft']:,} on the ground floor, {info['summary']['covered_sqft'] / (W * D):.0%} of the plot)." if info.get("upper")
                       else f" ({info['summary']['covered_sqft'] / (W * D):.0%} of the plot)."))
        if w == "rooms":
            parts = [f"{r['label'].title()} {r['size']} ({r['area_sqft']:.0f} sq ft)" for r in info["summary"]["rooms"]]
            up = [f"{r['label'].title()} {r['size']}" for r in (info.get("upper") or {}).get("rooms", [])]
            return "Ground floor: " + "; ".join(parts) + "." + (" First floor: " + "; ".join(up) + "." if up else "")
        if w == "room":
            rid = a.get("room")
            hits = [r for r in info["summary"]["rooms"] if r["id"] == rid or r["id"].startswith(rid or "~") or (rid == "bedroom" and r["id"].startswith("bed") and "_" not in r["id"])]
            if not hits:
                return f"There is no {rid} in this plan."
            return "; ".join(f"{r['label'].title()}: {r['size']} clear, {r['area_sqft']:.0f} sq ft" for r in hits) + "."
        if w == "fit":
            n = a["bedrooms"]
            W = v["info"]["plot"][0]

            def beds(lay):
                down = sum(1 for r in lay["rooms"] if r["kind"] == "bedroom")
                return down, (sum(1 for r in lay["upper"]["rooms"] if r["kind"] == "bedroom") if lay.get("upper") else 0)
            try:
                lay = F.plan(dict(v["spec"], bedrooms=n), budget_s=1.5)
                down, up = beds(lay)
            except F.PlanError:
                lay, down, up = {"rooms": []}, 0, 0
            ok = bool(lay["rooms"]) and not F.unreachable(lay)
            if down >= n and ok:
                return f"Yes: {n} bedrooms fit on the ground floor (say '{n} bedrooms' to draw it)."
            if down + up >= n and ok:
                return f"Yes, with the first floor: {down} downstairs and {up} upstairs (say '{n} bedrooms' to draw it)."
            try:
                two = F.plan(dict(v["spec"], bedrooms=n, floors=2), budget_s=1.5)
                d2, u2 = beds(two)
            except F.PlanError:
                d2 = u2 = 0
            return (f"Not on one floor: only {down} bedroom(s) with baths fit on the ground floor of a {W:g}' x {v['info']['plot'][1]:g}' plot." +
                    (f" Double story gives {d2 + u2} ({d2} down, {u2} up): say 'make it double story'." if d2 + u2 >= n else ""))
        return ""

    def export(self, fmt="pdf", paper=None):
        v = self.cur()
        if v is None:
            return "Nothing is drawn yet."
        if paper and paper != v["info"].get("paper"):
            return self._apply([{"op": "paper", "paper": paper}, {"op": "export", "fmt": fmt}], f"on {paper}")
        out_dir = self.folder / "exports"
        out_dir.mkdir(exist_ok=True)
        if fmt == "dwg":
            return ("A DWG needs the free ODA File Converter (a separate install I have not set up here). AutoCAD, BricsCAD and DraftSight open "
                    "the DXF directly: " + self.export("dxf"))
        if fmt == "cut" and v["kind"] != "part":
            return "A cut file is for parts (plates, flanges); for a plan, the DXF is the CAD file: " + self.export("dxf")
        src = Path(v["files"]["cut" if fmt == "cut" else fmt])
        if v["kind"] == "house":
            W, D = v["info"]["plot"]
            name = f"{v['spec'].get('name') or 'House'} {W:g}x{D:g} plan v{v['v']}" + src.suffix
        else:
            s = v["spec"]
            name = f"{s.get('name') or s['kind'].title()} v{v['v']}" + ("_cut" if fmt == "cut" else "") + src.suffix
        dst = out_dir / re.sub(r'[<>:"/\\|?*]+', "-", name)
        shutil.copy2(src, dst)
        self.state["exports"].append({"path": str(dst), "v": v["v"], "fmt": fmt})
        extra = {"pdf": f" ({v['info']['paper']}, true to scale)", "dxf": " (opens in AutoCAD, BricsCAD, LibreCAD, DraftSight)", "cut": " (outline and holes only, 1:1 mm, layer CUT)",
                 "png": ""}.get(fmt, "")
        return f"Saved {dst}{extra}."

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
        return "\n".join(f"v{v['v']} {v['kind']}: '{v['said'][:60]}'" + (" <- now" if v["v"] == self.state["cur"] else "") for v in self.state["versions"]) or "Nothing yet."


def _house_info(lay):
    """What a version keeps of its layout: room sizes, rectangles and labels on each floor, notes, and a signature to
    tell an unchanged plan."""
    floors = {"ground": lay} | ({"upper": lay["upper"]} if lay.get("upper") else {})
    rects = {k: {r["id"]: [r["x0"], r["y0"], r["x1"], r["y1"]] for r in fl["rooms"]} for k, fl in floors.items()}
    labels = {}
    for fl in reversed(list(floors.values())):
        labels.update({r["id"]: r["label"] for r in fl["rooms"]})
    sig = json.dumps({k: sorted((i, [round(x, 1) for x in v]) for i, v in r.items()) for k, r in rects.items()})
    return {"summary": F.summary(lay), "upper": F.summary(lay["upper"]) if lay.get("upper") else None,
            "notes": lay["notes"] + (lay["upper"]["notes"] if lay.get("upper") else []), "plot": [v / 12 for v in lay["plot"]],
            "floors": 2 if lay.get("upper") else 1, "rects": rects, "labels": labels, "sig": sig, "dropped": lay.get("dropped", [])}


def _ids_for(room, info):
    """The ground-floor rooms a word means: 'kitchen', 'bed2', every bedroom for 'bedroom', and for a first-floor
    room the room under it (the floors share their walls)."""
    g, up = info["rects"]["ground"], info["rects"].get("upper", {})
    if room == "bedroom":
        return [i for i in g if i.startswith("bed") and "_" not in i]
    if room in g:
        return [room]
    if room in up:
        return [i for i, r in g.items() if all(abs(a - b) < 0.6 for a, b in zip(r, up[room]))][:1]
    return []


def _room_words(rid):
    """'bed2' -> 'Bed Room 2', 'kitchen' -> 'The kitchen'."""
    return f"Bed Room {rid[3:]}" if rid.startswith("bed") and rid[3:].isdigit() else f"The {rid}"


def _why(what, lay):
    """A failed design check in words: 'BED ROOM 1 would lose its door'."""
    m = re.search(r"\(not: (.+)\)", what)
    if m and "reached" in what:
        labels = {r["id"]: r["label"] for fl in ([lay] + ([lay["upper"]] if lay.get("upper") else [])) for r in fl["rooms"]}
        names = [labels.get(i, i).title() for i in m.group(1).split(", ") if not i.endswith("_bath")]
        return f"{', '.join(dict.fromkeys(names))} would lose {'its door' if len(set(names)) == 1 else 'their doors'}"
    return what


def _part_defaults(ps):
    s = dict(ps)
    s.pop("new", None)
    if s.get("kind") == "flange":
        od = s.get("od", 150.0)
        s.setdefault("od", od)
        s.setdefault("id", round(od * 0.4))
        s.setdefault("pcd", round((s["od"] + s["id"]) / 2))
        s.setdefault("n", 4)
        s.setdefault("hole_d", max(8.0, round((s["od"] - s["id"]) / 2 * 0.3)))
        s.setdefault("t", 10.0)
    else:
        s["kind"] = "plate"
        s.setdefault("w", 200.0)
        s.setdefault("h", 100.0)
        s.setdefault("t", 6.0)
        s.setdefault("holes", [])
    s.setdefault("material", "ms")
    for k in ("hole_size", "hole_edge", "drop_center"):
        s.pop(k, None)
    return s


def _part_edit(spec, ps):
    """A change to the part in place: hole sizes or edge distance, a centre hole added or taken out, corners, size."""
    if ps.get("hole_size"):
        if spec["kind"] == "flange":
            spec["hole_d"] = ps["hole_size"]
        else:
            for h in spec.get("holes", []):
                if h.get("pattern") != "center":
                    h["d"] = ps["hole_size"]
    if ps.get("hole_edge"):
        for h in spec.get("holes", []):
            if h.get("pattern") in ("corners", "row", "grid"):
                h["e"] = ps["hole_edge"]
    if ps.get("drop_center"):
        spec["holes"] = [h for h in spec.get("holes", []) if h.get("pattern") != "center"]
    if ps.get("hole_count"):  # '6 holes': a flange's bolt holes; a plate's main set (two rows along the long sides when even)
        n = int(ps["hole_count"])
        if spec["kind"] == "flange":
            spec["n"] = n
        else:
            main = next((h for h in spec.get("holes", []) if h.get("pattern") != "center"), None)
            if main is None:
                main = {"d": ps.get("hole_size") or 10.0, "e": 20.0}
                spec.setdefault("holes", []).append(main)
            e = main.get("e", max(main["d"] * 1.5, 10))
            main.pop("n", None), main.pop("nx", None), main.pop("ny", None)
            if n == 4:
                main.update(pattern="corners", e=e)
            elif n % 2 == 0 and n > 4:
                long_x = spec["w"] >= spec["h"]
                main.update(pattern="grid", e=e, nx=n // 2 if long_x else 2, ny=2 if long_x else n // 2)
            else:
                main.update(pattern="row", e=e, n=n)
    if ps.get("holes"):
        spec.setdefault("holes", [])
        spec["holes"] += ps["holes"]
    for k in ("w", "h", "t", "material", "od", "id", "pcd", "n", "hole_d", "name"):
        if k in ps:
            spec[k] = ps[k]
    if "corner" in ps:
        spec["corner"] = ps["corner"]


def _part_file_checks(path, spec):
    """The part's DXF read back: it audits clean and holds every hole."""
    import ezdxf
    doc = ezdxf.readfile(str(path))
    aud = doc.audit()
    circles = len(doc.modelspace().query("CIRCLE[layer=='CUT']"))
    want = len(P.holes_of(spec)) + (2 if spec["kind"] == "flange" else 0)
    return [{"ok": not aud.has_errors, "what": "the DXF opens and audits clean", "level": "fail"},
            {"ok": circles == want, "what": f"{circles} circle(s) drawn for {want} hole(s) and bore", "level": "fail"}]

"""What a person says about a drawing, read by rules into changes (the cheap model reads the rest into the same).

House plans: "a 5 marla house with 3 bedrooms", "10 marla double story with dining and a store", "30x60 plot, porch on
the right, north facing", "make the kitchen bigger", "make bedroom 2 12 by 14", "add a store", "remove the drawing
room", "straight stairs", "what is the covered area?", "can I fit 4 bedrooms?".
Parts: "a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners and a 30 mm hole in the centre",
"flange OD 150 ID 60, 6 holes of 14 on a 110 PCD, 12 thick", "make the holes 14", "round the corners 10".
Saving: "export the pdf", "give me the dxf", "dwg", "a cut file for the laser", "on A2", "scale 1:50".
"""
import math
import re

from ai_pc.cad.units import WORDS, plot_of

ROOM_WORDS = [(r"\bkitchen\b", "kitchen"), (r"\b(?:tv |family )?lounge\b|\bliving(?: room)?\b|\bsitting(?: room)?\b", "lounge"),
              (r"\bdrawing(?: room)?\b|\bguest sitting\b", "drawing"), (r"\bdining(?: room| area)?\b", "dining"), (r"\b(?:car )?porch\b|\bgarage\b", "porch"),
              (r"\bstore(?: room)?\b", "store"), (r"\bpowder(?: room)?\b|\bguest (?:toilet|washroom|bath)\b", "powder"), (r"\bservant(?:s)?(?: room| quarter)?\b", "servant"),
              (r"\bguest room\b|\bguest bed ?room\b", "guest"), (r"\bstairs?\b|\bstaircase\b", "stairs")]


def _num(s):
    s = str(s).lower()
    return float(s) if re.fullmatch(r"\d+(?:\.\d+)?", s) else WORDS.get(s)


def room_in(c):
    m = re.search(r"\b(?:bed ?room|bedroom|room)\s*(?:no\.?\s*)?(\d+|one|two|three|four|five|six)\b|\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\s+bed ?room\b", c)
    if m:
        n = m.group(1) or m.group(2)
        n = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}.get(n) or int(_num(n))
        return f"bed{n}"
    if re.search(r"\bmaster bed ?room\b", c):
        return "bed1"
    for rx, kind in ROOM_WORDS:
        if re.search(rx, c):
            return kind
    if re.search(r"\bbed ?rooms?\b", c):
        return "bedroom"
    return None


def _feet(v, unit):
    return v * 3.28084 if unit and unit.startswith(("m", "meter", "metre")) and unit != "mm" else v


def house_brief(c):
    """The parts of a house brief a clause gives: {"plot", "bedrooms", "floors", rooms on/off, ...}."""
    b = {}
    m = re.search(r"\b(\d+(?:\.\d+)?|one|two|half)\s*kanal\b", c)
    if m:
        b["plot"] = list(plot_of(_num(m.group(1)), "kanal"))
    m = re.search(r"\b(\d+(?:\.\d+)?|three|four|five|six|seven|eight|ten|twelve|fourteen|sixteen|twenty)\s*marla\b", c)
    if m and "plot" not in b:
        b["plot"] = list(plot_of(_num(m.group(1))))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:'|ft|feet)?\s*(?:x|by|\*|×)\s*(\d+(?:\.\d+)?)\s*(ft|feet|foot|'|m|meters?|metres?)?(?!\s*(?:mm|x))", c)
    if m and not re.search(r"\bplate|flange|mm\b", c):
        unit = m.group(3) or ""
        w, d = _feet(float(m.group(1)), unit), _feet(float(m.group(2)), unit)
        if w >= 15 and d >= 25 and not room_in(c[:m.start()]):
            b["plot"] = [round(min(w, d), 1), round(max(w, d), 1)]  # the road side is usually the narrow one
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot)\s*(?:wide|width|front(?:age)?)\b.{0,12}?\b(\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot)\s*(?:deep|long|depth|length)\b", c)
    if m and "plot" not in b:  # '40 feet wide and 80 feet deep'
        b["plot"] = [float(m.group(1)), float(m.group(2))]
    m = re.search(r"\b(\d+|one|two|three|four|five|six)\s*(?:bed ?rooms?|beds?|bhk|bedroom|kamr[ae]y?|kamron|bed ?room wala)\b", c)
    if m:
        b["bedrooms"] = int(_num(m.group(1)))
    m = re.search(r"\bfamily of (\d+|three|four|five|six|seven|eight|nine|ten)\b", c)
    if m and "bedrooms" not in b:  # the parents share a room, the children two to a room
        b["bedrooms"] = max(2, 1 + math.ceil((int(_num(m.group(1))) - 2) / 2))
    if re.search(r"\bdouble[ -]stor(?:e)?y\b|\b(?:2|two)[ -]stor(?:e)?y\b|\b(?:with|add)(?: a)? first floor\b|\bg ?\+ ?1\b|\bground (?:\+|and|plus) first\b|\bupper floor\b", c):
        b["floors"] = 2
    if re.search(r"\bsingle[ -]stor(?:e)?y\b|\b(?:1|one)[ -]stor(?:e)?y\b|\bground floor only\b|\bno first floor\b|\bremove the first floor\b", c):
        b["floors"] = 1
    for rx, key in ((r"\bdining\b", "dining"), (r"\bstore\b", "store"), (r"\bpowder\b|\bguest (?:toilet|washroom|bath)\b", "powder"),
                    (r"\bservant", "servant"), (r"\bguest room\b|\bguest bed ?room\b", "guest")):
        if re.search(rx, c):
            neg = re.search(r"\b(?:no|without|remove|delete|drop|take out|get rid of)\b[^,.]*" + rx, c)
            b[key] = not neg
    if re.search(r"\b(?:no|without|remove|delete|drop)\b[^,.]*\b(?:car )?porch\b|\bno garage\b", c):
        b["porch"] = False
    elif re.search(r"\bwith (?:a )?(?:car )?porch\b|\badd (?:a )?(?:car )?porch\b", c):
        b["porch"] = True
    if re.search(r"\b(?:no|without|remove|delete|drop)\b[^,.]*\bdrawing(?: room)?\b", c):
        b["drawing"] = False
    m = re.search(r"\bporch (?:on|to) the (left|right)\b|\b(left|right)[ -]side porch\b", c)
    if m:
        b["porch_side"] = m.group(1) or m.group(2)
    if re.search(r"\bstraight (?:stairs?|staircase)\b|\bsingle flight\b", c):
        b["stair_type"] = "straight"
    elif re.search(r"\bdog[ -]?leg\b|\bu[ -]shaped stairs?\b|\btwo flights?\b", c):
        b["stair_type"] = "dogleg"
    m = re.search(r"\b(north|south|east|west)[ -]facing\b|\bfacing (north|south|east|west)\b|\broad (?:on|to) the (north|south|east|west)\b", c)
    if m:
        b["facing"] = m.group(1) or m.group(2) or m.group(3)
    if re.search(r"\bcorner (?:plot|house)\b", c):
        b["corner"] = True
    if re.search(r"\b(?:no|without) furniture\b|\bempty\b|\bremove (?:the )?furniture\b", c):
        b["furniture"] = False
    elif re.search(r"\bwith furniture\b|\badd (?:the )?furniture\b|\bfurnish", c):
        b["furniture"] = True
    return b


OD_RX = r"od|outer(?: dia(?:meter)?)?|outside dia(?:meter)?"
ID_RX = r"id|bore|inner(?: dia(?:meter)?)?|inside dia(?:meter)?"


def _labelled(c, rx):
    """The number after a label ('od 150') and the number before it ('150 od')."""
    a = re.search(rf"\b(?:{rx})\s*(?:of\s*|=\s*|:\s*)?(\d+(?:\.\d+)?)", c)
    b = re.search(rf"(\d+(?:\.\d+)?)\s*(?:mm\s*)?(?:{rx})\b", c)
    return (float(a.group(1)) if a else None), (float(b.group(1)) if b else None)


def part_spec(c):
    """A plate or flange from the words."""
    s = {}
    od_a, od_b = _labelled(c, OD_RX)
    if re.search(r"\bflange\b|\bpcd\b|\bbolt circle\b", c) or od_a or od_b:
        s["kind"] = "flange"
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm\s*)?pcd\b|\bpcd\s*(?:of\s*)?(\d+(?:\.\d+)?)|bolt circle (?:of )?(\d+(?:\.\d+)?)", c)
        pcd = float(next(g for g in m.groups() if g)) if m else None
        if pcd:
            s["pcd"] = pcd
        id_a, id_b = _labelled(c, ID_RX)

        def fits(od, bore):  # '150 od 60 bore' and 'od 150 bore 60' both read right: the pairing where bore < pcd < od
            return not ((od and bore and bore >= od) or (pcd and od and pcd >= od) or (pcd and bore and bore >= pcd))
        pairs = [(od_a, id_a), (od_b, id_b), (od_a, id_b), (od_b, id_a)]
        od, bore = max((p for p in pairs if fits(*p)), key=lambda p: (p[0] is not None) + (p[1] is not None), default=(None, None))
        if od:
            s["od"] = od
        if bore:
            s["id"] = bore
        m = re.search(r"\b(\d+|four|six|eight|three|five|ten|twelve)\s*(?:x\s*)?(?:bolt )?holes?\s*(?:of\s*)?(?:ø|dia(?:meter)?\s*)?(\d+(?:\.\d+)?)?", c)
        if m:
            s["n"] = int(_num(m.group(1)))
            if m.group(2):
                s["hole_d"] = float(m.group(2))
    else:
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:x|by|×)\s*(\d+(?:\.\d+)?)\s*(?:mm)?(?:\s*(?:x|by|×)\s*(\d+(?:\.\d+)?))?", c)
        if m and re.search(r"\bplate|\bbracket|\bpart|\bsheet|\bpanel|\bmm\b|\blaser|\bcnc", c):
            s.update(kind="plate", w=float(m.group(1)), h=float(m.group(2)))
            if m.group(3):
                s["t"] = float(m.group(3))
        holes = []
        m = re.search(r"\b(\d+|two|three|four|six|eight)\s*holes?\s*(?:of\s*)?(?:ø|dia(?:meter)?\s*)?(\d+(?:\.\d+)?)?\s*(?:mm)?(?:[^,.]*?(\d+(?:\.\d+)?)\s*(?:mm)?\s*from (?:the )?(?:corners?|edges?|sides?))?", c)
        if m:
            n = int(_num(m.group(1)))
            h = {"d": float(m.group(2)) if m.group(2) else 10.0, "pattern": "corners" if n == 4 else "row", "n": n}
            if m.group(3):
                h["e"] = float(m.group(3))
            holes.append(h)
        m = re.search(r"\b(?:a|one)?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:dia(?:meter)?\s*)?hole (?:in|at) the (?:cent(?:re|er)|middle)\b|\b(?:cent(?:re|er)|middle) hole (?:of\s*)?(\d+(?:\.\d+)?)", c)
        if m:
            holes.append({"d": float(m.group(1) or m.group(2)), "pattern": "center"})
        if holes:
            s["holes"] = holes
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mm)?\s*thick\b|\bthick(?:ness)?\s*(?:of\s*)?(\d+(?:\.\d+)?)", c)
    if m:
        s["t"] = float(m.group(1) or m.group(2))
    m = re.search(r"\b(?:round(?:ed)? (?:the )?corners?|corner radius|radius|r)\s*(?:of\s*)?(\d+(?:\.\d+)?)\b", c)
    if m:
        s["corner"] = {"r": float(m.group(1))}
    m = re.search(r"\bchamfer(?:ed)?(?: (?:the )?corners?)?\s*(?:of\s*)?(\d+(?:\.\d+)?)", c)
    if m:
        s["corner"] = {"c": float(m.group(1))}
    if re.search(r"\b(?:square|sharp|no (?:radius|chamfer)) corners?\b|\bremove the (?:radius|chamfer)\b", c):
        s["corner"] = None
    m = re.search(r"\b(mild steel|ms|stainless(?: steel)?|ss|steel|aluminium|aluminum|brass|acrylic|mdf|wood)\b", c)
    if m:
        s["material"] = m.group(1)
    return s


def parse(clause, kind=None):
    """{"ops": [...], "ask": str | None}. kind: what the chat is drawing now ('house' | 'part' | None)."""
    raw = clause
    c = " ".join(clause.lower().replace("’", "'").split())
    out = {"ops": [], "ask": None}

    def done(*ops):
        out["ops"] = list(ops)
        return out
    # ---------------------------------------------------------------- saving
    if re.search(r"\b(?:export|save|download|give me|send|print|need)\b.*\b(?:pdf|dxf|dwg|png|image|picture|cad file|autocad|file|cut ?file|laser|cnc)\b|^\s*(?:pdf|dxf|dwg)\b", c):
        fmt = "dwg" if re.search(r"\bdwg\b", c) else "cut" if re.search(r"\bcut ?file|laser|cnc|plasma|water ?jet", c) else \
            "dxf" if re.search(r"\bdxf\b|\bcad file\b|\bautocad\b", c) else "png" if re.search(r"\bpng|image|picture|photo\b", c) else "pdf"
        op = {"op": "export", "fmt": fmt}
        m = re.search(r"\b(a[1-4])\b", c)
        if m:
            op["paper"] = m.group(1).upper()
        return done(op)
    m = re.search(r"\b(?:on|to|use)\s+(?:an?\s+)?(a[1-4])\b|\b(a[1-4])\s+(?:paper|sheet|size)\b", c)
    if m:
        return done({"op": "paper", "paper": (m.group(1) or m.group(2)).upper()})
    m = re.search(r"\bscale\s*(?:of\s*)?1\s*[:/]\s*(\d+)\b", c)
    if m:
        return done({"op": "scale", "scale": int(m.group(1))})
    # ---------------------------------------------------------------- questions
    if re.search(r"\b(?:covered|built|total|plot) area\b|\bhow many (?:marla|square feet|sq ?ft)\b|\bhow big is the (?:house|plot|plan)\b", c):
        return done({"op": "ask", "what": "area"})
    if re.search(r"\b(?:list|show|what are)\b.*\brooms\b|\broom (?:sizes|schedule|list)\b|\bwhat rooms\b", c):
        return done({"op": "ask", "what": "rooms"})
    m = re.search(r"\b(?:can|could|will|would)\b.*\b(?:fit|have|get)\b.*?\b(\d+|one|two|three|four|five|six)\s*(?:bed ?rooms?|beds?)\b", c)
    if m:
        return done({"op": "ask", "what": "fit", "bedrooms": int(_num(m.group(1)))})
    if re.search(r"^\s*(?:how big|what size|what is the size|size of|how wide|how long|how deep)\b", c) and room_in(c):
        return done({"op": "ask", "what": "room", "room": room_in(c)})
    if re.search(r"\b(?:what(?:'s| is) wrong|any problems|check (?:it|the plan|the drawing)|is it ok|is it good)\b", c):
        return done({"op": "ask", "what": "checks"})
    # ---------------------------------------------------------------- parts
    ps = part_spec(c)
    if kind == "part" and not ps.get("kind"):  # a change to the part on the drawing
        ed = dict(ps)
        m = re.search(r"\bmake the holes?\s*(\d+(?:\.\d+)?)\b(?!\s*(?:mm\s*)?(?:in\s*)?from)|\bholes?\s*(?:to\s*)?(\d+(?:\.\d+)?)\s*mm\b(?!\s*(?:in\s*)?from)"
                      r"|\bhole (?:size|dia(?:meter)?)\s*(?:to\s*|of\s*)?(\d+(?:\.\d+)?)", c)
        if m:
            ed["hole_size"] = float(next(g for g in m.groups() if g))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:in\s*)?from (?:the )?(?:corners?|edges?|sides?)\b|\bedge distance\s*(?:of\s*|to\s*)?(\d+(?:\.\d+)?)", c)
        if m and not (ed.get("holes") and re.search(r"\badd\b", c)):
            ed["hole_edge"] = float(m.group(1) or m.group(2))
            if ed.get("holes") and all(h.get("pattern") != "center" for h in ed["holes"]):
                ed.pop("holes")
        if re.search(r"\b(?:remove|delete|drop|no|without|take out)\b[^,.]*\b(?:cent(?:re|er)|middle) hole\b", c):
            ed["drop_center"] = True
            ed.pop("holes", None)
        m = re.search(r"^\s*(?:make it|change it to|resize(?: it)? to|now)?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:x|by|×)\s*(\d+(?:\.\d+)?)"
                      r"(?:\s*(?:mm)?\s*(?:x|by|×)\s*(\d+(?:\.\d+)?))?\s*(?:mm)?\s*$", c)
        if m:
            ed.update(w=float(m.group(1)), h=float(m.group(2)))
            if m.group(3):
                ed["t"] = float(m.group(3))
        hs = ed.get("holes") or []
        if len(hs) == 1 and hs[0].get("pattern") != "center" and not re.search(r"\b(?:add|plus|more|extra|another)\b", c):
            ed.pop("holes")  # '8 holes': the count of the holes there are, not a second set
            ed["hole_count"] = hs[0]["n"]
            if re.search(r"\bholes?\s*(?:of\s*)?(?:ø|dia(?:meter)?\s*)?\d", c):
                ed["hole_size"] = hs[0]["d"]
        m = re.search(r"\b(\d+|four|six|eight)\s*bolt holes?\b", c)
        if m:
            ed["hole_count"] = int(_num(m.group(1)))
        if ed:
            return done({"op": "part", "spec": ed, "new": False})
    if ps.get("kind") or (kind == "part" and ps) or re.search(r"\bplate\b|\bflange\b|\bbracket\b|\blaser cut", c):
        if not ps.get("kind") and kind != "part" and not ps:
            out["ask"] = "What size? e.g. 'a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners'."
            return out
        m = re.search(r"\bmake the holes?\s*(\d+(?:\.\d+)?)|\bholes?\s*(?:to\s*)?(\d+(?:\.\d+)?)\s*mm\b|\bhole (?:size|dia(?:meter)?)\s*(?:to\s*)?(\d+(?:\.\d+)?)", c)
        if m and not ps.get("holes") and kind == "part":
            ps["hole_size"] = float(next(g for g in m.groups() if g))
        m = re.search(r"\bholes?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*from the (?:corners?|edges?|sides?)\b", c)
        if m and kind == "part" and not ps.get("holes"):
            ps["hole_edge"] = float(m.group(1))
        if re.search(r"\bremove (?:the )?(?:cent(?:re|er)|middle) hole\b", c):
            ps["drop_center"] = True
        return done({"op": "part", "spec": ps, "new": bool(ps.get("kind")) and kind != "part"})
    # ---------------------------------------------------------------- houses
    hb = house_brief(c)
    new_house = bool(re.search(r"\b(?:house|home|plan|villa|bungalow|map|naqsha|nuqsha|ghar|makan|design)\b", c)) and ("plot" in hb or re.search(r"\b(?:new|make|draw|design|create|need|want)\b", c))
    if kind is None and hb and not hb.get("plot") and not new_house and re.search(r"\b(?:bed ?rooms?|beds?|kamr|stor(?:e)?y|dining|porch)\b", c):
        out["ask"] = "What plot is it for? e.g. '5 marla', '10 marla', '1 kanal' or '30 x 60 feet'."
        return out
    if new_house and (hb.get("plot") or kind != "house"):
        if not hb.get("plot"):
            out["ask"] = "What plot? e.g. '5 marla', '10 marla', '1 kanal' or '30 x 60 feet'."
            return out
        return done({"op": "house", "brief": hb, "new": True})
    ops = []
    m = re.search(r"\b(?:add|one more|another)\s+(?:a\s+)?bed ?room\b", c)
    if m:
        ops.append({"op": "bedrooms", "by": 1})
    elif re.search(r"\b(?:remove|delete|drop|one less|take out)\s+(?:a|one|the last)?\s*bed ?room\b", c):
        ops.append({"op": "bedrooms", "by": -1})
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:'|ft|feet)?\s*(?:x|by|×)\s*(\d+(?:\.\d+)?)\s*(?:'|ft|feet)?\b", c)
    room = room_in(c)
    if m and room and not hb.get("plot"):
        ops.append({"op": "size", "room": room, "w": float(m.group(1)), "d": float(m.group(2))})
    elif room and re.search(r"\b(?:bigger|larger|wider|longer|more space|increase|enlarge|grow)\b", c):
        ops.append({"op": "grow", "room": room, "by": 2 if re.search(r"\bmuch|a lot|way\b", c) else 1})
    elif room and re.search(r"\b(?:smaller|narrower|shorter|less space|reduce|shrink|decrease)\b", c):
        ops.append({"op": "grow", "room": room, "by": -2 if re.search(r"\bmuch|a lot|way\b", c) else -1})
    if hb:
        ops.append({"op": "set", "brief": hb})
    m = re.search(r"\b(?:call it|name it|project name is|project:?)\s+['\"]?(.+?)['\"]?\s*$", raw, re.I)
    if m:
        ops.append({"op": "set", "brief": {"name": m.group(1).strip()}})
    m = re.search(r"\b(?:for|client(?: is)?|owner(?: is)?)\s+((?:mr|mrs|ms|dr|haji|sheikh|ch|chaudhry)\.?\s+[A-Za-z]+(?:\s+[A-Za-z]+)?)\b", raw, re.I)
    if m:
        ops.append({"op": "set", "brief": {"client": m.group(1).strip()}})
    return done(*ops)

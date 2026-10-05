"""What a person says about a photo, read by rules into edits (the cheap model reads the rest into the same edits).

  parse("make it a bit brighter and crop it square") -> {"ops": [{"op": "brightness", "amount": 0.12}, {"op": "crop", "aspect": "1:1"}], "ask": None}
  "a bit" halves an amount and "a lot" makes it 1.6 times; "by 30%" is exact. Quoted words are the text to write.
"""
import re

from .ops import ASPECTS, FONTS, PASSPORTS, PRESETS

COLOURS = r"(white|black|red|blue|green|yellow|orange|pink|purple|grey|gray|gold|silver|navy|teal|cream|beige|maroon|brown|light blue|sky blue|" \
          r"light grey|light gray|dark grey|dark gray|off white|mint|peach|coral|lavender|olive|#[0-9a-f]{6}|#[0-9a-f]{3})"
WHERE = r"(top left|top right|bottom left|bottom right|top-left|top-right|bottom-left|bottom-right|upper left|upper right|lower left|lower right|top|bottom|" \
        r"middle|center|centre|left|right)"
IMG_EXT = r"(?:jpe?g|png|webp|bmp|gif|tiff?|heic)"
QUOTE = r"[\"“”'‘’]"


def strength(c, base):
    m = re.search(r"\bby\s+(\d+(?:\.\d+)?)\s*%", c)
    if m:
        return float(m.group(1)) / 100 * (1 if base >= 0 else -1)
    k = 1.0
    if re.search(r"\b(?:a (?:tiny )?bit|slightly|a little|a touch|a tad|just a bit|subtle|subtly|a little bit|mildly|lightly)\b", c):
        k = 0.5
    elif re.search(r"\b(?:a lot|much|way|really|very|super|extremely|heavily|strongly|massively|seriously)\b", c):
        k = 1.6
    return round(base * k, 3)


def quoted(raw):
    return [m.group(1).strip() for m in re.finditer(QUOTE + r"(.+?)" + QUOTE, raw)]


def where_in(c):
    m = re.search(r"\b(?:at|on|in|to|along|across)?\s*(?:the\s+)?" + WHERE + r"\b(?:\s+(?:corner|edge|side|of (?:the )?(?:photo|picture|image)))?", c)
    if not m:
        return None
    w = m.group(1).replace("upper", "top").replace("lower", "bottom").replace(" ", "-").replace("centre", "center")
    return w


def aspect_in(c):
    m = re.search(r"\b(\d{1,2})\s*[:x]\s*(\d{1,2})\b", c)
    if m and m.group(0).replace(" ", "") not in ("4x6", "6x4", "5x7", "2x2"):
        return f"{m.group(1)}:{m.group(2)}"
    for word, asp in (("square", "1:1"), ("story", "9:16"), ("reel", "9:16"), ("tiktok", "9:16"), ("vertical", "9:16"), ("portrait", "4:5"),
                      ("landscape", "16:9"), ("widescreen", "16:9"), ("wide", "16:9"), ("horizontal", "16:9"), ("cinema", "21:9"), ("a4", "a4")):
        if re.search(r"\b" + word + r"\b", c):
            return asp
    return None


def preset_in(c):
    for name in sorted(PRESETS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"s?\b", c):
            return name
    if re.search(r"\binsta(?:gram)?\b|\big\b", c):
        return "instagram portrait" if re.search(r"\bportrait\b", c) else "instagram story" if re.search(r"\bstor(?:y|ies)\b", c) else "instagram"
    if re.search(r"\byoutube\b", c):
        return "youtube thumbnail"
    if re.search(r"\bfacebook\b|\bfb\b", c):
        return "facebook cover" if re.search(r"\bcover\b", c) else "facebook post"
    if re.search(r"\blinkedin\b", c):
        return "linkedin banner" if re.search(r"\bbanner|cover|background\b", c) else "linkedin post"
    if re.search(r"\bwhatsapp\b", c):
        return "whatsapp status" if re.search(r"\bstatus|story\b", c) else "whatsapp dp"
    return None


def colour_in(c, after=None):
    rx = (after + r"\s+(?:in\s+|to\s+|with\s+(?:a\s+)?)?" if after else r"\b") + COLOURS + r"\b"
    m = re.search(rx, c)
    return m.group(1) if m else None


def file_in(raw):
    """A photo file named in the words: a quoted name first ('my beach day.jpg'), else a name without spaces."""
    m = re.search(QUOTE + r"([^\"“”'‘’]+?\." + IMG_EXT + r")" + QUOTE, raw, re.I) or re.search(r"([\w][\w.()&'\-]*\." + IMG_EXT + r")\b", raw, re.I)
    return m.group(1).strip() if m else None


def size_in(c):
    for w in ("tiny", "small", "medium", "large", "huge"):
        if re.search(r"\b" + w + r"\b", c):
            return w
    if re.search(r"\b(?:big|bigger|bold)\b", c):
        return "large"
    if re.search(r"\b(?:massive|giant|enormous|very big)\b", c):
        return "huge"
    return None


def font_in(c):
    for name in sorted(FONTS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", c):
            return name
    if re.search(r"\bfancy|cursive|signature\b", c):
        return "script"
    return None


def parse(clause, raw=None):
    """{"ops": [...], "ask": str | None} for one clause. An edit said with 'instead' / 'rather' replaces the earlier edit
    of its kind (the chat redoes what came after it); 'move the text to the bottom', 'make the title red', 'change the
    text to "..."' change the words already written."""
    c = " ".join(clause.lower().split())
    wanted = re.sub(r"\s*\b(?:instead of|rather than|in place of)\b.*$", "", clause, flags=re.I)  # 'vintage instead of sepia': vintage is wanted
    r = _parse(wanted if wanted.strip() else clause, raw if wanted == clause else wanted)
    if r["ops"] and re.search(r"\binstead\b|\brather\b|\bactually\b|\bswap (?:it|that) for\b", c):
        for o in r["ops"]:
            o["instead"] = True
    m = re.search(r"\bprint\s+(\d+)\b|\b(\d+)\s+(?:copies|of them|photos)\b", c)
    if m:
        for o in r["ops"]:
            if o["op"] == "passport":
                o["want"] = int(m.group(1) or m.group(2))
    return r


def _parse(clause, raw=None):
    raw = raw or clause
    c = " ".join(clause.lower().replace("’", "'").split())
    out = {"ops": [], "ask": None}

    def done(*ops):
        out["ops"] = [o for o in ops if o]
        return out

    q = quoted(raw)
    # ---------------------------------------------------------------- changing the words already written
    tm = re.search(r"\b(?:the |that |my )?(?:text|caption|title|words|heading|headline|writing|label)\b", c)
    if tm and not re.search(r"\b(?:add|write|put (?:a|some|the words?)|insert|type|new)\b", c[:tm.start()] + " ") or (tm and re.search(r"\bmove|change|make|edit|fix|turn\b", c[:tm.start()])):
        if re.search(r"\b(?:move|put|place|shift)\b", c) and where_in(c[tm.end():]):
            return done({"op": "text", "modify": True, "where": where_in(c[tm.end():])})
        mod = {"op": "text", "modify": True}
        if q and re.search(r"\b(?:change|replace|edit|fix|make|correct)\b.*\b(?:to|say|says|read|reads|into)\b", c):
            mod["text"] = q[-1]
        col = colour_in(c[tm.end():])
        if col:
            mod["color"] = col
        s = size_in(re.sub(r"\b(?:bigger|larger|smaller|big|bold)\b", " ", c[tm.end():]))
        if s:
            mod["size"] = s
        elif re.search(r"\bbigger|larger\b", c):
            mod["size_rel"] = 2 if re.search(r"\b(?:much|a lot|way) (?:bigger|larger)\b", c) else 1  # a step up from what it is
        elif re.search(r"\bsmaller\b", c):
            mod["size_rel"] = -2 if re.search(r"\b(?:much|a lot|way) smaller\b", c) else -1
        f = font_in(c[tm.end():])
        if f:
            mod["font"] = f
        if re.search(r"\boutline\b", c):
            mod["outline"] = colour_in(c, r"outline") or "black"
        if len(mod) > 2:
            return done(mod)
    # ---------------------------------------------------------------- words on the photo (first: the quoted words could say anything)
    if re.search(r"\bmeme\b", c):
        if len(q) >= 2:
            return done({"op": "meme", "top": q[0], "bottom": q[1]})
        if q:
            return done({"op": "meme", "top": None if re.search(r"\bbottom\b", c) else q[0], "bottom": q[0] if re.search(r"\bbottom\b", c) else None})
        out["ask"] = "What should the meme say? e.g. 'make it a meme: \"top words\" / \"bottom words\"'."
        return out
    if re.search(r"\bwatermark\b|©|\bcopyright\b", c):
        fl = file_in(raw)
        text = q[0] if q else (None if fl else (re.search(r"(?:watermark|copyright)\s+(?:it\s+)?(?:with\s+)?(?:saying\s+)?(.+?)(?:\s+(?:at|in|on|across|all over)\b.*)?$", raw, re.I) or [None, None])[1])
        if text and text.lower().strip() in ("it", "this", "the photo", "the picture", "the image"):
            text = None
        op = {"op": "watermark", "text": ("© " + text.strip().lstrip("©").strip()) if text and "©" not in text and re.search(r"©|\bcopyright\b", c) else (text.strip() if text else None),
              "logo": fl if fl and re.search(r"\blogo\b", c) else None, "tiled": bool(re.search(r"\bacross|all over|tiled?|repeat|diagonal|everywhere\b", c))}
        if not op["text"] and not op["logo"]:
            out["ask"] = "What should the watermark say? e.g. 'watermark \"© Your Name\"'."
            return out
        w = where_in(c)
        if w and not op["tiled"]:
            op["where"] = w if "-" in w else {"top": "top-right", "bottom": "bottom-right"}.get(w, w)
        if re.search(r"\bfaint|subtle|light(?:ly)?|barely\b", c):
            op["opacity"] = 0.2
        elif re.search(r"\bstrong|bold|visible|dark\b", c):
            op["opacity"] = 0.55
        return done(op)
    text_m = re.search(r"\b(?:add|put|write|place|type|insert|print|stamp|overlay)\b.*?\b(?:text|caption|title|words?|heading|headline|quote|label|saying|says)\b|"
                       r"\b(?:write|caption|title|heading|headline|label)\b", c)
    not_text = re.search(r"\bpolaroid|background|watermark|meme|collage\b", c) or (q and re.search(r"\." + IMG_EXT + r"$", q[0], re.I))
    if not not_text and ((q and (text_m or re.search(r"\bbanner|strip|ribbon\b", c) or re.search(r"\b(?:add|put|write|place|type|insert|print|stamp|overlay|say|says|saying)\b", c)))
                         or (text_m and re.search(r"\b(?:saying|that says|which says|reading|:)\s*\S", c))):
        words = q[0] if q else re.search(r"\b(?:saying|that says|which says|reading|:)\s*(.+?)\s*(?:\b(?:at|on|in) the\b.*)?$", raw, re.I).group(1)
        op = {"op": "text", "text": words.strip()}
        rest = re.sub(QUOTE + r".+?" + QUOTE, " ", c)
        w = where_in(rest)
        if w:
            op["where"] = w
        col = colour_in(rest)
        if col:
            op["color"] = col
        s = size_in(rest)
        if s:
            op["size"] = s
        f = font_in(rest)
        if f:
            op["font"] = f
        if re.search(r"\bbanner|strip|ribbon|on a (?:band|bar|box)|with a (?:band|bar|box|background)\b", rest):
            op["style"] = "banner"
            bgc = colour_in(rest, r"(?:banner|strip|ribbon|band|bar|box|background)")
            if bgc:
                op["bg"] = bgc
                if op.get("color") == bgc:
                    op.pop("color")
        elif re.search(r"\btitle|heading|headline\b", rest):
            op["style"] = "title"
            op.setdefault("size", "large")
        if re.search(r"\boutline|stroke|border round the (?:text|letters)\b", rest):
            op["outline"] = colour_in(rest, r"(?:outline|stroke)") or "black"
        if re.search(r"\b(?:all )?caps|upper ?case|capital letters\b", rest):
            op["upper"] = True
        return done(op)

    # ---------------------------------------------------------------- questions
    if re.search(r"\b(?:where|when) (?:was|were) (?:this|it|the (?:photo|picture|image)|these) taken\b|\bwhat (?:camera|phone)\b|\b(?:show|read|what(?:'s| is| are)) (?:the |its )?"
                 r"(?:metadata|exif|location|gps|date taken)\b|\bdoes (?:it|this|the photo) have (?:a |any )?(?:location|gps|metadata)\b", c):
        return done({"op": "describe", "meta": True})
    if re.search(r"^\s*(?:what(?:'s| is)? (?:in |on )?(?:the |this )?(?:photo|picture|image|it)|describe|how does it look|tell me about (?:the |this )?(?:photo|picture|image|it)|"
                 r"is (?:it|the photo|this) (?:too )?(?:dark|bright|blurry|sharp|tilted|crooked|straight|noisy|grainy)|how (?:big|large) is|what size|"
                 r"how many (?:faces|people)|what (?:resolution|dimensions)|analy[sz]e)", c):
        return done({"op": "describe"})
    if re.search(r"^\s*(?:what can you do|help|ideas|suggest|what (?:should|could) i do)\b", c):
        return done({"op": "help"})

    # ---------------------------------------------------------------- background and people
    other = file_in(raw)
    if re.search(r"\b(?:remove|delete|erase|cut out|take out|get rid of|drop|clear)\b.*\bbackground\b|\btransparent (?:background|png)\b|\bcut (?:him|her|it|them|the \w+) out\b|"
                 r"\bno background\b|\bbackground removed\b", c):
        return done({"op": "remove_background"})
    if re.search(r"\bblur (?:the |his |her |their )?background\b|\bportrait mode\b|\bbokeh\b|\bbackground (?:out of focus|blurr?y|soft)\b|\bblurr?y background\b", c):
        return done({"op": "blur_background", "amount": strength(c, 0.6)})
    if re.search(r"\bbackground\b", c) and re.search(r"\b(?:change|replace|make|set|turn|swap|put|use|give)\b|\bto\b|\bwith\b", c) or \
            (other and re.search(r"\b(?:put|place) (?:him|her|it|them|the \w+) (?:on|in front of|against|into)\b", c)):
        if other:
            return done({"op": "replace_background", "image": other})
        col = colour_in(c, r"background") or colour_in(c)
        if re.search(r"\bblur", c):
            return done({"op": "blur_background", "amount": 0.6})
        if col:
            return done({"op": "replace_background", "color": col})
        out["ask"] = "Change the background to what? A colour ('make the background white') or another photo ('replace the background with beach.jpg')."
        return out
    if re.search(r"\b(?:blur|hide|pixelate|pixelise|pixelize|cover|anonymi[sz]e|censor|mask|obscure)\b.*\bfaces?\b|\bfaces? (?:blurred|hidden|pixelated)\b", c):
        return done({"op": "blur_faces", "style": "pixelate" if re.search(r"\bpixel", c) else "blur"})
    if re.search(r"\b(?:brighten|lighten|lift|light up)\b.*\bfaces?\b|\bfaces? (?:is|are|look) (?:too )?dark\b|\bbacklit\b", c):
        return done({"op": "brighten_faces", "amount": strength(c, 0.35)})
    if re.search(r"\bsmooth(?:en)?\b.*\bskin\b|\bsoften (?:the )?skin\b|\bretouch\b|\bbeautif|\bairbrush|\bskin smoothing\b|\bremove (?:the )?(?:blemishes|wrinkles|spots|pimples)\b", c):
        return done({"op": "smooth_skin", "amount": strength(c, 0.5)})
    if re.search(r"\bpassport|\bvisa (?:photo|picture)|\bid (?:card )?(?:photo|picture)\b", c) or \
            (re.search(r"\bprint\b|\bsheet\b", c) and re.search(r"\b(?:4x6|6x4|5x7|a4|sheet|copies|\d+ of (?:them|it))\b", c)):
        std = next((k for k in sorted(PASSPORTS, key=len, reverse=True) if re.search(r"\b" + re.escape(k) + r"\b", c)), None)
        if not std and re.search(r"\b(?:usa|american|united states|u\.s\.)\b", c):
            std = "us"
        if not std and re.search(r"\b(?:british|england|united kingdom)\b", c):
            std = "uk"
        op = {"op": "passport", "bg": colour_in(c) or "white"}
        if std:
            op["standard"] = std
        if re.search(r"\bsheet|print|copies|several|4x6|6x4|5x7|a4 sheet|multiple\b", c):
            op["sheet"] = "5x7" if "5x7" in c else "a4" if re.search(r"\ba4\b", c) else "4x6"
        return done(op)
    if re.search(r"\bscan|\bscanned\b|\bdocument\b|\breceipt\b|\bflatten (?:the )?(?:page|paper|document)\b|\bstraighten (?:the )?(?:page|paper|document|receipt)\b", c):
        return done({"op": "document", "mode": "color" if re.search(r"\bcolou?r", c) else "scan"})
    if re.search(r"\b(?:remove|erase|get rid of|delete|clean off)\b.*\b(?:date|time ?stamp|logo|watermark|stamp|writing|text|signature|numbers)\b", c):
        return done({"op": "erase", "where": where_in(c) or "bottom-right"})
    if re.search(r"\bcollage\b|\bgrid of\b|\bside by side\b|\bput (?:them|these|the photos|all) together\b|\bcombine (?:the |these )?(?:photos|pictures|images)\b", c):
        return done({"op": "collage", "layout": "row" if re.search(r"\bside by side|in a row\b", c) else "column" if re.search(r"\bon top of each other|stacked|in a column\b", c) else "grid"})

    # ---------------------------------------------------------------- saving
    m = re.search(r"\b(?:under|less than|below|max(?:imum)?|at most|smaller than|no more than|up to)\s*(\d+(?:\.\d+)?)\s*(kb|k|mb|m)\b", c)
    if m or re.search(r"\b(?:save|export|download|give me (?:it|the file)|convert (?:it )?to|as (?:a |an )?(?:jpe?g|png|webp|pdf))\b", c) or \
            (re.search(r"\b(?:ready|for)\b", c) and preset_in(c) and not re.search(r"\bcrop|without cropping|fit\b", c)) or \
            re.search(r"\b(?:compress|smaller file|file size|reduce (?:the )?(?:file )?size)\b", c):
        op = {"op": "export"}
        fm = re.search(r"\b(jpe?g|png|webp|pdf)\b", c)
        if fm:
            op["fmt"] = fm.group(1).replace("jpeg", "jpg")
        if m:
            op["max_kb"] = float(m.group(1)) * (1024 if m.group(2).startswith("m") else 1)
        elif re.search(r"\bcompress|smaller file|file size|reduce (?:the )?(?:file )?size\b", c):
            op["max_kb"] = 500
        p = preset_in(c)
        if p:
            op["preset"] = p
            op["fit"] = "canvas" if re.search(r"\bwithout cropping|don'?t crop|no crop|whole photo|fit\b", c) else "crop"
        if re.search(r"\b(?:remove|strip|without|no)\b.*\b(?:location|gps|metadata|exif|camera info)\b", c):
            op["strip"] = "all" if re.search(r"\bmetadata|exif|everything|camera\b", c) else "gps"
        q_ = re.search(r"\bquality\s*(\d{2,3})\b|\b(\d{2,3})%? quality\b", c)
        if q_:
            op["quality"] = int(q_.group(1) or q_.group(2))
        if re.search(r"\bnext to the original|beside the original|same folder\b", c):
            op["beside"] = True
        return done(op)
    if re.search(r"\b(?:remove|strip|delete|clear|wipe)\b.*\b(?:location|gps|metadata|exif|camera (?:info|details))\b", c):
        return done({"op": "strip", "what": "all" if re.search(r"\bmetadata|exif|everything|camera\b", c) else "gps"})

    # ---------------------------------------------------------------- shape
    ops = []
    if re.search(r"\bwithout cropping\b|\bdon'?t crop\b|\bfit (?:it |the whole (?:photo|picture) )?(?:in|into|to|for)\b|\bletterbox|\bwhite (?:space|bars)\b|\bblack bars\b|\bwhole (?:photo|picture) (?:in|on)\b", c):
        p = preset_in(c)
        asp = aspect_in(c) or (None if p else "1:1")
        fill = "white" if re.search(r"\bwhite\b", c) else "black" if re.search(r"\bblack\b", c) else colour_in(c) or "blur"
        op = {"op": "canvas", "fill": fill}
        if p:
            op["size"] = list(PRESETS[p])
            op["aspect"] = f"{PRESETS[p][0]}:{PRESETS[p][1]}"
        else:
            op["aspect"] = asp
        return done(op)
    if re.search(r"\bcrop\b|\bcut (?:it )?(?:down )?to\b|\bmake it (?:a )?(?:square|portrait|landscape|vertical|horizontal|widescreen)\b|\b(?:square|vertical) (?:version|crop)\b|\bzoom in\b|\btighter\b|"
                 r"\b(?:make it|turn it into|change it to|go|switch to)\s+(?:a\s+)?\d{1,2}\s*[:x]\s*\d{1,2}\b", c):
        asp = aspect_in(c)
        p = preset_in(c)
        if p and not asp:
            asp = f"{PRESETS[p][0]}:{PRESETS[p][1]}"
        if asp:
            ops.append({"op": "crop", "aspect": asp})
        elif re.search(r"\bto (?:the |him|her|them|it\b)|\baround (?:the |him|her)|\bon (?:the |him|her)|\bsubject\b|\bperson\b|\bface\b|\bcar\b|\bclose(?:r|-up)?\b|\bzoom in\b", c):
            ops.append({"op": "crop", "subject": True})
        elif re.search(r"\bedges|tighter|a bit|in\b", c):
            ops.append({"op": "trim", "amount": 0.1 if not re.search(r"\ba (?:little|bit)\b", c) else 0.06})
        else:
            out["ask"] = "Crop to what? e.g. 'crop it square', 'crop to 16:9', 'crop to the car', or 'crop for an Instagram story'."
            return out
    if re.search(r"\bupside down\b", c):
        ops.append({"op": "rotate", "degrees": 180})
    elif re.search(r"\brotate|\bturn (?:it )?(?:left|right|sideways|clockwise|anti|counter)", c):
        m = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:degrees?|°)", c)
        if m and float(m.group(1)) not in (90, 180, 270):
            ang = float(m.group(1)) * (-1 if re.search(r"\bleft|anti|counter", c) else 1)  # clockwise is positive
            ops.append({"op": "rotate", "degrees": ang})
        else:
            d = int(m.group(1)) if m else 90
            ops.append({"op": "rotate", "degrees": (360 - d) % 360 if re.search(r"\bleft|anti|counter", c) else d})
    if re.search(r"\bflip|\bmirror", c):
        ops.append({"op": "flip", "how": "vertical" if re.search(r"\bvertical|upside|top to bottom", c) else "horizontal"})
    if re.search(r"\bstraighten|\blevel (?:the |out the )?horizon|\b(?:it'?s|it is|is) (?:a bit |slightly )?(?:tilted|crooked|wonky|slanted|not straight|leaning)\b|\bhorizon\b", c):
        ops.append({"op": "straighten"})
    m = re.search(r"\b(\d{2,5})\s*[x×]\s*(\d{2,5})\b", c)
    m2 = re.search(r"\b(\d{2,5})\s*(?:px|pixels?)?\s*(wide|width|across|tall|high|height)\b", c)
    m3 = re.search(r"\b(\d{1,3})\s*%\s*(?:size|smaller|of (?:the )?size)?|\bhalf (?:the )?size\b|\bdouble (?:the )?size\b", c)
    if re.search(r"\bresize|\bscale\b|\bmake it (?:smaller|bigger|larger)\b|\bdownsize|\bupscale|\bshrink|\breduce (?:the )?(?:dimensions|resolution)\b|"
                 r"\b(?:half|double) (?:the )?size\b", c) or m or m2:
        if m:
            ops.append({"op": "resize", "width": int(m.group(1)), "height": int(m.group(2))})
        elif m2:
            ops.append({"op": "resize", ("width" if m2.group(2) in ("wide", "width", "across") else "height"): int(m2.group(1))})
        elif m3:
            pct = 50 if "half" in m3.group(0) else 200 if "double" in m3.group(0) else int(m3.group(1))
            ops.append({"op": "resize", "percent": pct})
        elif re.search(r"\bsmaller|shrink|downsize\b", c):
            ops.append({"op": "resize", "percent": 50})
        elif re.search(r"\bbigger|larger|upscale\b", c):
            ops.append({"op": "resize", "percent": 200})

    # ---------------------------------------------------------------- frames
    if re.search(r"\bpolaroid\b", c):
        ops.append({"op": "polaroid", "caption": q[0] if q else None})
    elif re.search(r"\bborder\b|\bframe\b", c) and not re.search(r"\bframe rate\b", c):
        col = colour_in(c, r"(?:border|frame)") or colour_in(c) or "white"
        ops.append({"op": "border", "color": col, "percent": 0.02 if re.search(r"\bthin\b", c) else 0.07 if re.search(r"\bthick\b", c) else 0.04})
    if re.search(r"\brounded? (?:the )?corners|\bround (?:the )?corners|\bcorners rounded\b", c):
        ops.append({"op": "rounded"})
    if re.search(r"\bvignette|\bdarken (?:the )?(?:edges|corners)|\bdark (?:edges|corners)\b", c):
        ops.append({"op": "vignette", "amount": strength(c, 0.35)})

    # ---------------------------------------------------------------- looks (one at a time)
    looks = [(r"\bblack (?:and|&|n) white\b|\bb ?& ?w\b|\bb/w\b|\bgr[ae]yscale\b|\bmonochrome\b|\bno colou?rs?\b", "bw"), (r"\bsepia\b|\bold photo\b|\bantique\b", "sepia"),
             (r"\bvintage\b|\bretro\b|\bold school\b|\bnostalgic\b|\b90s\b|\b80s\b|\b70s\b", "vintage"), (r"\bcinematic\b|\bmovie look\b|\bfilm look\b|\bteal and orange\b|\bhollywood\b", "cinematic"),
             (r"\bdramatic\b|\bmoody\b|\bintense\b|\bgritty\b", "dramatic"), (r"\bfaded?\b|\bmatte\b|\bwashed out look\b", "fade"),
             (r"\bdreamy\b|\bglow(?:y|ing)?\b|\bhazy\b|\bsoft (?:look|glow|focus)\b|\bethereal\b", "soft"), (r"\bmake (?:it|the colou?rs) pop\b|\bpop(?:py)?\b|\bvibrant look\b", "pop"),
             (r"\bsketch\b|\bpencil\b|\bdrawing\b", "sketch"), (r"\bcartoon|\bcomic\b|\banime\b|\btoon\b", "cartoon"), (r"\bpainting\b|\bpainted\b|\boil paint|\bwatercolou?r|\bartistic\b", "painting"),
             (r"\bhdr\b", "hdr"), (r"\binvert|\bnegative\b", "invert")]
    if re.search(r"\bnoir\b", c):  # film noir: black and white, hard light
        ops += [{"op": "bw"}, {"op": "dramatic"}]
    else:
        for rx, name in looks:
            if re.search(rx, c):
                ops.append({"op": name})
                break

    # ---------------------------------------------------------------- light and colour
    if re.search(r"\b(?:auto(?:matic(?:ally)?)?[ -]?(?:enhance|fix|correct|adjust)?|enhance|improve|fix (?:it|this|the photo|the picture)|make it (?:look )?(?:better|nicer|good|great|professional)|"
                 r"touch ?(?:it )?up|polish|clean it up|best version)\b", c) and not ops:
        ops.append({"op": "auto"})
    dark = re.search(r"\b(?:too dark|underexposed|it'?s (?:so |very |a bit |rather )?dark|is (?:so |very |a bit )?dark)\b", c)
    if any(o["op"] == "auto" for o in ops) and dark:
        next(o for o in ops if o["op"] == "auto")["brighter"] = True  # 'it's too dark, fix it': one pass, aimed brighter
    elif re.search(r"\b(?:brighter|brighten|lighter|lighten|more light|exposure up|increase (?:the )?(?:brightness|exposure))\b", c) or dark:
        if not re.search(r"\bfaces?\b|\bshadows?\b", c):
            ops.append({"op": "brightness", "amount": strength(c, 0.25)})
    elif re.search(r"\b(?:darker|darken|dimmer|too bright|overexposed|exposure down|less bright|decrease (?:the )?(?:brightness|exposure)|tone it down)\b", c) and \
            not re.search(r"\bedges|corners|shadows\b", c):
        ops.append({"op": "brightness", "amount": strength(c, -0.2)})
    if re.search(r"\b(?:more contrast|higher contrast|increase (?:the )?contrast|punchier|punchy|add contrast|boost (?:the )?contrast|crisper tones)\b", c):
        ops.append({"op": "contrast", "amount": strength(c, 0.25)})
    elif re.search(r"\b(?:less contrast|lower contrast|reduce (?:the )?contrast|decrease (?:the )?contrast|flatter|softer contrast)\b", c):
        ops.append({"op": "contrast", "amount": strength(c, -0.25)})
    if re.search(r"\bvibran", c):
        ops.append({"op": "vibrance", "amount": strength(c, 0.35)})
    elif re.search(r"\b(?:more colou?rful|more vivid|vivid|more saturat\w*|saturate|richer colou?rs?|boost (?:the )?colou?rs?|more colou?r|colou?rs? (?:more )?(?:pop|brighter|stronger))\b", c):
        ops.append({"op": "saturation", "amount": strength(c, 0.3)})
    elif re.search(r"\b(?:less saturat\w*|desaturat\w*|muted|less colou?r(?:ful)?|tone down the colou?rs?|duller colou?rs?|calmer colou?rs?)\b", c):
        ops.append({"op": "saturation", "amount": strength(c, -0.3)})
    if re.search(r"\b(?:warmer|warm(?: it)? up|golden|sunnier|warm(?:er)? tones?|more warmth|add warmth)\b", c):
        ops.append({"op": "warmth", "amount": strength(c, 0.3)})
    elif re.search(r"\b(?:cooler|colder|cool(?: it)? down|bluer|cool(?:er)? tones?|icy)\b", c):
        ops.append({"op": "warmth", "amount": strength(c, -0.3)})
    if re.search(r"\b(?:lift|raise|brighten|open up|recover|show more in)\b.*\bshadows?\b|\bshadow detail\b|\bdetails? in the dark\b", c):
        ops.append({"op": "shadows", "amount": strength(c, 0.4)})
    elif re.search(r"\b(?:deeper|darker|deepen)\b.*\bshadows?\b|\bcrush (?:the )?blacks\b", c):
        ops.append({"op": "shadows", "amount": strength(c, -0.3)})
    if re.search(r"\b(?:bring down|reduce|tone down|recover|lower|soften)\b.*\bhighlights?\b|\b(?:sky|window) (?:is )?(?:too bright|blown|white)\b|\bblown(?: out)?\b", c):
        ops.append({"op": "highlights", "amount": strength(c, 0.4)})
    if re.search(r"\bwhite balance\b|\bfix (?:the )?colou?rs?\b|\bcolou?r cast\b|\b(?:remove|fix|get rid of)\b.*\b(?:tint|cast)\b|\btoo (?:yellow|blue|orange|green|red|pink)\b|"
                 r"\bnatural colou?rs?\b|\bcorrect (?:the )?colou?rs?\b", c):
        ops.append({"op": "white_balance"})
    if re.search(r"\bclarity\b|\bmore detail\b|\bmore texture\b|\blocal contrast\b|\bbring out (?:the )?details?\b", c):
        ops.append({"op": "clarity", "amount": strength(c, 0.5)})
    if re.search(r"\b(?:noise|grain|grainy|noisy|denoise|speckles)\b", c) and not re.search(r"\badd (?:some )?(?:film )?grain\b", c):
        ops.append({"op": "denoise", "amount": None, "strength": strength(c, 0.6)})
    if re.search(r"\bsharpen|\bsharper\b|\bcrisper\b|\bclearer\b|\bless blurry\b|\bunblur|\bdeblur|\bnot sharp\b|\bin focus\b", c):
        ops.append({"op": "sharpen", "amount": strength(c, 0.6)})
    elif re.search(r"\bblur (?:it|the (?:whole )?(?:photo|picture|image))\b|\bmake it blurr?y\b|\bsoften it\b", c):
        ops.append({"op": "blur", "amount": strength(c, 0.5)})
    for o in ops:
        if o.get("op") == "denoise":
            o.pop("amount", None)
    return done(*ops)

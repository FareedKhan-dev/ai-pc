"""A conversation about converting, shrinking, cutting and fixing video and sound files: Format Factory and HandBrake
done by code. Every change makes a version, always made from the original (nothing is compressed twice); every version
is read back and checked, and its look measured against the original.

  c = ConvertChat.start("holiday.mov")            the original is never changed; versions live in the chat's folder
  c.say("will it play on whatsapp?")              -> what would stop it, if anything
  c.say("make it ready for whatsapp")             -> v1: 1280x720 H.264, 11.8 MB (was 96 MB), looks 96/100 like the original
  c.say("cut the first 5 seconds and make it under 10 MB")
  c.say("make a gif of 0:05 to 0:08") / c.say("screenshots every 10 seconds") / c.say("split it into 3 parts")
  c.say("join it with intro.mp4") / c.say("extract the audio as mp3") / c.say("save it to my desktop")
  c.say("undo") / c.say("go back to v1") / c.say("history") / c.say("record my screen for 20 seconds")
  c = ConvertChat.load(chat_id)                   a saved chat again
"""

import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path

from ai_pc.convert import encode as E
from ai_pc.convert import media as MD
from ai_pc.convert import plan as P
from ai_pc.convert import record as R
from ai_pc.convert.convparse import parse
from ai_pc.convert.presets import AUDIO_ONLY, PRESETS, VIDEO_CONTAINERS, issues
from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json

CHATS = ROOT / "out" / "convert" / "chats"
UNDO = re.compile(
    r"^\s*(?:please\s+)?(?:undo(?: that| it| the last (?:change|one))?|revert(?: that| it)?|go back(?: one)?|take (?:that|it) back)"
    r"(?:\s+please)?\s*[.!]*\s*$",
    re.I,
)  # the whole message: 'go back to the video and make it 720p' is a change, not an undo
REDO = re.compile(r"^\s*redo\b", re.I)
GOTO = re.compile(
    r"\b(?:go back to|back to|restore|use|switch to)\s+(?:version\s*|v)(\d+)\b|\bback to the original\b|^\s*(?:the )?original\s*$", re.I
)
HISTORY = re.compile(r"^\s*(?:history|versions|show (?:me )?(?:the )?(?:history|versions))\b", re.I)
SPLIT = re.compile(
    r"(?<=[.!?;])\s+|,?\s+(?:and then|then|and also|also|after that)\s+|,?\s+and\s+(?=(?:make|remove|cut|add|put|take|reduce|fade|speed|slow|"
    r"normali[sz]e|save|export|convert|give|burn|trim|keep|turn|rotate|crop|split|join|merge|change|fix|extract|compress|shrink|send|"
    r"stabili[sz]e|mute|flip|mirror)\b)",
    re.I,
)
# a later change of one of these kinds replaces the earlier one; trims, cuts, joins, speed, turns, volume and sync stack
FAMILIES = [
    {"target"},
    {"format", "extract_audio", "gif", "video"},
    {"codec"},
    {"compress", "quality"},
    {"resize"},
    {"fps"},
    {"aspect"},
    {"bars"},
    {"crop"},
    {"stabilize"},
    {"denoise"},
    {"sharpen"},
    {"gray"},
    {"logo"},
    {"subtitles"},
    {"fade"},
    {"mute", "audio"},
    {"normalize"},
    {"mono"},
    {"split"},
    {"hw"},
    {"deinterlace"},
    {"exact", "lossless"},
    {"smooth"},
]
PICTURE_OPS = {
    "resize",
    "fps",
    "aspect",
    "rotate",
    "flip",
    "bars",
    "crop",
    "stabilize",
    "denoise",
    "sharpen",
    "gray",
    "logo",
    "subtitles",
    "deinterlace",
}
KNOWN = {
    "trim",
    "cut",
    "join",
    "speed",
    "format",
    "codec",
    "compress",
    "quality",
    "target",
    "resize",
    "fps",
    "aspect",
    "rotate",
    "flip",
    "bars",
    "crop",
    "deinterlace",
    "stabilize",
    "denoise",
    "sharpen",
    "gray",
    "logo",
    "subtitles",
    "fade",
    "mute",
    "audio",
    "volume",
    "normalize",
    "sync",
    "mono",
    "extract_audio",
    "gif",
    "frames",
    "split",
    "video",
    "hw",
    "lossless",
    "exact",
    "smooth",
    "ask",
    "save",
    "record",
    "record_stop",
}
CONVERT_SYSTEM = """You turn a person's request about a video or sound file into changes for a converter program. Reply with ONE JSON
object: {"ops": [...]} or {"ask": "<short question back>"}. Each op is {"op": NAME, "args": {...}}:
 target {"name": "whatsapp|email|discord|telegram|slack|instagram|instagram_post|instagram_story|tiktok|youtube|youtube_shorts|facebook|linkedin|x|web|iphone|android|tv|powerpoint|editing|archive|everywhere"}
 format {"to": "mp4|mkv|mov|webm|avi|gif|mp3|wav|m4a|aac|flac|ogg|opus"}   codec {"video": "h264|hevc|av1|vp9|prores"}
 compress {"max_mb": 10} or {"percent": 50 (of the size)} or {"level": "small|tiny"} or {} (smallest that still looks the same)
 quality {"level": "best|high|good"}   resize {"height": 720} or {"width": 1280} or {"scale": 0.5}   fps {"fps": 30}
 aspect {"ratio": "9:16|1:1|4:5|16:9", "fit": "blur|bars|crop"}   rotate {"deg": 90|180|270}   flip {"dir": "h|v"}   bars {} (cut black bars)
 trim {"start": s, "end": s} or {"first": s} or {"last": s} or {"drop_start": s} or {"drop_end": s}   cut {"ranges": [[s, e]]} (remove)
 speed {"factor": 2}   mute {}   audio {"file": "<name>", "mode": "replace|mix"}   volume {"db": 6}   normalize {}   sync {"delay": -0.3} (minus = sound earlier)
 extract_audio {"fmt": "mp3"}   gif {"max_mb": 5}   frames {"at": [12.5]} or {"every": 10} or {"count": 8} or {"sheet": true} or {"best": true}
 split {"parts": 3} or {"every": 60} or {"max_mb": 16}   join {"files": ["<name>"], "before": false}
 stabilize {}  denoise {}  sharpen {}  gray {}  deinterlace {}  fade {"in": 1, "out": 1}   logo {"file": "<name>", "corner": "br|bl|tr|tl"}
 subtitles {"file": "<name>.srt", "burn": true}   exact {} (cut on the exact frame)   lossless {} (no re-encoding)
 ask {"what": "info|compat|quality|compare|where", "target": "..."}   save {"where": "desktop|downloads|videos|documents|original"}
Times are seconds. Do only what was asked."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


class ConvertChat:
    def __init__(self, state, planner=None, log=print):
        self.state, self.planner, self.log = state, planner, log
        self.folder = Path(state["folder"])
        self.last_turn = None

    # ---------------------------------------------------------------- start / load
    @classmethod
    def start(cls, src=None, chats_dir=None, planner=None, log=print, files=None):
        stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(src).stem)[:24].strip("_").lower() if src else "new"
        base = Path(chats_dir or CHATS).resolve()
        folder = base / f"convert_{stem}_{time.strftime('%H%M%S')}"
        k = 2
        while folder.exists():
            folder = base / f"convert_{stem}_{time.strftime('%H%M%S')}_{k}"
            k += 1
        folder.mkdir(parents=True)
        state = {
            "id": folder.name,
            "folder": str(folder),
            "sources": [],
            "versions": [],
            "cur": -1,
            "redo": [],
            "turns": [],
            "exports": [],
            "extras": [],
            "recording": None,
            "earlier": [],
            "said_notes": [],
            "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in list(files or []) + ([src] if src else [])},
        }
        c = cls(state, planner=planner, log=log)
        if src:
            c._open(Path(src).resolve())
        c.save()
        return c

    @classmethod
    def load(cls, cid, chats_dir=None, planner=None, log=print):
        return cls(json.loads((Path(chats_dir or CHATS) / cid / "chat.json").read_text(encoding="utf-8")), planner=planner, log=log)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def _open(self, src):
        p = MD.probe(src)
        if self.state["versions"]:
            self.state["earlier"].append({"sources": self.state["sources"], "versions": self.state["versions"], "cur": self.state["cur"]})
        self.state["sources"] = [p]
        self.state["files"][Path(src).name.lower()] = str(src)
        self.state["versions"] = [
            {
                "v": 0,
                "ops": [],
                "outputs": [str(src)],
                "kind": "original",
                "size": p["size"],
                "summary": MD.describe(p),
                "checks": [],
                "notes": [],
                "quality": None,
                "said": "(the original)",
                "parent": -1,
                "when": _when(),
            }
        ]
        self.state["cur"], self.state["redo"] = 0, []

    def cur(self):
        return self.state["versions"][self.state["cur"]] if self.state["cur"] >= 0 else None

    @property
    def src(self):
        return self.state["sources"][0] if self.state["sources"] else None

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
            out.append(self.goto(int(m.group(1)) if m.group(1) else 0))
        elif HISTORY.search(message):
            turn["intents"].append("history")
            out.append(self.history())
        else:
            if not self.state["sources"]:
                self._adopt(message)
            ops = []
            instead = bool(re.search(r"\binstead\b|\bactually\b|\bno,? make it\b", message, re.I))
            for cl in [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")] or [message]:
                r = parse(cl, self._ctx())
                if not r["ops"] and (self.planner is not None or not r.get("ask")):  # the model reads what the rules could not (or would ask about)
                    r2 = self._llm(cl, message)
                    r = r2 if (r2["ops"] or not r.get("ask")) else r
                if r.get("ask") and not r["ops"]:
                    out.append(r["ask"])
                    ops = []
                    break
                ops += r["ops"]
            if ops:
                out.append(self._apply(ops, message, instead))
        reply = "\n".join(x for x in out if x).strip() or (
            "Tell me what to do with it, e.g. 'make it ready for WhatsApp', 'under 10 MB', 'convert to mp4', "
            "'cut the first 5 seconds', 'make a GIF of 0:05 to 0:08', 'extract the audio as mp3'."
        )
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), v_to=self.state["cur"])
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _ctx(self):
        s = self.src
        return {
            "duration": (self.cur() or {}).get("duration") or (s or {}).get("duration"),
            "has_video": bool(s and s.get("video")),
            "has_audio": bool(s and s.get("audio")),
            "files": self.state["files"],
        }

    def _adopt(self, message):
        """A chat started without a file takes the first video or sound file the message names."""
        for name in re.findall(
            r"([A-Za-z]:\\[^\"'<>|]+?\.\w{2,4}|[\w\-.()]+\.(?:mp4|mov|mkv|webm|avi|m4v|wmv|flv|3gp|ts|mpg|mp3|wav|m4a|aac|flac|ogg|opus|wma))\b",
            message,
        ):
            p = self._resolve(name)
            if p:
                try:
                    self._open(Path(p))
                    return
                except MD.MediaError:
                    continue

    def _resolve(self, name):
        name = str(name).strip("\"'")
        cands = [Path(name), Path(self.state["files"].get(name.lower(), name))]
        if self.src:
            cands.append(Path(self.src["path"]).parent / name)
        cands.append(Path.cwd() / name)
        return next((str(c.resolve()) for c in cands if c.is_file()), None)

    def _llm(self, clause, message):
        if self.planner is None:
            return {
                "ops": [],
                "ask": f"I could not read '{clause}'. Try e.g. 'make it ready for WhatsApp', 'under 10 MB', 'convert to mp4', "
                "'cut the first 5 seconds', 'make a GIF', 'extract the audio as mp3'.",
            }
        self._turn["llm"] = True
        v, s = self.cur(), self.src
        ctx = (
            (
                f"FILE: {MD.describe(s)}; now v{self.state['cur']}: {(v or {}).get('summary', '')}; changes so far: "
                f"{[o['op'] for o in (v or {}).get('ops', [])]}; files named before: {list(self.state['files'])}"
            )
            if s
            else "FILE: none open yet"
        )
        try:
            r = self.planner._call(
                "fast", [{"role": "system", "content": CONVERT_SYSTEM}, {"role": "user", "content": f"{ctx}\nMESSAGE: {message}\nREQUEST: {clause}"}]
            )
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [
            o if "args" in o else {"op": o.get("op"), "args": {k: v_ for k, v_ in o.items() if k != "op"}}
            for o in d.get("ops") or []
            if isinstance(o, dict)
        ]
        ops = [o for o in ops if o.get("op") in KNOWN and isinstance(o.get("args") or {}, dict)]
        for o in ops:
            o["args"] = o.get("args") or {}
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- doing
    def _apply(self, ops, said, instead=False):
        lines = []
        for o in ops:
            self._turn["intents"].append(o["op"])
        rec = next((o for o in ops if o["op"] in ("record", "record_stop")), None)
        if rec:
            lines.append(self._record(rec))
        frames = [o for o in ops if o["op"] == "frames"]
        changes = [o for o in ops if o["op"] not in ("ask", "save", "record", "record_stop", "frames")]
        if (changes or frames) and not self.state["sources"]:
            return "\n".join(lines + ["Open a video or sound file first: name it, e.g. 'convert C:\\Videos\\holiday.mov to mp4'."])
        if changes:
            lines.append(self._change(changes, said, instead))
        for o in frames:
            lines.append(self._frames(o))
        for o in ops:
            if o["op"] == "ask":
                lines.append(self.answer(o["args"]))
            elif o["op"] == "save":
                lines.append(self.export(**o["args"]))
        return "\n".join(x for x in lines if x)

    def _merge(self, chain, changes, instead):
        chain = [json.loads(json.dumps(o)) for o in chain]
        for o in changes:
            k, a = o["op"], o.get("args") or {}
            if k == "rotate" and a.get("deg") == "other":  # 'the other way': the last turn reversed
                last = next((x for x in reversed(chain) if x["op"] == "rotate"), None)
                if last:
                    last["args"]["deg"] = (360 - int(last["args"].get("deg", 90))) % 360
                else:
                    chain.append({"op": "rotate", "args": {"deg": 270}})
                continue
            fam = next((f for f in FAMILIES if k in f), None)
            if fam:
                chain = [x for x in chain if x["op"] not in fam]
                chain.append({"op": k, "args": a})
            elif instead and any(x["op"] == k for x in chain):
                i = max(i for i, x in enumerate(chain) if x["op"] == k)
                chain[i] = {"op": k, "args": a}
            else:
                chain.append({"op": k, "args": a})
        return chain

    def _resolve_ops(self, chain):
        """Names in joins, sound files, logos and subtitles -> files on the disk (joined files become sources)."""
        sources = [self.src]
        for o in chain:
            a = o.get("args") or {}
            if o["op"] == "join":
                names = a.get("files") or []
                if names == "all":
                    names = [
                        n
                        for n in self.state["files"]
                        if Path(self.state["files"][n]) != Path(self.src["path"]) and Path(n).suffix.lower() in MD.VIDEO_EXTS
                    ]
                srcs = []
                for n in names:
                    p = self._resolve(n)
                    if not p:
                        raise P.PlanError(f"I can't find {n}")
                    sources.append(MD.probe(p))
                    srcs.append(len(sources) - 1)
                a["srcs"] = srcs
            for key in ("file",):
                if o["op"] in ("audio", "logo", "subtitles") and a.get(key):
                    p = self._resolve(a[key])
                    if not p:
                        raise P.PlanError(f"I can't find {a[key]}")
                    a[key] = p
        return sources

    def _change(self, changes, said, instead):
        v = self.cur()
        if not self.src.get("video") and any(o["op"] in PICTURE_OPS | {"gif", "frames"} for o in changes):
            return "It is sound only, so there is no picture to change."
        mode, want = P.settings(v["ops"])["mode"], _wants(changes)
        base = v
        if mode in ("audio", "gif", "webp") and want and want != mode and not (want == "picture" and mode in ("gif", "webp")):
            # a GIF or a sound file made from the video was asked for something only the video has: build on that video
            while base["parent"] >= 0 and P.settings(base["ops"])["mode"] != "video":
                base = self.state["versions"][base["parent"]]
        chain = self._merge(base["ops"], changes, instead)
        n = len(self.state["versions"])
        try:
            sources = self._resolve_ops(chain)
            r = E.render(chain, sources, self.folder, f"v{n}", log=self.log)
        except (P.PlanError, MD.MediaError, E.EncodeError, R.RecordError) as e:
            return f"Couldn't do that: {e}."
        if r["status"] == "no_gain":
            return (
                f"It is already compressed about as far as it goes: at the same look it would still be about {MD.human(r['predicted'])} "
                f"(it is {MD.human(r['est'])} now). Say e.g. 'under {max(1, int(r['est'] / 1e6 * 0.6))} MB' to squeeze it anyway, trading some quality."
            )
        p = r["probe"]
        nv = {
            "v": n,
            "ops": chain,
            "outputs": r["outputs"],
            "kind": r["kind"],
            "size": r["size"],
            "summary": MD.describe(p) if p else f"{len(r['outputs'])} files",
            "duration": (p or {}).get("duration"),
            "checks": r["checks"],
            "notes": r["notes"],
            "quality": r["quality"],
            "said": said,
            "parent": self.state["cur"],
            "when": _when(),
            "seconds": r["seconds"],
            "search": r.get("search"),
        }
        self.state["versions"].append(nv)
        self.state["cur"], self.state["redo"] = n, []
        made = self._words(nv)
        if base is not v:
            made = f"(Made from v{base['v']}, the video, not from the {'GIF' if mode in ('gif', 'webp') else 'sound file'} v{v['v']}.)\n" + made
        return made

    def _words(self, nv):
        src = self.src
        outs = nv["outputs"]
        if len(outs) > 1:
            parts = [MD.probe(f) for f in outs]
            head = f"v{nv['v']}: {len(outs)} parts - " + ", ".join(f"{MD.mmss(x['duration'])} ({MD.human(x['size'])})" for x in parts)
        else:
            p = MD.probe(outs[0])
            v, a = p.get("video"), p.get("audio")
            if v and nv["kind"] in ("gif", "webp"):
                what = f"{nv['kind'].upper()} {v['w']}x{v['h']}, {round(v['fps'])} fps"
            elif v:
                what = f"{v['w']}x{v['h']} at {v['fps']:g} fps, {MD.CODEC_WORDS.get(v['codec'], v['codec'])}" + (
                    f" + {MD.CODEC_WORDS.get(a['codec'], a['codec'])}" if a else ", no sound"
                )
            else:
                what = f"{MD.CODEC_WORDS.get(a['codec'], a['codec'])} sound, {round(p['bitrate'] / 1000)} kbps"
            change = ""
            whole = (
                src
                and abs(p["duration"] - src["duration"]) < max(2.0, src["duration"] * 0.03)
                and bool(v) == bool(src.get("video"))
                and nv["kind"] not in ("gif", "webp")
            )
            if whole and src["size"]:
                pct = (1 - p["size"] / src["size"]) * 100
                change = f" (was {MD.human(src['size'])}, {pct:.0f}% smaller)" if pct >= 1 else f" (was {MD.human(src['size'])})"
            head = f"v{nv['v']} ({Path(outs[0]).name}): {MD.mmss(p['duration'])}, {what}, {MD.human(p['size'])}{change}"
        if nv.get("quality") is not None:
            head += f"; looks {nv['quality']:.0f}/100 like the original"
        lines = [head + "."]
        parent = self.state["versions"][nv["parent"]] if nv["parent"] >= 0 else {"notes": []}
        new = [n for n in nv["notes"] if n not in parent.get("notes", [])]
        notes = [n for n in new if not n.startswith("made the picture as")] + [n for n in new if n.startswith("made the picture as")]
        if notes:
            lines.append(_cap(("; ".join(notes)) + "."))
        bad = [c for c in nv["checks"] if not c["ok"] and c["level"] == "fail"]
        warn = [c for c in nv["checks"] if not c["ok"] and c["level"] == "warn"]
        if bad:
            lines.append("Not right: " + "; ".join(f"{c['what']} ({c['detail']})" for c in bad) + ".")
        if warn:
            lines.append("Note: " + "; ".join(f"{c['what']}: {c['detail']}" for c in warn) + ".")
        if not bad:
            ok = [c["what"] for c in nv["checks"] if c["ok"]]
            if ok:
                lines.append("Checked: " + ", ".join(ok[:6]) + ".")
        tgt = next((o["args"].get("name") for o in nv["ops"] if o["op"] == "target"), None)
        note = (PRESETS.get(tgt) or {}).get("note")
        if note and tgt not in self.state["said_notes"]:
            self.state["said_notes"].append(tgt)
            lines.append(note)
        return "\n".join(lines)

    def _frames(self, o):
        v = self.cur()
        chain = [
            x for x in v["ops"] if x["op"] not in ("format", "extract_audio", "gif", "video", "compress", "quality", "target", "codec", "split")
        ] + [o]
        k = len(self.state["extras"]) + 1
        try:
            r = E.render(chain, self._resolve_ops(chain), self.folder, f"pictures{k}", log=self.log)
        except (P.PlanError, MD.MediaError, E.EncodeError) as e:
            return f"Couldn't do that: {e}."
        self.state["extras"].append({"kind": "pictures", "files": r["outputs"], "said": self._turn["user"], "when": _when()})
        files = r["outputs"]
        where = Path(files[0]).parent if files else self.folder
        bad = [c for c in r["checks"] if not c["ok"]]
        if len(files) == 1:
            p = MD.probe(files[0]).get("video") or {}
            return f"Saved {Path(files[0]).name} ({p.get('w')}x{p.get('h')}) in {where}." + (f" Not right: {bad[0]['detail']}." if bad else "")
        return f"Saved {len(files)} pictures in {where}." + (f" Not right: {bad[0]['detail']}." if bad else "")

    # ---------------------------------------------------------------- screen recording
    def _record(self, o):
        a = o.get("args") or {}
        if o["op"] == "record_stop":
            rec = self.state.get("recording")
            if not rec:
                return "Nothing is being recorded."
            try:
                path = R.stop(rec)
            except R.RecordError as e:
                self.state["recording"] = None
                return f"Couldn't finish the recording: {e}."
            self.state["recording"] = None
            return self._recorded(path, rec)
        if self.state.get("recording") and R.running(self.state["recording"]):
            return "It is already recording; say 'stop recording' first."
        try:
            rec = R.start(self.folder, seconds=a.get("seconds"), mic=bool(a.get("mic")), screen=a.get("screen") or 1)
        except R.RecordError as e:
            return f"Couldn't record: {e}."
        if a.get("seconds"):
            try:
                path = R.wait_for(rec)
            except R.RecordError as e:
                return f"Couldn't finish the recording: {e}."
            return self._recorded(path, rec)
        self.state["recording"] = rec
        return f"Recording screen {rec['screen']}" + (" with the microphone" if rec.get("mic") else "") + ". Say 'stop recording' when you are done."

    def _recorded(self, path, rec):
        self._open(Path(path))
        p = self.src
        mic = " with the microphone" if rec.get("mic") else " (no sound)" if not p.get("audio") else ""
        return (
            f"Recorded {MD.mmss(p['duration'])} of screen {rec['screen']}{mic}: {Path(path).name}, {p['video']['w']}x{p['video']['h']}, "
            f"{MD.human(p['size'])}. Say what to do with it, e.g. 'cut the first 3 seconds', 'make it a GIF' or 'save it to my desktop'."
        )

    # ---------------------------------------------------------------- answers
    def answer(self, a):
        what = a.get("what", "info")
        v, s = self.cur(), self.src
        if not s:
            return "No file is open yet."
        cur_p = MD.probe(v["outputs"][0]) if v["v"] and len(v["outputs"]) == 1 and v["kind"] != "frames" else s
        if what == "info":
            return MD.describe(cur_p) + ("" if cur_p is s else f"\nThe original: {MD.describe(s)}")
        if what == "compat":
            key = a.get("target") or "everywhere"
            label = PRESETS[key]["label"]
            found = issues(cur_p, key)
            if not found:
                return f"Yes: {cur_p['name']} should work for {label} as it is."
            fixes = [x["why"] for x in found if x["level"] == "fix"]
            minor = [x["why"] for x in found if x["level"] == "minor"]
            say = f"say 'make it ready for {label.replace('a ', '').replace('an ', '')}'" if key != "everywhere" else "say 'make it play everywhere'"
            if not fixes:
                return f"Mostly yes for {label}, but {'; '.join(minor)}. To be safe, {say}."
            return f"Not as it is, for {label}: {'; '.join(fixes + minor)}. {_cap(say)} and I'll fix that."
        if what == "quality":
            if v["v"] and v.get("quality") is not None:
                q = v["quality"]
                word = (
                    "hard to tell apart from the original"
                    if q >= 93
                    else "close to the original"
                    if q >= 85
                    else "a little softer than the original"
                    if q >= 75
                    else "visibly worse than the original"
                )
                return f"v{v['v']} looks {q:.0f}/100 like the original (VMAF): {word}."
            vv = cur_p.get("video")
            if not vv:
                a_ = cur_p.get("audio") or {}
                return f"It is sound only: {MD.CODEC_WORDS.get(a_.get('codec'), a_.get('codec'))} at about {round((a_.get('bitrate') or cur_p['bitrate']) / 1000)} kbps."
            bpp = cur_p["bitrate"] / max(1, vv["w"] * vv["h"] * (vv["fps"] or 30))
            word = "plenty of detail kept" if bpp > 0.12 else "normal for its size" if bpp > 0.05 else "quite compressed already"
            return (
                f"{cur_p['name']}: {vv['w']}x{vv['h']} at {cur_p['bitrate'] / 1e6:.1f} Mbps - {word}. (Only changed versions get a measured score.)"
            )
        if what == "compare":
            if not v["v"]:
                return "Nothing has been changed yet: this is the original."
            lines = [f"Original: {MD.describe(s)}", f"v{v['v']}: {v['summary']}"]
            if v.get("quality") is not None:
                lines.append(f"It looks {v['quality']:.0f}/100 like the original.")
            return "\n".join(lines)
        if what == "where":
            files = v["outputs"] if v["v"] else [s["path"]]
            ex = [e["path"] for e in self.state["exports"][-3:]]
            return "Now: " + ", ".join(files) + (f"\nSaved copies: {', '.join(ex)}" if ex else "")
        return MD.describe(cur_p)

    # ---------------------------------------------------------------- saving
    def export(self, where=None, name=None):
        v, s = self.cur(), self.src
        if not s:
            return "No file is open yet."
        if not v["v"] and not self.state["extras"]:
            return "Nothing has been changed yet, so there is nothing new to save (the original is untouched)."
        if where in (None, "original", ""):
            dest = Path(s["path"]).parent
        else:
            from ai_pc.windows import fs as WF

            dest = WF.known(
                {
                    "download": "downloads",
                    "document": "documents",
                    "video": "videos",
                    "picture": "pictures",
                    "photo": "pictures",
                    "photos": "pictures",
                }.get(where, where)
            )
            if not dest:
                return f"I don't know the folder '{where}'."
        files = v["outputs"] if v["v"] else []
        if not files and self.state["extras"]:
            files = self.state["extras"][-1]["files"]
        label = self._label(v)
        saved = []
        for k, f in enumerate(files):
            f = Path(f)
            if name and len(files) == 1:
                target = dest / name
            elif len(files) == 1:
                target = dest / f"{Path(s['name']).stem} ({label}){f.suffix}"
            else:
                target = dest / f"{Path(s['name']).stem} ({label} {k + 1}){f.suffix}"
            target = _unique(target)
            shutil.copy2(f, target)
            ok = target.exists() and target.stat().st_size == f.stat().st_size
            saved.append((target, ok))
            self.state["exports"].append({"path": str(target), "v": v["v"], "when": _when(), "ok": ok})
        if not saved:
            return "There is nothing to save."
        bad = [str(t) for t, ok in saved if not ok]
        if bad:
            return f"Saving went wrong for {', '.join(bad)}."
        return f"Saved to {saved[0][0]}" if len(saved) == 1 else f"Saved {len(saved)} files to {dest}"

    def _label(self, v):
        ops = v["ops"]
        for o in reversed(ops):
            k, a = o["op"], o["args"]
            if k == "target":
                return PRESETS[a["name"]]["label"].replace("a ", "").replace("an ", "").split(" (")[0]
            if k == "compress" and a.get("max_mb"):
                return f"under {a['max_mb']:g} MB"
            if k == "compress":
                return "smaller"
            if k == "gif":
                return "gif"
            if k == "extract_audio" or (k == "format" and a.get("to") in ("mp3", "wav", "m4a", "aac", "flac", "ogg", "opus")):
                return "sound"
            if k == "resize" and a.get("height"):
                return f"{a['height']}p"
            if k in ("trim", "cut"):
                return "cut"
            if k == "join":
                return "joined"
        return f"v{v['v']}"

    # ---------------------------------------------------------------- versions
    def undo(self):
        v = self.cur()
        if not v or v["parent"] < 0:
            return "There is nothing to undo."
        self.state["redo"].append(self.state["cur"])
        self.state["cur"] = v["parent"]
        return f"Back to v{self.state['cur']}: {self.cur()['summary']}"

    def redo(self):
        if not self.state["redo"]:
            return "There is nothing to redo."
        self.state["cur"] = self.state["redo"].pop()
        return f"Again v{self.state['cur']}: {self.cur()['summary']}"

    def goto(self, n):
        if not 0 <= n < len(self.state["versions"]):
            return f"There is no v{n} (there are v0 to v{len(self.state['versions']) - 1})."
        self.state["cur"], self.state["redo"] = n, []
        return f"Now v{n}: {self.cur()['summary']}"

    def history(self):
        if not self.state["versions"]:
            return "No file is open yet."
        return "\n".join(f"{'*' if v['v'] == self.state['cur'] else ' '} v{v['v']}: {v['said']} -> {v['summary']}" for v in self.state["versions"])


def _wants(changes):
    """What kind of file new changes ask for: 'audio', 'gif', 'video', 'picture' (changes to the frame) or None."""
    ks = {o["op"] for o in changes}
    to = {(o.get("args") or {}).get("to") for o in changes if o["op"] == "format"}
    if "extract_audio" in ks or to & AUDIO_ONLY:
        return "audio"
    if "gif" in ks or to & {"gif", "webp"}:
        return "gif"
    if ks & {"target", "video", "codec", "split", "join"} or to & VIDEO_CONTAINERS:
        return "video"
    if ks & PICTURE_OPS:
        return "picture"
    return None


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


def _unique(dst):
    dst = Path(dst)
    if not dst.exists():
        return dst
    k = 2
    while True:
        cand = dst.with_name(f"{dst.stem} ({k}){dst.suffix}")
        if not cand.exists():
            return cand
        k += 1

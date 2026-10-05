"""A conversation about a recording or a video's sound. Every message makes one version; every change is measured.

  c = SoundChat.start("interview.mp4")        the original is never changed: versions live in the chat's folder
  c.say("clean it up")                        -> the steps it needed and why, each with its measure ("50 Hz hum 39 -> 2 dB")
  c.say("remove the long pauses and the ums") -> a talking video is cut the same way (jump cuts), captions follow
  c.say("add word by word captions in yellow") / c.say("export the video")
  c.say("add music.mp3 under my voice") / c.say("make the music quieter") / c.say("normalize for youtube instead")
  c.say("undo") / c.say("go back to v1") / c.say("how loud is it?") / c.say("save as mp3 under 5 MB")
"""
import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path

from ..config import ROOT
from ..util import parse_json
from . import captions as C
from . import measure as M
from . import ops as O
from .soundparse import parse

CHATS = ROOT / "out" / "sound" / "chats"
UNDO = re.compile(r"^\s*(?:undo|revert|go back|take (?:that|it) back|undo (?:that|it|the last (?:change|one)))\b(?!.*\bv\d)", re.I)
REDO = re.compile(r"^\s*redo\b", re.I)
GOTO = re.compile(r"\b(?:go back to|back to|restore|use|switch to)\s+(?:version\s*|v)(\d+)\b|\bback to the original\b|^\s*(?:the )?original\s*$", re.I)
HISTORY = re.compile(r"^\s*(?:history|versions|show (?:me )?(?:the )?(?:history|versions))\b", re.I)
SPLIT = re.compile(r"(?<=[.!?;])\s+|,?\s+(?:and then|then|and also|also|after that)\s+|,?\s+and\s+(?=(?:make|remove|cut|add|put|take|reduce|fade|speed|slow|normali[sz]e|"
                   r"save|export|convert|give|burn|clean|trim|keep|turn|lower|raise|boost|tighten|shorten|change|fix)\b)", re.I)
FAMILIES = [{"normalize"}, {"denoise"}, {"speed"}, {"pitch"}, {"music"}, {"fade"}, {"volume"}, {"echo", "reverb", "telephone"}, {"tighten"}, {"compress"},
            {"deess"}, {"dehum"}, {"highpass"}, {"clean"}, {"mono", "stereo"}]
SOUND_SYSTEM = """You turn a person's request about a recording (or a video's sound) into changes for a program. Reply with ONE JSON object:
{"ops": [...]} or {"ask": "<short question back>"}. Each op is {"op": NAME, "args": {...}}:
 clean {"platform": "youtube|podcast|..."}   denoise {"strength": "light|medium|strong"}   dehum {"hz": 50}   highpass {"hz": 80}   deess {}   declick {}
 declip {}   compress {"amount": "light|medium|strong"}   normalize {"platform": "youtube|podcast|spotify|broadcast|whatsapp"} or {"lufs": -16}
 volume {"db": 6}   trim {"start": s} or {"end": s} or {"drop_end": s}   cut {"ranges": [[s, e]]}   keep {"start": s, "end": e}
 fade {"in": s, "out": s}   tighten {"max_pause": 0.5}   fillers {}   speed {"factor": 1.25}   pitch {"semitones": -3}
 music {"file": "<name>", "below": 18}   music_level {"by": -6}   join {"file": "<name>", "before": false}   echo {}   reverb {}   telephone {}   mono {}   stereo {}
 captions {"kind": "clean|bold|karaoke|boxed", "color": "white|yellow|...", "position": "bottom|middle|top", "size_by": 1.25}
 fix_words {"old": "...", "new": "..."}
 export {"fmt": "mp3|wav|m4a|ogg|flac|mp4|srt|vtt|txt|docx", "max_mb": 5, "burn": true}
 ask {"what": "loudness|quality|length|transcript|language|compare"}
Times are seconds. Do only what was asked."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


def _mmss(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:04.1f}"


class SoundChat:
    def __init__(self, state, planner=None, log=print):
        self.state, self.planner, self.log = state, planner, log
        self.folder = Path(state["folder"])
        self._m = {}  # measures per version file (not saved)
        self.last_turn = None

    # ---------------------------------------------------------------- start / load
    @classmethod
    def start(cls, src=None, chats_dir=None, planner=None, log=print, files=None):
        stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(src).stem)[:24].strip("_").lower() if src else "voiceover"
        cid = f"sound_{stem}_{time.strftime('%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        k = 2
        while folder.exists():
            folder = Path(chats_dir or CHATS) / f"{cid}_{k}"
            k += 1
        folder.mkdir(parents=True)
        state = {"id": folder.name, "folder": str(folder), "src": None, "probe": None, "versions": [], "cur": -1, "redo": [], "turns": [], "exports": [],
                 "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in (files or [])}}
        c = cls(state, planner=planner, log=log)
        if src:
            c._open(Path(src).resolve())
        c.save()
        return c

    def _open(self, src):
        if not src.is_file():
            raise FileNotFoundError(src)
        p = M.probe(src)
        if not p["audio"]:
            raise ValueError(f"{src.name} has no sound")
        v0 = self.folder / "v0.wav"
        O.ff([src], v0, extra=["-ac", str(min(2, p["audio"]["channels"]))])
        self.state.update(src=str(src), probe=p)
        m = self._measure(v0)
        self.state["versions"] = [{"v": 0, "ops": [], "wav": str(v0), "timeline": {"keep": [[0.0, m["duration"]]], "speed": 1.0}, "captions": None,
                                   "checks": [], "said": "(the original)", "summary": _summary(m), "parent": -1, "when": _when()}]
        self.state["cur"] = 0

    @classmethod
    def load(cls, cid, chats_dir=None, planner=None, log=print):
        return cls(json.loads((Path(chats_dir or CHATS) / cid / "chat.json").read_text(encoding="utf-8")), planner=planner, log=log)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def cur(self):
        return self.state["versions"][self.state["cur"]] if self.state["cur"] >= 0 else None

    def _measure(self, wav, op=None):
        key = (str(wav), op)
        if key not in self._m:
            self._m[key] = O.describe(wav, op)
        return self._m[key]

    @property
    def video(self):
        return (self.state.get("probe") or {}).get("video")

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
            ops = []
            ctx = {"has_video": bool(self.video), "has_captions": bool((self.cur() or {}).get("captions")), "files": self.state["files"]}
            instead = bool(re.search(r"\binstead\b", message, re.I))
            whole = re.match(r"^\s*(?:make a |create a |record a )?(?:voice[- ]?over|read (?:this|it|the following) (?:out|aloud)|say)\s*[:\-]", message, re.I)
            for cl in ([message] if whole else [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")]) or [message]:  # a script is one piece
                r = parse(cl, ctx)
                if not r["ops"]:
                    r2 = self._llm(cl, message) if (self.planner is not None or not r.get("ask")) else {"ops": []}
                    r = r2 if (r2["ops"] or not r.get("ask")) else r
                if r.get("ask") and not r["ops"]:
                    out.append(r["ask"])
                    ops = []
                    break
                ops += r["ops"]
            if ops:
                out.append(self._apply(ops, message, instead))
        reply = "\n".join(x for x in out if x).strip() or ("Tell me what to do with the sound, e.g. 'clean it up', 'remove the long pauses', "
                                                          "'add captions', 'save as mp3'.")
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), v_to=self.state["cur"])
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, clause, message):
        if self.planner is None:
            return {"ops": [], "ask": f"I could not read '{clause}'. Try e.g. 'clean it up', 'remove the hum', 'cut the first 5 seconds', 'add captions'."}
        self._turn["llm"] = True
        v = self.cur()
        ctx = (f"RECORDING: {_mmss(v['summary']['duration'])} long, {v['summary']['lufs']:.0f} LUFS, video: {bool(self.video)}, captions: {bool(v.get('captions'))}, "
               f"done so far: {[o['op'] for o in v['ops']]}, files named before: {list(self.state['files'])}") if v else "RECORDING: none yet"
        try:
            r = self.planner._call("fast", [{"role": "system", "content": SOUND_SYSTEM},
                                            {"role": "user", "content": f"{ctx}\nMESSAGE: {message}\nREQUEST: {clause}"}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        known = set(O.OPS) | {"music_level", "captions", "fix_words", "export", "ask", "voiceover"}
        ops = [o if "args" in o else {"op": o.get("op"), "args": {k: v_ for k, v_ in o.items() if k != "op"}} for o in d.get("ops") or [] if isinstance(o, dict)]
        ops = [o for o in ops if o.get("op") in known]
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- doing
    def _apply(self, ops, said, instead=False):
        lines = []
        if not self.state["versions"] and not any(o["op"] == "voiceover" for o in ops):
            return "Open a recording or a video first (or say 'voice-over: <your text>')."
        sound_ops = [o for o in ops if o["op"] in O.OPS or o["op"] in ("music_level", "voiceover")]
        if sound_ops:
            lines.append(self._sound(sound_ops, said, instead))
        for o in ops:
            k, a = o["op"], o.get("args") or {}
            self._turn["intents"].append(k)
            if k == "captions":
                lines.append(self._captions(a, said))
            elif k == "fix_words":
                lines.append(self._fix_words(a, said))
            elif k == "export":
                lines.append(self.export(**a))
            elif k == "ask":
                lines.append(self.answer(a.get("what", "quality")))
        return "\n".join(x for x in lines if x)

    def _sound(self, ops, said, instead):
        v = self.cur()
        if any(o["op"] == "voiceover" for o in ops):
            return self._voiceover(next(o for o in ops if o["op"] == "voiceover")["args"], said)
        chain = [dict(o) for o in v["ops"]]
        replay = False
        for o in ops:
            if o["op"] == "music_level":
                mus = next((x for x in reversed(chain) if x["op"] == "music"), None)
                if mus is None:
                    return "There is no music in it yet: say e.g. 'add music.mp3 under my voice'."
                mus["args"] = dict(mus["args"], below=max(4, mus["args"].get("below", 18) - o["args"].get("by", 6)))
                replay = True
                continue
            fam = next((f for f in FAMILIES if o["op"] in f), {o["op"]})
            old = next((i for i in range(len(chain) - 1, -1, -1) if chain[i]["op"] in fam), None)
            if instead and old is not None:
                chain[old] = dict(o)
                replay = True
            elif self.video and o["op"] == "join":
                return "Joining another recording to a video's sound would leave the picture short; save the sound first ('save as mp3'), then join."
            else:
                chain.append(dict(o))
        try:
            nv = self._build(chain, said, replay=replay)
        except (O.OpError, ValueError, KeyError) as e:
            return f"Couldn't do that: {e}."
        return self._words(nv, v)

    def _build(self, chain, said, replay=False):
        """The next version: the new changes on top of the current file, or the whole chain again from the original
        when an earlier change was swapped ('instead')."""
        v = self.cur()
        n = len(self.state["versions"])
        base = self.state["versions"][0]
        if replay:  # start from the version that already holds the longest unchanged run of the chain
            key = [json.dumps(o, sort_keys=True) for o in chain]
            best = max((x for x in self.state["versions"] if Path(x["wav"]).exists() and len(x["ops"]) <= len(chain)
                        and [json.dumps(o, sort_keys=True) for o in x["ops"]] == key[:len(x["ops"])]), key=lambda x: len(x["ops"]), default=base)
            base = best
        start = len(base["ops"]) if replay else len(v["ops"])
        cur_wav = Path(base["wav"] if replay else v["wav"])
        timeline = dict(base["timeline"] if replay else v["timeline"])
        caps = None if replay else (json.loads(json.dumps(v["captions"])) if v.get("captions") else None)
        if replay and v.get("captions"):
            caps = json.loads(json.dumps(v["captions"]))
            if any(o["op"] in O.TIME_OPS for o in chain[start:]) or any(o["op"] in O.TIME_OPS for o in v["ops"][start:]):
                caps["_rebuild"] = True  # the timing under the captions changed: they are heard again at the end
        steps, checks = [], []
        for k, o in enumerate(chain[start:]):
            dst = self.folder / f"v{n}_{k}.wav"
            before = self._measure(cur_wav, o["op"])
            info = O.run(o["op"], cur_wav, dst, o.get("args") or {}, before)
            after = self._measure(dst, o["op"])
            chk = O.check(o["op"], before, after, o.get("args") or {}, info)
            steps.append({"op": o["op"], "args": o.get("args") or {}, "info": {k_: v_ for k_, v_ in info.items() if k_ not in ("voice_pauses",)},
                          "before": _summary(before), "after": _summary(after)})
            checks += chk
            if o["op"] in O.TIME_OPS and "keep" in info:
                timeline = _compose(timeline, info["keep"], info.get("speed", 1.0))
                if caps and not caps.get("_rebuild"):
                    caps["cues"] = C.remap(caps["cues"], info["keep"], info.get("speed", 1.0))
            cur_wav = dst
        final = self.folder / f"v{n}.wav"
        shutil.move(str(cur_wav), final) if cur_wav != Path(base["wav"]) and cur_wav != Path(v["wav"]) else shutil.copy(cur_wav, final)
        for f in self.folder.glob(f"v{n}_*.wav"):
            f.unlink(missing_ok=True)
        m = self._measure(final)
        if caps and caps.get("_rebuild"):  # the timing changed under the captions: hear them again
            caps = self._make_captions(final, caps.get("style") or {}, lang=caps.get("lang"))
        nv = {"v": n, "ops": chain, "wav": str(final), "timeline": timeline, "captions": caps, "checks": checks, "steps": steps, "said": said,
              "summary": _summary(m), "parent": self.state["cur"], "when": _when()}
        self.state["versions"].append(nv)
        self.state["cur"] = n
        self.state["redo"] = []
        return nv

    def _words(self, nv, before):
        parts = []
        for s in nv.get("steps", []):
            parts.append(_step_words(s))
        bad = [c for c in nv["checks"] if not c["ok"] and c["level"] == "fail"]
        warn = [c for c in nv["checks"] if not c["ok"] and c["level"] == "warn"]
        ck = f"checked {len(nv['checks']) - len(bad) - len(warn)}/{len(nv['checks'])}" + (f"; not right: {'; '.join(c['what'] for c in bad[:3])}" if bad else "") + \
            (f"; to look at: {'; '.join(c['what'] for c in warn[:2])}" if warn else "")
        cap = f" Captions moved with the cuts ({len(nv['captions']['cues'])} lines)." if nv.get("captions") and before.get("captions") and \
            nv["summary"]["duration"] != before["summary"]["duration"] else ""
        vid = " The video will be cut the same way when you export it." if self.video and nv["timeline"] != before["timeline"] else ""
        return f"v{nv['v']}: " + " ".join(parts) + cap + vid + f" ({ck})"

    def _voiceover(self, a, said):
        from . import tts
        tmp = self.folder / "voiceover_tts.wav"
        info = tts.speak(a["text"], tmp, voice=a.get("voice"))
        if not self.state["versions"]:
            self._open(tmp)
            self.state["versions"][0]["said"] = said
            m = self.state["versions"][0]["summary"]
            return f"v0: a voice-over ({info['voice'].replace('Microsoft ', '').replace(' Desktop', '')}), {_mmss(m['duration'])} long. Say 'save as mp3' or 'add music.mp3 under it'."
        return self._sound([{"op": "join", "args": {"file": str(tmp)}}], said, False)

    # ---------------------------------------------------------------- captions
    def _make_captions(self, wav, style, lang=None):
        words = O.transcribe_words(wav, language="en")  # captions are in English
        st = dict(C.default_style(self.video), **{k: v for k, v in style.items() if k not in ("size_by",)})
        cues = C.make_cues(words, st)
        return {"cues": cues, "style": st, "lang": lang, "words": len(words), "checks": C.check_cues(cues, words, st), "_words": words}

    def _captions(self, a, said):
        v = self.cur()
        if a.get("remove"):
            nv = dict(json.loads(json.dumps(v)), captions=None, said=said, parent=self.state["cur"], checks=[], steps=[])
            return self._push(nv, "Captions taken off.")
        if v.get("captions") and not (set(a) - {"kind", "color", "highlight", "position", "size_by", "upper"}) and a:
            st = dict(v["captions"]["style"])
            if a.get("size_by"):
                st["size"] = round(float(st.get("size", 1.0)) * a["size_by"], 3)
            st.update({k: val for k, val in a.items() if k != "size_by"})
            if a.get("kind") == "bold" and "upper" not in a:
                st["upper"] = True
            words = v["captions"].get("_words") or [w for c in v["captions"]["cues"] for w in c["words"]]
            cues = C.make_cues(words, st) if a.get("kind") or "upper" in a else v["captions"]["cues"]
            caps = dict(v["captions"], style=st, cues=cues, checks=C.check_cues(cues, words, st))
            nv = dict(json.loads(json.dumps(v)), captions=caps, said=said, parent=self.state["cur"], checks=caps["checks"], steps=[])
            return self._push(nv, f"Captions restyled: {_style_words(st)}." + _cap_check_words(caps["checks"]))
        st = {k: val for k, val in a.items() if k != "size_by"}
        if a.get("size_by"):
            st["size"] = a["size_by"]
        caps = self._make_captions(v["wav"], st)
        if not caps["cues"]:
            return "No speech was heard, so there is nothing to caption."
        nv = dict(json.loads(json.dumps(v)), captions=caps, said=said, parent=self.state["cur"], checks=caps["checks"], steps=[])
        first = " / ".join(c["text"] for c in caps["cues"][:3])
        return self._push(nv, f"Captions: {len(caps['cues'])} lines from {caps['words']} words ({_style_words(caps['style'])}). First: \"{first[:140]}\"."
                          + _cap_check_words(caps["checks"]) + (" Say 'export the video' to burn them in, or 'save the srt'." if self.video else " Say 'save the srt'."))

    def _push(self, nv, words):
        n = len(self.state["versions"])
        nv["v"] = n
        nv["when"] = _when()
        self.state["versions"].append(nv)
        self.state["cur"] = n
        self.state["redo"] = []
        return f"v{n}: {words}"

    def _fix_words(self, a, said):
        v = self.cur()
        if not v.get("captions"):
            return "There are no captions yet."
        old, new = a["old"].strip(), a["new"].strip()
        n = 0
        cues = []
        for c in v["captions"]["cues"]:
            t, k = re.subn(re.escape(old), new, c["text"], flags=re.I)
            n += k
            if k:
                ws = t.split()
                span = (c["end"] - c["start"]) / max(1, len(ws))
                c = dict(c, text=t, lines=C._balance(t) if len(c["lines"]) > 1 or len(t) > 42 else [t],
                         words=[{"w": w, "start": round(c["start"] + i * span, 3), "end": round(c["start"] + (i + 1) * span, 3)} for i, w in enumerate(ws)])
            cues.append(c)
        if not n:
            return f"'{old}' is not in the captions."
        caps = dict(v["captions"], cues=cues, _words=[w for c in cues for w in c["words"]])  # the corrected words are the reference now
        nv = dict(json.loads(json.dumps(v, default=str)), captions=caps, said=said, parent=self.state["cur"], checks=[], steps=[])
        return self._push(nv, f"'{old}' -> '{new}' in {n} place(s).")

    # ---------------------------------------------------------------- saving
    def export(self, fmt="mp3", max_mb=None, burn=True, kbps=None, **kw):
        v = self.cur()
        if v is None:
            return "Nothing to save yet."
        out_dir = self.folder / "exports"
        out_dir.mkdir(exist_ok=True)
        stem = (Path(self.state["src"]).stem if self.state.get("src") else "voiceover") + f" v{v['v']}"
        if fmt in ("srt", "vtt", "ass", "txt", "docx"):
            return self._export_text(fmt, v, out_dir, stem)
        if fmt == "mp4":
            if not self.video:
                return "This is a recording without a picture; say 'save as mp3' (or 'wav', 'm4a')."
            return self._export_video(v, out_dir, stem, burn and bool(v.get("captions")))
        if kw.get("for") == "whatsapp" and fmt == "ogg":
            fmt = "mp3"
        codec = {"mp3": ["-c:a", "libmp3lame"], "wav": ["-c:a", "pcm_s16le"], "m4a": ["-c:a", "aac"], "ogg": ["-c:a", "libopus"], "opus": ["-c:a", "libopus"],
                 "flac": ["-c:a", "flac"]}.get(fmt)
        if codec is None:
            return f"I can save mp3, wav, m4a, ogg, opus or flac (not {fmt})."
        dur = v["summary"]["duration"]
        rate = kbps or (128 if kw.get("for") == "whatsapp" else 192 if fmt in ("mp3", "m4a") else 96)
        if max_mb and fmt not in ("wav", "flac"):
            rate = int(min(rate, max(24, max_mb * 8 * 1024 / dur * 0.94)))
        args = ["ffmpeg", "-v", "error", "-y", "-i", v["wav"]] + codec + ([] if fmt in ("wav", "flac") else ["-b:a", f"{rate}k"]) + \
            (["-ac", "1"] if kw.get("for") == "whatsapp" else []) + (["-ar", "48000"] if fmt in ("ogg", "opus") else ["-ar", "44100"])
        dst = out_dir / f"{stem}.{fmt}"
        code, _, err = M.run(args + [str(dst)])
        if code:
            return f"Couldn't save: {err[-200:]}"
        p = M.probe(dst)
        size = dst.stat().st_size / 1024 / 1024
        chk = [{"ok": abs(p["duration"] - dur) <= 0.15, "what": f"{_mmss(p['duration'])} long", "level": "fail"}]
        if max_mb:
            chk.append({"ok": size <= max_mb, "what": f"{size:.2f} MB (at most {max_mb:g})", "level": "fail"})
        self.state["exports"].append({"path": str(dst), "v": v["v"], "fmt": fmt})
        bad = [c["what"] for c in chk if not c["ok"]]
        return f"Saved {dst} ({size:.2f} MB, {rate if fmt not in ('wav', 'flac') else 'lossless'}{'k' if fmt not in ('wav', 'flac') else ''})" + \
            (f"; not right: {'; '.join(bad)}" if bad else "") + "."

    def _export_text(self, fmt, v, out_dir, stem):
        caps = v.get("captions")
        if fmt in ("srt", "vtt", "ass") and not caps:
            caps_msg = self._captions({}, "(captions for saving)")
            v = self.cur()
            caps = v.get("captions")
            if not caps:
                return caps_msg
        if fmt in ("txt", "docx"):
            if caps:
                cues = caps["cues"]
            else:
                words = O.transcribe_words(v["wav"])
                cues = C.make_cues(words, {"kind": "clean"})
            dst = out_dir / f"{stem} transcript.{fmt}"
            if fmt == "txt":
                dst.write_text("\n".join(f"[{_mmss(c['start'])}] {c['text']}" for c in cues) + "\n", encoding="utf-8")
            else:
                from docx import Document
                d = Document()
                d.add_heading(f"Transcript: {Path(self.state['src']).name if self.state.get('src') else 'voice-over'}", 1)
                d.add_paragraph(f"{_mmss(v['summary']['duration'])} long. Made {dt.date.today():%d %b %Y}.")
                for c in cues:
                    p = d.add_paragraph()
                    p.add_run(f"[{_mmss(c['start'])}] ").bold = True
                    p.add_run(c["text"])
                d.save(dst)
            self.state["exports"].append({"path": str(dst), "v": v["v"], "fmt": fmt})
            return f"Saved {dst} ({len(cues)} lines)."
        files = C.write(caps["cues"], caps["style"], out_dir, stem, self.video)
        for k in ("srt", "vtt", "ass"):
            if k != fmt:
                Path(files[k]).unlink(missing_ok=True)
        self.state["exports"].append({"path": files[fmt], "v": v["v"], "fmt": fmt})
        return f"Saved {files[fmt]} ({len(caps['cues'])} captions)."

    def _export_video(self, v, out_dir, stem, burn):
        src = Path(self.state["src"])
        tl = v["timeline"]
        whole = len(tl["keep"]) == 1 and abs(tl["keep"][0][0]) < 0.01 and abs(tl["keep"][0][1] - self.state["versions"][0]["summary"]["duration"]) < 0.05 \
            and abs(tl["speed"] - 1) < 1e-6
        dst = out_dir / f"{stem}.mp4"
        work = out_dir / "_burn"
        work.mkdir(exist_ok=True)
        args = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", v["wav"]]
        chain = []
        if not whole:
            segs = tl["keep"]
            chain.append(";".join(f"[0:v]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS[v{i}]" for i, (a, b) in enumerate(segs)) + ";" +
                         "".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[vc]")
            last = "vc"
            if abs(tl["speed"] - 1) > 1e-6:
                chain.append(f"[{last}]setpts=PTS/{tl['speed']:.5f}[vs]")
                last = "vs"
        else:
            last = "0:v"
        if burn:
            files = C.write(v["captions"]["cues"], v["captions"]["style"], work, "caps", self.video)
            C.copy_fonts(work)
            chain.append(f"[{last}]subtitles=caps.ass" + (":fontsdir=." if C.fonts_dir() else "") + "[vo]")
            last = "vo"
        if chain:
            args += ["-filter_complex", ";".join(chain), "-map", f"[{last}]"]
            vcodec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        else:
            args += ["-map", "0:v"]
            vcodec = ["-c:v", "copy"]
        args += ["-map", "1:a"] + vcodec + ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dst)]
        t0 = time.perf_counter()
        import subprocess
        r = subprocess.run(args, cwd=str(work), capture_output=True, creationflags=M.NO_WINDOW)
        if r.returncode:
            return f"Couldn't make the video: {r.stderr.decode('utf-8', 'replace')[-300:]}"
        p = M.probe(dst)
        adur = v["summary"]["duration"]
        chk = [{"ok": p["video"] is not None and abs(p["duration"] - adur) <= 0.2, "what": f"picture and sound together, {_mmss(p['duration'])} long", "level": "fail"}]
        if burn:
            def src_time(t):
                acc = 0.0
                for a, b in tl["keep"]:
                    d = (b - a) / tl["speed"]
                    if t <= acc + d:
                        return a + (t - acc) * tl["speed"]
                    acc += d
                return tl["keep"][-1][1]
            chk += C.check_burn(src, dst, v["captions"]["cues"], v["captions"]["style"], src_time)
        shutil.rmtree(work, ignore_errors=True)
        self.state["exports"].append({"path": str(dst), "v": v["v"], "fmt": "mp4", "checks": chk})
        bad = [c["what"] for c in chk if not c["ok"]]
        return (f"Saved {dst} ({dst.stat().st_size / 1024 / 1024:.1f} MB, {time.perf_counter() - t0:.0f} s to make" + (", captions burned in" if burn else "") +
                (", cut to match the sound" if not whole else "") + f"). checked {sum(c['ok'] for c in chk)}/{len(chk)}" + (f"; not right: {'; '.join(bad)}" if bad else "") + ".")

    # ---------------------------------------------------------------- answers
    def answer(self, what):
        v = self.cur()
        if v is None:
            return "Nothing is open yet."
        m = self._measure(Path(v["wav"]))
        if what == "loudness":
            yt = -14 - m["lufs"]
            return (f"{m['lufs']:.1f} LUFS (true peak {m['true_peak']} dBTP). YouTube and Spotify play at -14 LUFS, so it would be turned "
                    f"{'up' if yt > 0 else 'down'} {abs(yt):.0f} dB there; podcasts aim for -16. Say 'normalize for youtube' to set it.")
        if what == "length":
            talk = m["duration"] - sum(b - a for a, b in m.get("pauses", []))
            return f"{_mmss(m['duration'])} long: about {_mmss(talk)} of sound and {len(m.get('pauses', []))} pause(s) (the longest {m['longest_pause']:.1f} s)."
        if what in ("transcript", "language"):
            words = O.transcribe_words(v["wav"])
            text = " ".join(w["w"] for w in words)
            if what == "language":
                from .. import speech
                info = speech._load().transcribe(M.load(v["wav"], sr=16000)[: 16000 * 30], beam_size=1)[1]
                return f"It sounds like {info.language} ({info.language_probability:.0%} sure)."
            return (f"\"{text[:700]}\"" + (" ..." if len(text) > 700 else "") + f" ({len(words)} words). Say 'save the transcript as word' for a document.") if words else \
                "No speech was heard."
        if what == "compare":
            a = self._measure(Path(self.state["versions"][0]["wav"]))
            rows = [("length", f"{_mmss(a['duration'])}", f"{_mmss(m['duration'])}"), ("loudness", f"{a['lufs']:.1f} LUFS", f"{m['lufs']:.1f} LUFS"),
                    ("noise between words", f"{a['noise_db']:.0f} dB", f"{m['noise_db']:.0f} dB"), ("hum", _hum(a), _hum(m)),
                    ("longest pause", f"{a['longest_pause']:.1f} s", f"{m['longest_pause']:.1f} s")]
            return "Original -> now: " + "; ".join(f"{k} {x} -> {y}" for k, x, y in rows if x != y) + "." if any(x != y for _, x, y in rows) else "No measured change from the original."
        issues = []
        if m["noise_db"] > -55 and m["snr_db"] < 35:
            issues.append(f"background noise {m['snr_db']:.0f} dB under the voice")
        if (m.get("hum") or {}).get("hz"):
            issues.append(f"{m['hum']['hz']} Hz hum")
        if m.get("rumble_db", -99) > -25:
            issues.append("low rumble")
        if m.get("clipped", 0) > 1e-4:
            issues.append(f"clipping ({m['clipped']:.2%} of samples)")
        if m.get("sibilance_db", -99) > -14:
            issues.append("harsh 's' sounds")
        if m["lufs"] < -24:
            issues.append(f"quiet ({m['lufs']:.0f} LUFS)")
        if m["longest_pause"] > 1.5:
            issues.append(f"long pauses (up to {m['longest_pause']:.1f} s)")
        return ("To fix: " + "; ".join(issues) + ". Say 'clean it up' for the lot." if issues else
                f"It is clean: noise {m['noise_db']:.0f} dB, no hum, no clipping, {m['lufs']:.0f} LUFS.")

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
        return "\n".join(f"v{v['v']}: {v['said'][:60]} [{', '.join(o['op'] for o in v['ops']) or 'original'}]" + (" + captions" if v.get("captions") else "")
                         + (" <- now" if v["v"] == self.state["cur"] else "") for v in self.state["versions"])


# ---------------------------------------------------------------- helpers
def _summary(m):
    return {k: m.get(k) for k in ("duration", "lufs", "true_peak", "noise_db", "speech_db", "snr_db", "longest_pause", "clipped", "pitch_hz")} | {
        "hum": (m.get("hum") or {}).get("hz"), "channels": (m.get("audio") or {}).get("channels")}


def _hum(m):
    return f"{m['hum']['hz']} Hz ({m['hum']['db']:.0f} dB)" if (m.get("hum") or {}).get("hz") else "none"


def _compose(tl, keep, speed=1.0):
    """The source parts a version plays, after keeping 'keep' (times in the current version) and a speed change."""
    s = tl["speed"]
    out = []
    for x, y in keep:
        acc = 0.0
        for a, b in tl["keep"]:
            d = (b - a) / s
            lo, hi = max(x, acc), min(y, acc + d)
            if hi > lo + 1e-4:
                out.append([round(a + (lo - acc) * s, 4), round(a + (hi - acc) * s, 4)])
            acc += d
    merged = []
    for a, b in out:
        if merged and abs(merged[-1][1] - a) < 1e-3:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return {"keep": merged, "speed": round(s * speed, 6)}


def _step_words(s):
    op, i, b, a = s["op"], s["info"], s["before"], s["after"]
    if op == "clean":
        names = {"highpass": "cut the rumble", "dehum": "removed the hum", "declip": "repaired clipping", "denoise": "reduced the noise", "deess": "softened the 's' sounds",
                 "compress": "evened out the level", "normalize": "set the loudness"}
        return "Cleaned up: " + "; ".join(f"{names.get(x['op'], x['op'])} ({x['why']})" for x in i["steps"]) + \
            f". The noise is now {a['snr_db']:.0f} dB under the voice (was {b['snr_db']:.0f}); loudness {b['lufs']:.0f} -> {a['lufs']:.0f} LUFS."
    if op == "denoise":
        return f"Reduced the background noise ({b['noise_db']:.0f} -> {a['noise_db']:.0f} dB" + (f", with {' and '.join(i['also'])}" if i.get("also") else "") + ")."
    if op == "dehum":
        return f"Removed the {i['hz']} Hz hum." if i.get("found") else f"Notched out {i['hz']} Hz (no hum was measured)."
    if op == "normalize":
        return f"Loudness {b['lufs']:.1f} -> {a['lufs']:.1f} LUFS" + (f" for {i['platform']}" if i.get("platform") else "") + "."
    if op == "volume":
        return f"{'Louder' if i['db'] > 0 else 'Quieter'} by {abs(i['db']):g} dB ({b['lufs']:.0f} -> {a['lufs']:.0f} LUFS)."
    if op == "tighten":
        return f"Shortened {i['count']} long pause(s): {_mmss(b['duration'])} -> {_mmss(a['duration'])}." if i["count"] else f"No pause was longer than {i['max_pause']:g} s."
    if op == "fillers":
        return f"Cut {i['count']} filler(s) ({', '.join(x.strip(',.') for x in i['found'][:5])})." if i["count"] else "No 'um' or 'uh' was heard."
    if op in ("trim", "cut", "keep"):
        return f"{_mmss(b['duration'])} -> {_mmss(a['duration'])}."
    if op == "fade":
        return "Fade " + " and ".join(x for x in ((f"in {i['in']:g} s" if i["in"] else ""), (f"out {i['out']:g} s" if i["out"] else "")) if x) + "."
    if op == "speed":
        return f"{i['factor']:g}x speed, pitch kept: {_mmss(b['duration'])} -> {_mmss(a['duration'])}."
    if op == "pitch":
        return f"Pitch {i['semitones']:+g} semitones" + (f" ({b['pitch_hz']:.0f} -> {a['pitch_hz']:.0f} Hz)." if b.get("pitch_hz") and a.get("pitch_hz") else ".")
    if op == "music":
        return f"Music '{i['file']}' {i['below']:g} dB under the voice" + (", dipping while you talk" if i["duck"] else "") + ", faded in and out."
    if op == "join":
        return f"Added '{i['file']}' {'before' if not i['first'] else 'after'}: {_mmss(a['duration'])} in all."
    return {"highpass": "Cut the rumble.", "deess": "Softened the 's' sounds.", "declick": "Removed clicks.", "declip": "Repaired clipped peaks.", "compress": "Evened out the level.",
            "echo": "Added an echo.", "reverb": "Added room reverb.", "telephone": "Telephone voice.", "mono": "Made it mono.", "stereo": "Made it stereo."}.get(op, op + ".")


def _style_words(st):
    kind = {"clean": "clean lines", "bold": "word by word, the spoken word highlighted", "karaoke": "karaoke", "boxed": "on a dark box"}.get(st.get("kind"), st.get("kind"))
    return f"{kind}, {st.get('color', 'white')}" + (f", highlight {st.get('highlight')}" if st.get("kind") in ("bold", "karaoke") else "") + f", {st.get('position', 'bottom')}" + \
        (f", size x{st['size']:g}" if st.get("size", 1) != 1 else "")


def _cap_check_words(chk):
    bad = [c["what"] for c in chk if not c["ok"] and c["level"] == "fail"]
    warn = [c["what"] for c in chk if not c["ok"] and c["level"] == "warn"]
    return f" (checked {len(chk) - len(bad) - len(warn)}/{len(chk)}" + (f"; not right: {'; '.join(bad)}" if bad else "") + (f"; to look at: {'; '.join(warn)}" if warn else "") + ")"

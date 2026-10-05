"""The video agent, from the command line.

  .venv\\Scripts\\python.exe studio.py new "edit this for instagram: lightning on my eyes, shaky boss entrance" --media media\\me.mp4
  .venv\\Scripts\\python.exe studio.py revise <draft> "make the lightning stronger and end with a slow zoom"
  .venv\\Scripts\\python.exe studio.py verify <draft>          (check an exported draft again at its edit points)
  .venv\\Scripts\\python.exe studio.py show <draft>            (plan, notes, checks of a session)
  .venv\\Scripts\\python.exe studio.py chat "make the title red and the music a bit quieter"   (continues the chat about the last edit)
  .venv\\Scripts\\python.exe studio.py talk <draft>            (a conversation: questions, changes, undo, "export" when happy)

Options for new / revise: --no-export (build the JianYing project only), --fix N (fix rounds, default 2).
Media files must be inside the project's media/ folder. JianYing runs behind your windows; your mouse is never used.
Kill switch during exports: Ctrl+Alt+Q.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):  # item names are often Chinese: never crash on the console's code page
    _stream.reconfigure(encoding="utf-8", errors="replace")


def _log(m, **_):
    print(m, flush=True)


def _report(sess):
    from harness import verify as V
    t = sess.get("timings", {})
    print("\n=== result")
    print(f"draft   {sess['map']['draft']}  ({sess['map']['seconds']:.1f} s, {sess['map']['canvas'][0]}x{sess['map']['canvas'][1]})")
    ex = sess.get("export") or {}
    if ex.get("ok"):
        print(f"video   {ex['path']}")
    elif ex:
        print(f"export  failed: {ex.get('error')}")
    if sess.get("report"):
        c = sess["report"]["counts"]
        print(f"checks  {c['pass']} pass, {c['warn']} warn, {c['fail']} fail at the edit points")
        print(V.summary(sess["report"]))
    if t:
        print("timings " + ", ".join(f"{k} {v}" for k, v in t.items() if not isinstance(v, list)))
    if sess.get("ai_usage"):
        parts = [f"{m.split('/')[-1]} {x['calls']} calls {x['in']:,}+{x['out']:,} tokens ${x['usd']:.4f}" for m, x in sess["ai_usage"].items()]
        print(f"AI cost ${sess['ai_usd']:.4f}: " + "; ".join(parts))


def main():
    ap = argparse.ArgumentParser(description="video editing agent (JianYing 5.9)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("request")
    n.add_argument("--media", nargs="+", required=True)
    n.add_argument("--like", nargs="+", default=[], help="sample edits whose style to match (measured, not used as footage)")
    n.add_argument("--template", default=None, help="follow a template: a library name, a video of it, a CapCut template link, "
                                                    "a screenshot of its page, or words ('4 clips 15s #slowmo')")
    tp = sub.add_parser("template", help="templates: learn one from a video, add one from its link / screenshot / words, suggest, list")
    tp.add_argument("action", choices=["learn", "add", "suggest", "list", "show"])
    tp.add_argument("target", nargs="?", default=None,
                    help="learn: the video; add: a CapCut template link, a screenshot of its page or words; suggest: what you want; show: the name")
    tp.add_argument("--name", default=None)
    tp.add_argument("--video", default=None, help="add: a video of the template too (its preview), for the exact cut frames")
    tp.add_argument("--media", nargs="*", default=[], help="suggest: your footage (templates needing more clips than it has rank lower)")
    q = sub.add_parser("ask", help="a question: available effects, what is possible, what kind of video, a sample's style")
    q.add_argument("question")
    q.add_argument("--media", nargs="*", default=[])
    c = sub.add_parser("chat", help="any message: a question is answered, a request with media is edited")
    c.add_argument("message")
    c.add_argument("--media", nargs="*", default=[])
    c.add_argument("--like", nargs="*", default=[])
    c.add_argument("--draft", default=None, help="the edit a follow-up refers to (default: the last one)")
    t = sub.add_parser("talk", help="a conversation about an edit: questions, changes, undo, versions; 'export' renders it")
    t.add_argument("draft", nargs="?", default=None, help="the edit (default: the last one)")
    t.add_argument("--new", action="store_true", help="a new chat instead of continuing the last one about this edit")
    r = sub.add_parser("revise")
    r.add_argument("draft")
    r.add_argument("request")
    for p in (n, r):
        p.add_argument("--no-export", action="store_true")
        p.add_argument("--fix", type=int, default=2)
    v = sub.add_parser("verify")
    v.add_argument("draft")
    s = sub.add_parser("show")
    s.add_argument("draft")
    a = ap.parse_args()

    from harness import studio

    def inside(paths, roots=("media",)):
        out = []
        for f in paths:
            p = Path(f).resolve()
            if not p.is_file() or not any((ROOT / r).resolve() in p.parents for r in roots):
                sys.exit(f"not a file inside {' or '.join(r + '/' for r in roots)}: {f}")
            out.append(str(p))
        return out
    if a.cmd == "new":
        files = inside(a.media)
        refs = inside(a.like, ("media", "out"))  # samples may be the user's or earlier edits
        st = studio.Studio(log=_log, export=not a.no_export, fix_rounds=a.fix)
        if a.template:
            tsrc = inside([a.template], ("media", "out"))[0] if Path(a.template).exists() else a.template
            sess = st.from_template(a.request, files, tsrc)
            m = sess.get("template_match")
            if m:
                print(f"template  {m['found_on_time']}/{m['template_cuts']} cuts on the template's frames ({m['rhythm_match']:.0%})")
            ti = sess.get("template_info") or {}
            if ti.get("techniques") and ti["techniques"] != "no trend words":
                print(f"style     {ti['techniques']}")
            for x in ti.get("approximations") or []:
                print(f"note      {x}")
            for x in ti.get("offers") or []:
                print(f"offer     {x}")
        else:
            sess = st.new(a.request, files, refs)
        _report(sess)
    elif a.cmd == "template":
        from harness import template as TP
        if a.action == "list":
            for nm in TP.library():
                t = TP.load(nm) or {}
                m = t.get("meta") or {}
                print(f"  {nm}: {len(t.get('slots') or [])} slots, {t.get('seconds')} s, {'exact (from a video)' if t.get('exact', True) else 'from its page'}"
                      + (f"  '{m['title']}'" if m.get("title") else "") + (f" {' '.join('#' + x for x in m.get('tags') or [])}" if m.get("tags") else ""))
            if not TP.library():
                print("no templates yet")
        elif a.action == "show":
            t = TP.load(a.target) or sys.exit(f"no template '{a.target}'")
            print(json.dumps({k: t.get(k) for k in ("name", "source", "exact", "seconds", "bpm", "drop", "counts", "look_words", "notes")},
                             ensure_ascii=False, indent=1))
            if t.get("techniques"):
                from harness import trends as TR
                print("style:", TR.explain(t["techniques"]))
            for s in t["slots"][:60]:
                v = ((t.get("vision") or {}).get("slots") or {}).get(str(s["n"])) or {}
                extra = " ".join(x for x in (f"{s['speed']}x" if s.get("speed") else "", "ramp" if s.get("ramp") else "",
                                             "B&W" if s.get("bw") else "", "guessed cut" if s.get("guessed") else "") if x)
                print(f"  #{s['n']:<3} {s['start']:6.2f}s {s['dur']:5.2f}s  in: {s['into']:<8} {str(s.get('size') or '-'):<11} {extra} "
                      f"{'text: ' + repr(v.get('text')) if v.get('text') else ''} {v.get('shows') or ''}")
        elif a.action == "add":
            import re as _re
            from harness import template_meta as TM
            from harness import trends as TR
            from harness.planner import ChatPlanner
            src = a.target or sys.exit("add: give a CapCut template link, a screenshot of its page, or words ('SLOWMO HDR 4 clips 15s #slowmo')")
            planner = ChatPlanner()
            try:
                if _re.match(r"https?://", src, _re.I):
                    meta = TM.from_link(src)
                elif Path(src).is_file() and Path(src).suffix.lower() in TP.IMAGE_EXT:
                    meta = TM.from_image(inside([src], ("media", "out"))[0], planner)
                else:
                    meta = TM.from_text(src)
            except TM.NotAllowed as e:
                sys.exit(f"not read: {e}")
            print(f"page      '{meta.get('title')}' by {meta.get('author') or '?'}: {meta.get('clips')} clips, {meta.get('seconds')} s, "
                  f"{meta.get('aspect') or '?'}, {meta.get('uses') or '?'} uses  {' '.join('#' + x for x in meta.get('tags') or [])}")
            if a.video:
                t = TP.learn(inside([a.video], ("media", "out"))[0], planner, name=a.name or TP._slug(meta.get("title"), "template"), log=_log, meta=meta)
            else:
                t = TP.from_meta(meta, name=a.name, planner=planner, log=_log)
            print(f"added '{t['name']}': {len(t['slots'])} slots in {t['seconds']} s, "
                  f"{'exact cut frames from the video' if t.get('exact', True) else 'even slots on the beat (give --video <preview> for the exact frames)'}")
            print(f"style     {TR.explain(t.get('techniques') or {})}")
            for x in t.get("notes") or []:
                print(f"note      {x}")
            u = (t.get("techniques") or {}).get("unknown") or []
            if u:
                print(f"note      tags with no editing meaning here: {', '.join('#' + x for x in u)}")
        elif a.action == "suggest":
            from harness import frames as FR
            files = inside(a.media) if a.media else []
            an = {Path(f).name: {"file": Path(f).name, "kind": "image" if Path(f).suffix.lower() in TP.IMAGE_EXT else "video",
                                 "seconds": float(FR.probe(f).get("seconds") or 0)} for f in files}
            for i, x in enumerate(TP.suggest(a.target or "", an or None, k=5), 1):
                print(f"  {i}. {x['name']} ({x['clips']} clips, {x['seconds']} s, {'exact' if x['exact'] else 'from its page'})  score {x['score']}: {x['why']}")
        else:
            from harness.planner import ChatPlanner
            src = inside([a.target], ("media", "out"))[0]
            t = TP.learn(src, ChatPlanner(), name=a.name or Path(src).stem[:30], log=_log)
            print(f"learned '{t['name']}': {len(t['slots'])} slots in {t['seconds']} s, {t['bpm']} BPM, drop at {t['drop']} s; {t['counts']}")
    elif a.cmd in ("ask", "chat"):
        from harness import router as RT
        from harness.planner import ChatPlanner
        files = inside(a.media) if a.media else []
        refs = inside(getattr(a, "like", []) or [], ("media", "out"))
        msg = a.question if a.cmd == "ask" else a.message
        last = getattr(a, "draft", None) or (max(studio.SESSIONS.glob("*.json"), key=lambda p: p.stat().st_mtime).stem
                                             if studio.SESSIONS.exists() and any(studio.SESSIONS.glob("*.json")) else None)
        planner = ChatPlanner()
        r = RT.route(msg, files, last, planner)
        refs += [str(p) for p in (ROOT / "media").rglob("*") for name in r["references"] if p.name.lower() == name.lower()]
        if a.cmd == "chat" and r["intent"] == "edit":
            sess = studio.Studio(log=_log).new(msg, files, refs)
            _report(sess)
        elif a.cmd == "chat" and last:  # everything about an existing edit goes to its conversation (changes, questions, undo...)
            from harness.conversation import Conversation
            conv = Conversation.latest(last, planner=planner, log=_log, export=True) or Conversation.start(last, planner=planner, log=_log, export=True)
            print(conv.say(msg))
            print(f"(chat {conv.state['id']}, v{conv.state['cur']}; draft {conv.version.get('draft') or last})")
            usd = planner.cost()[1]
            if usd:
                print(f"(AI ${usd:.4f})")
        else:
            intent, text = RT.answer(msg, files, planner, last, _log)
            print(f"[{intent}] {text}")
            usd = planner.cost()[1]
            if usd:
                print(f"(AI ${usd:.4f})")
    elif a.cmd == "talk":
        from harness.conversation import Conversation
        from harness.planner import ChatPlanner
        draft = a.draft or (max(studio.SESSIONS.glob("*.json"), key=lambda p: p.stat().st_mtime).stem
                            if studio.SESSIONS.exists() and any(studio.SESSIONS.glob("*.json")) else None)
        if not draft:
            sys.exit("no edit yet: make one with 'studio.py new ...'")
        planner = ChatPlanner()
        conv = (None if a.new else Conversation.latest(draft, planner=planner, log=_log, export=True)) or \
            Conversation.start(draft, planner=planner, log=_log, export=True)
        print(f"Talking about {draft} (chat {conv.state['id']}, v{conv.state['cur']}). Ask, change, undo, 'export' when happy; 'quit' to leave.")
        while True:
            try:
                msg = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg.lower() in ("quit", "exit", "q", "bye"):
                break
            if msg:
                print(conv.say(msg))
        print(f"(chat saved: {conv.state['id']}, {len(conv.state['versions'])} versions; AI ${planner.cost()[1]:.4f})")
    elif a.cmd == "revise":
        sess = studio.Studio(log=_log, export=not a.no_export, fix_rounds=a.fix).revise(a.draft, a.request)
        _report(sess)
    elif a.cmd == "verify":
        from harness import verify as V
        from harness.planner import ChatPlanner
        sess = studio.load(a.draft)
        video = ROOT / "out" / "video" / f"{a.draft}.mp4"
        sess["report"] = V.verify(video, sess["map"], planner=ChatPlanner(), log=_log)
        studio._save(sess)
        _report(sess)
    elif a.cmd == "show":
        sess = studio.load(a.draft)
        print(json.dumps({k: sess[k] for k in ("request", "plan") if k in sess}, ensure_ascii=False, indent=1))
        print("notes:", sess["resolved"].get("notes"))
        _report(sess)


if __name__ == "__main__":
    main()

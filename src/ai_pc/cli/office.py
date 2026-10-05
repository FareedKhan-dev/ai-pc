"""The document agent, from the command line (Word documents, made programmatically and checked page by page).

  ai-pc office new "a 5 page report on rooftop solar in Pakistan with a cost table and a chart"
  ai-pc office new "invoice for Ali Traders: logo design Rs 25,000, 2 sets of posts at Rs 12,500, 18% tax"
  ai-pc office new "my CV, data analyst, 4 years at Daraz" --files media\\docs\\old_cv.docx
  ai-pc office check out\\docs\\x\\x.docx      (render and check any Word document)
  ai-pc office new "a 10 slide presentation on rooftop solar for homeowners in Lahore"
  ai-pc office talk report.docx        (edit an existing Word / PowerPoint / Excel file by conversation)
  ai-pc office talk sales.xlsx -m "clean up the data" -m "which city sold the most?" -m export
  ai-pc office talk --chat book_sales_163841      (continue a saved chat)
  ai-pc office project sales.xlsx -m "clean up the data" -m "write a 2 page report on Q1 sales from the workbook"
        -m "put the amount by city into the report, with a pie chart" -m "make a 5 slide deck from the report" -m "export everything as one pdf"
  ai-pc office project --load proj_q1sales_171943      (continue a saved project)

Options for new: --files (the client's material: txt, md, csv, docx, xlsx, pdf, images; inside the project folder),
--theme corporate|academic|modern|elegant|minimal|warm, --pages N, --fix N (fix rounds, default 2), --no-look.
In a talk every message makes one version (undo, redo, 'go back to v2', 'compare v0 and v3', 'what did you change?',
'export'); questions about a workbook's data are computed, not guessed.
Word, PowerPoint and Excel run hidden in the background; your mouse, keyboard and open documents are never touched.
"""
import argparse
import json
import sys
from pathlib import Path

from ai_pc.core.paths import ROOT

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def _log(m, **_):
    print(m, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="document agent (Word, programmatic)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("request")
    n.add_argument("--files", nargs="*", default=[])
    n.add_argument("--theme", default=None, choices=["corporate", "academic", "modern", "elegant", "minimal", "warm"])
    n.add_argument("--pages", type=int, default=None)
    n.add_argument("--fix", type=int, default=2)
    n.add_argument("--no-look", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("docx")
    t = sub.add_parser("talk", help="edit an existing .docx / .pptx / .xlsx by conversation")
    t.add_argument("file", nargs="?", default=None)
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    pj = sub.add_parser("project", help="several files edited together: data from a workbook into a report and a deck, PDF packs")
    pj.add_argument("files", nargs="*")
    pj.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    pj.add_argument("--load", default=None, help="continue a saved project by its id")
    pj.add_argument("--name", default=None)
    pj.add_argument("--offline", action="store_true", help="rules only, no model")
    a = ap.parse_args(argv)

    def inside(paths):
        out = []
        for f in paths:
            p = Path(f).resolve()
            if not p.is_file() or ROOT.resolve() not in p.parents:
                sys.exit(f"not a file inside the project folder: {f}")
            out.append(str(p))
        return out
    if a.cmd == "new":
        from ai_pc.office.studio import DocStudio
        st = DocStudio(log=_log, look=not a.no_look, fix_rounds=a.fix)
        s = st.new(a.request, inside(a.files), theme=a.theme, pages=a.pages)
        c = s["checks"]["counts"]
        print("\n=== result")
        print(f"document  {s.get('pptx') or s.get('xlsx') or s['docx']}")
        print(f"pdf       {s.get('pdf')}")
        front = (s.get("pages") or 0) - (s.get("body_pages") or s.get("pages") or 0)
        size = (f", {len(s['sheets'])} sheet(s): " + ", ".join(f"{x['name']} ({x['rows']} rows)" if x["kind"] == "table" else x["name"] for x in s["sheets"])
                if s.get("sheets") else f", {s.get('body_pages') or s.get('pages')} {'slide' if s['doctype'] == 'presentation' else 'page'}(s)")
        print(f"what      {s['doctype']}, theme {s['theme']}{size}" + (f" + {front} front (cover, contents)" if front else "")
              + (f" for {s['target_pages']} asked" if s.get("target_pages") else "")
              + (f", {s.get('words')} words" if s.get("words") else ""))
        print(f"checks    {c.get('pass', 0)} pass, {c.get('warn', 0)} warn, {c.get('fail', 0)} fail" + (f", {c['skip']} skipped" if c.get("skip") else ""))
        for r in s["checks"]["results"]:
            if r["status"] in ("warn", "fail", "skip"):
                print(f"  {r['status'].upper():5s} {r['id']:7s} {r['why'][:150]}")
        if s.get("client_data"):
            print(f"data      {s['client_data']['found']}/{s['client_data']['checked']} of the client's figures and names are on the pages")
        print("timings   " + ", ".join(f"{k} {v}" for k, v in s["timings"].items()))
        print(f"AI cost   ${s['ai_usd']:.4f} (" + "; ".join(f"{m.split('/')[-1]} {x['calls']} calls" for m, x in s["ai_usage"].items()) + ")")
        print(f"report    {Path(s['folder']) / 'report.md'}")
    elif a.cmd == "talk":
        from ai_pc.office.bookchat import BookChat
        from ai_pc.office.deckchat import DeckChat
        from ai_pc.office.docchat import CHATS, DocChat
        kinds = {".docx": DocChat, ".pptx": DeckChat, ".xlsx": BookChat, ".xlsm": BookChat}
        planner = None
        if not a.offline:
            from ai_pc.llm.planner import ChatPlanner
            planner = ChatPlanner()
        if a.chat:
            sf = CHATS / a.chat / "chat.json"
            if not sf.is_file():
                sys.exit(f"no saved chat {a.chat} in {CHATS}")
            kind = json.loads(sf.read_text(encoding="utf-8")).get("kind", "docx")
            chat = {"docx": DocChat, "pptx": DeckChat, "xlsx": BookChat}[kind].load(a.chat, planner=planner)
        else:
            if not a.file:
                sys.exit("say which file: ai-pc office talk <file.docx|.pptx|.xlsx>")
            src = inside([a.file])[0]
            cls = kinds.get(Path(src).suffix.lower())
            if cls is None:
                sys.exit("talk edits .docx, .pptx and .xlsx files")
            chat = cls.start(src, planner=planner)
        print(f"Chat {chat.state['id']} about {Path(chat.state['base']).name}, at v{chat.state['cur']}. Ask, change, undo, 'export' when happy; 'quit' to leave.")
        try:
            if a.say:
                for msg in a.say:
                    print(f"> {msg}")
                    print(chat.say(msg), flush=True)
            else:
                while True:
                    try:
                        msg = input("> ").strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if msg.lower() in ("quit", "exit", "q", "bye"):
                        break
                    if msg:
                        print(chat.say(msg), flush=True)
        finally:
            chat.close()
        usd = planner.cost()[1] if planner is not None else 0.0
        print(f"(chat {chat.state['id']}: {len(chat.state['versions'])} versions, now v{chat.state['cur']}; files in {chat.folder}; AI ${usd:.4f})")
    elif a.cmd == "project":
        from ai_pc.office.projectchat import ProjectChat
        planner = None
        if not a.offline:
            from ai_pc.llm.planner import ChatPlanner
            planner = ChatPlanner()
        if a.load:
            pc = ProjectChat.load(a.load, planner=planner, log=_log)
        else:
            if not a.files:
                sys.exit("say which files: ai-pc office project <file.xlsx> [<file.docx> <file.pptx>]")
            pc = ProjectChat.start(inside(a.files), name=a.name, planner=planner, log=_log)
        print(f"Project {pc.state['id']}: " + ", ".join(pc.label(k) for k in pc.active()) + ". 'quit' to leave.")
        try:
            msgs = a.say
            if msgs:
                for msg in msgs:
                    print(f"> {msg}")
                    print(pc.say(msg), flush=True)
            else:
                while True:
                    try:
                        msg = input("> ").strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if msg.lower() in ("quit", "exit", "q", "bye"):
                        break
                    if msg:
                        print(pc.say(msg), flush=True)
        finally:
            pc.close()
        usd = planner.cost()[1] if planner is not None else 0.0
        print(f"(project {pc.state['id']}: v{pc.state['cur']} of {len(pc.state['versions'])} versions; files in {pc.folder}; AI ${usd:.4f})")
    elif a.cmd == "check":
        from ai_pc.office import render as RN
        from ai_pc.office import verify as VF
        src = inside([a.docx])[0]
        r = RN.to_pdf(src, update_fields=False, save=False, pdf=str(Path(src).with_suffix(".check.pdf")))
        if not r.get("ok"):
            sys.exit(f"could not render: {r.get('error')}")
        import docx
        d = docx.Document(src)
        blocks = [{"type": "heading", "text": p.text, "level": int(p.style.name.split()[-1])} if p.style.name.startswith("Heading") and p.style.name.split()[-1].isdigit()
                  else {"type": "paragraph", "text": p.text} for p in d.paragraphs if p.text.strip()]
        from ai_pc.office import docplan as DP
        plan = DP.resolve({"doctype": "other", "blocks": blocks, "cover": False, "toc": False})
        sec = d.sections[0]
        plan["page"]["orientation"] = "landscape" if sec.page_width > sec.page_height else "portrait"
        plan["page"]["size"] = "Letter" if abs(sec.page_width.cm - 21.59) < 0.3 else "A4"
        plan["page"]["margins"] = round(sec.left_margin.cm, 2)
        rep = VF.check(plan, {}, r)
        print(json.dumps(rep["counts"]))
        for x in rep["results"]:
            if x["status"] != "pass" or x["type"] in ("global", "text"):
                print(f"  {x['status'].upper():5s} {x['id']:7s} {x['why'][:150]}")


if __name__ == "__main__":
    main()

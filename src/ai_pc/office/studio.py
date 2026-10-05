"""The document studio: a request in, a checked .docx and .pdf out (the video studio's recipe for Word).

s = DocStudio(planner).new("a 5 page report on rooftop solar in Pakistan with a cost table and a chart",
                           files=["data/costs.xlsx"])
-> out/docs/<name>/<name>.docx + .pdf + pages.jpg + report.md + session.json

1 write    designer: an outline, then every section in parallel (or one call for a short document)
2 build    docplan.resolve + docx_build: real styles, tables, native charts, cover, contents, page numbers
3 render   Word in the background: fields and contents updated, saved, exported to PDF
4 check    verify: every element on the rendered pages; the client's own data looked for on the pages
5 fix      what the checks can fix (length, a heading alone at a page's foot, a blank page, a table too wide),
           rebuilt and checked again; then one vision look at the final pages
6 report   asked vs delivered, checks, time and cost
"""

import json
import re
import time
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.core.util import slug
from ai_pc.office import designer as D
from ai_pc.office import docplan as DP
from ai_pc.office import docx_build as DB
from ai_pc.office import render as RN
from ai_pc.office import verify as VF

OUT = ROOT / "out" / "docs"


class DocStudio:
    def __init__(self, planner=None, log=print, look=True, fix_rounds=2):
        if planner is None:
            from ai_pc.llm.planner import ChatPlanner

            planner = ChatPlanner()
        self.planner, self.log, self.look, self.fix_rounds = planner, log, look, fix_rounds

    def new(self, request, files=(), theme=None, pages=None, name=None, kind=None):
        """A document for the request: a slide deck when it asks for slides, a workbook when it asks for a spreadsheet,
        else a Word document."""
        kind = kind or kind_of(request)
        if kind == "pptx":
            return self.new_deck(request, files, theme, pages, name)
        if kind == "xlsx":
            return self.new_book(request, files, theme, name)
        t0 = time.perf_counter()
        timings = {}
        files = [str(Path(f)) for f in files or []]
        inputs = D.read_inputs(files)
        t = time.perf_counter()
        plan, dinfo = D.design(request, inputs, self.planner, self.log, theme=theme, pages=pages)
        timings["write_s"] = round(time.perf_counter() - t, 1)
        self.log(f"written: {dinfo.get('mode')} document, {dinfo['calls']} model call(s) in {timings['write_s']} s")
        nm = name or slug(plan.get("title") or request, 40) or "document"
        folder = OUT / f"{nm}_{time.strftime('%H%M%S')}"
        folder.mkdir(parents=True, exist_ok=True)
        docx_path = folder / f"{nm}.docx"
        rounds = []
        for rnd in range(self.fix_rounds + 1):
            rp = DP.resolve(plan)
            t = time.perf_counter()
            built = DB.build(rp, docx_path)
            tb = time.perf_counter() - t
            rendered = RN.to_pdf(docx_path, update_fields=True, save=True)
            rep = VF.check(rp, built, rendered, planner=None)
            rounds.append(
                {
                    "round": rnd,
                    "build_s": round(tb, 2),
                    "render_s": rendered.get("seconds"),
                    "pages": rep["facts"].get("pages"),
                    "counts": rep["counts"],
                    "problems": [f"{r['id']}: {r['why']}" for r in rep["results"] if r["status"] in ("warn", "fail")][:8],
                }
            )
            self.log(
                f"round {rnd}: {rep['facts'].get('pages')} page(s), checks {rep['counts']} (build {tb:.2f} s, render {rendered.get('seconds')} s)"
            )
            fixes = [r["fix"] for r in rep["results"] if r.get("fix") and r["status"] in ("warn", "fail")]
            if not fixes or rnd == self.fix_rounds or not rendered.get("ok"):
                break
            plan, done = self.apply(plan, rp, fixes, request)
            rounds[-1]["fixed"] = done
            self.log("fixing: " + "; ".join(done))
            if not done:
                break
        if self.look and rendered.get("ok"):
            t = time.perf_counter()
            look = VF.check(rp, built, rendered, planner=self.planner)
            lk = next((r for r in look["results"] if r["type"] == "look"), None)
            if lk:
                rep["results"].append(lk)
                rep["counts"] = {k: sum(1 for r in rep["results"] if r["status"] == k) for k in ("pass", "warn", "fail", "skip")}
            timings["look_s"] = round(time.perf_counter() - t, 1)
        data = self.client_data(request, dinfo, rendered)
        timings["total_s"] = round(time.perf_counter() - t0, 1)
        sess = {
            "request": request,
            "files": files,
            "folder": str(folder),
            "docx": str(docx_path),
            "pdf": rendered.get("pdf"),
            "doctype": rp["doctype"],
            "theme": rp["theme"],
            "title": rp["title"],
            "pages": rep["facts"].get("pages"),
            "body_pages": rep["facts"].get("body_pages"),
            "target_pages": rp.get("target_pages"),
            "words": rendered.get("words"),
            "design": {k: v for k, v in dinfo.items() if k != "outline"},
            "outline": dinfo.get("outline"),
            "plan": plan,
            "checks": rep,
            "rounds": rounds,
            "client_data": data,
            "timings": timings,
        }
        sess["ai_usage"], sess["ai_usd"] = self.planner.cost()
        if rendered.get("ok"):
            imgs = RN.pages(rendered["pdf"], scale=0.9)
            (folder / "pages.jpg").write_bytes(RN.sheet(imgs, [f"p{i + 1}" for i in range(len(imgs))], cols=min(4, len(imgs)), cell_w=420))
            sess["sheet"] = str(folder / "pages.jpg")
        (folder / "report.md").write_text(report_md(sess), encoding="utf-8")
        (folder / "session.json").write_text(json.dumps(sess, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return sess

    def new_deck(self, request, files=(), theme=None, slides=None, name=None):
        """A PowerPoint deck: written in one call, drawn by pptx_build, rendered by PowerPoint in the background (PDF,
        slide images, and the measured size of every text), checked slide by slide, fixed, looked at once."""
        from ai_pc.office import pptx_build as PB

        t0 = time.perf_counter()
        timings = {}
        files = [str(Path(f)) for f in files or []]
        inputs = D.read_inputs(files)
        t = time.perf_counter()
        deck, dinfo = D.design_deck(request, inputs, self.planner, self.log, theme=theme, slides=slides)
        timings["write_s"] = round(time.perf_counter() - t, 1)
        self.log(f"written: deck of {len(deck.get('slides') or [])} slides in {timings['write_s']} s")
        nm = name or slug(deck.get("title") or request, 40) or "deck"
        folder = OUT / f"{nm}_{time.strftime('%H%M%S')}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{nm}.pptx"
        png_dir = folder / "slides"
        rounds = []
        for rnd in range(self.fix_rounds + 1):
            rd = PB.resolve_deck(deck)
            t = time.perf_counter()
            built = PB.build_deck(rd, path)
            tb = time.perf_counter() - t
            png_dir.mkdir(exist_ok=True)
            for f in png_dir.glob("*.png"):
                f.unlink()
            rendered = RN.to_pdf(path, measure=True, png_dir=str(png_dir), png_width=1280)
            rep = VF.check_deck(rd, built, rendered)
            rounds.append(
                {
                    "round": rnd,
                    "build_s": round(tb, 2),
                    "render_s": rendered.get("seconds"),
                    "slides": rendered.get("slides"),
                    "counts": rep["counts"],
                    "problems": [f"{r['id']}: {r['why']}" for r in rep["results"] if r["status"] in ("warn", "fail")][:8],
                }
            )
            self.log(f"round {rnd}: {rendered.get('slides')} slides, checks {rep['counts']} (build {tb:.2f} s, render {rendered.get('seconds')} s)")
            fixes = [r["fix"] for r in rep["results"] if r.get("fix") and r["status"] in ("warn", "fail")]
            if not fixes or rnd == self.fix_rounds or not rendered.get("ok"):
                break
            done = []
            for f in fixes:
                if f.get("op") == "shrink" and f.get("src") is not None and 0 <= f["src"] < len(deck["slides"]):
                    sl = deck["slides"][f["src"]]
                    sl["scale"] = round(float(sl.get("scale") or 1.0) * 0.85, 3)
                    if len(sl.get("bullets") or []) > 6:  # too much for one slide: the rest goes to a continuation slide
                        rest = sl["bullets"][6:]
                        sl["bullets"] = sl["bullets"][:6]
                        deck["slides"].insert(f["src"] + 1, {**sl, "bullets": rest, "title": f"{sl.get('title') or ''} (continued)", "scale": 1.0})
                    done.append(f"slide '{str(sl.get('title') or '')[:30]}' text made smaller")
            rounds[-1]["fixed"] = done
            self.log("fixing: " + "; ".join(done))
            if not done:
                break
        if self.look and rendered.get("ok"):
            t = time.perf_counter()
            lk = VF.check_deck(rd, built, rendered, planner=self.planner, png_dir=str(png_dir))
            look = next((r for r in lk["results"] if r["type"] == "look"), None)
            if look:
                rep["results"].append(look)
                rep["counts"] = {k: sum(1 for r in rep["results"] if r["status"] == k) for k in ("pass", "warn", "fail", "skip")}
            timings["look_s"] = round(time.perf_counter() - t, 1)
        timings["total_s"] = round(time.perf_counter() - t0, 1)
        sess = {
            "request": request,
            "files": files,
            "folder": str(folder),
            "pptx": str(path),
            "docx": str(path),
            "pdf": rendered.get("pdf"),
            "doctype": "presentation",
            "theme": rd["theme"],
            "title": rd["title"],
            "slides": rendered.get("slides"),
            "target_pages": rd.get("target_slides"),
            "pages": rendered.get("slides"),
            "body_pages": rendered.get("slides"),
            "design": dinfo,
            "plan": deck,
            "checks": rep,
            "rounds": rounds,
            "client_data": self.client_data(request, {}, rendered),
            "timings": timings,
        }
        sess["ai_usage"], sess["ai_usd"] = self.planner.cost()
        if rendered.get("ok"):
            from PIL import Image

            imgs = [Image.open(p_).convert("RGB") for p_ in sorted(png_dir.glob("*.png"))]
            if imgs:
                (folder / "slides.jpg").write_bytes(RN.sheet(imgs, [f"s{i + 1}" for i in range(len(imgs))], cols=4, cell_w=420))
                sess["sheet"] = str(folder / "slides.jpg")
        (folder / "report.md").write_text(report_md(sess), encoding="utf-8")
        (folder / "session.json").write_text(json.dumps(sess, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return sess

    def new_book(self, request, files=(), theme=None, name=None):
        """An Excel workbook: designed in one call (columns, computed columns by name, totals, summaries), written with
        live formulas by xlsx_build, recalculated by Excel in the background, every total checked against Python's."""
        from ai_pc.office import xlsx_build as XB

        t0 = time.perf_counter()
        timings = {}
        files = [str(Path(f)) for f in files or []]
        inputs = D.read_inputs(files)
        t = time.perf_counter()
        book, dinfo = D.design_book(request, inputs, self.planner, self.log, theme=theme)
        timings["write_s"] = round(time.perf_counter() - t, 1)
        self.log(f"written: workbook of {len(book.get('sheets') or [])} sheet(s) in {timings['write_s']} s")
        nm = name or slug(book.get("title") or request, 40) or "workbook"
        folder = OUT / f"{nm}_{time.strftime('%H%M%S')}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{nm}.xlsx"
        rb = XB.resolve_book(book)
        t = time.perf_counter()
        built = XB.build_book(rb, path)
        tb = time.perf_counter() - t
        rendered = RN.to_pdf(path, save=True, read=[{"sheet": c["sheet"], "cell": c["cell"]} for c in built["checks"]])
        rep = VF.check_book(rb, built, rendered)
        self.log(f"built in {tb:.2f} s; Excel {rendered.get('seconds')} s; checks {rep['counts']}")
        if self.look and rendered.get("ok"):
            t = time.perf_counter()
            import threading

            box = {}

            def go():
                try:
                    imgs = RN.pages(rendered["pdf"], scale=1.0, last=5)
                    box["r"] = VF.look_images(
                        imgs, f"an Excel workbook printed as {len(imgs)} page(s): '{rb.get('title') or ''}'", self.planner, VF.LOOK_SYSTEM
                    )
                except Exception as e:  # noqa: BLE001
                    box["r"] = {"id": "look", "type": "look", "status": "skip", "why": f"visual check failed: {type(e).__name__}"}

            th_ = threading.Thread(target=go, daemon=True)
            th_.start()
            th_.join(timeout=25)  # a slow model never holds up the run
            rep["results"].append(
                box.get("r") or {"id": "look", "type": "look", "status": "skip", "why": "visual check skipped: no answer within 25 s"}
            )
            rep["counts"] = {k: sum(1 for r in rep["results"] if r["status"] == k) for k in ("pass", "warn", "fail", "skip")}
            timings["look_s"] = round(time.perf_counter() - t, 1)
        timings["total_s"] = round(time.perf_counter() - t0, 1)
        sess = {
            "request": request,
            "files": files,
            "folder": str(folder),
            "xlsx": str(path),
            "docx": str(path),
            "pdf": rendered.get("pdf"),
            "doctype": "workbook",
            "theme": rb["th"]["name"],
            "title": rb.get("title"),
            "pages": None,
            "body_pages": None,
            "sheets": built["sheets"],
            "design": dinfo,
            "plan": book,
            "checks": rep,
            "rounds": [],
            "client_data": None,
            "timings": timings,
        }
        sess["ai_usage"], sess["ai_usd"] = self.planner.cost()
        if rendered.get("ok"):
            imgs = RN.pages(rendered["pdf"], scale=0.9)
            if imgs:
                (folder / "pages.jpg").write_bytes(RN.sheet(imgs, [f"p{i + 1}" for i in range(len(imgs))], cols=min(3, len(imgs)), cell_w=520))
                sess["sheet"] = str(folder / "pages.jpg")
        (folder / "report.md").write_text(report_md(sess), encoding="utf-8")
        (folder / "session.json").write_text(json.dumps(sess, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return sess

    def apply(self, plan, rp, fixes, request):
        """The plan changed as the checks suggest. Returns (plan, [what was done])."""
        import copy

        plan = copy.deepcopy(plan)
        done = []
        src = {i: b.get("src") for i, b in enumerate(rp["blocks"])}
        for f in fixes:
            op = f.get("op")
            if op == "length" and f.get("want") and f.get("pages"):
                factor = max(0.55, min(1.9, f["want"] / max(1, f["pages"])))
                plan, n = D.resize(plan, request, self.planner, factor, self.log)
                if n:
                    done.append(f"{n} section(s) rewritten {'longer' if factor > 1 else 'shorter'} ({f['pages']} pages for {f['want']} asked)")
            elif op == "page_break_before" and src.get(f.get("block")) is not None:
                plan["blocks"][src[f["block"]]]["page_break_before"] = True
                done.append(f"heading '{str(plan['blocks'][src[f['block']]].get('text'))[:30]}' moved to the next page")
            elif op == "blank_pages":
                n = sum(1 for b in plan["blocks"] if isinstance(b, dict) and b.get("type") == "page_break")
                plan["blocks"] = [b for b in plan["blocks"] if not (isinstance(b, dict) and b.get("type") == "page_break")]
                if n:
                    done.append(f"{n} page break(s) removed (blank page)")
            elif op == "fit_pages":
                plan["tight"] = int(plan.get("tight") or 0) + 1
                done.append(f"tightened spacing and margins to fit {f.get('pages')} page(s)")
            elif op == "table_smaller" and src.get(f.get("block")) is not None:
                plan["blocks"][src[f["block"]]]["small"] = True
                done.append("a wide table set in smaller type")
        return plan, done

    def client_data(self, request, dinfo, rendered):
        """The numbers and names the client gave (in the request, and as the outline listed them), looked for on the
        rendered pages: a client's figure must reach the document exactly."""
        if not rendered.get("ok"):
            return None

        def nums(s):
            return re.sub(r"(?<=\d),(?=\d)", "", s)

        full = nums(VF._norm(" ".join(RN.text(rendered["pdf"]))))
        NUMS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|\d+(?:\.\d+)?%?"
        facts = [re.sub(r"^[A-Za-z /()]{2,30}:\s*", "", str(d)) for d in dinfo.get("data") or []]  # "Instructor: Dr. X" -> "Dr. X"
        facts = [f for f in facts if not re.search(r"\b(?:pages?|words?|length|format|due)\b", f, re.I)]  # instructions, not content
        facts += [m for m in re.findall(NUMS, str(request)) if len(re.sub(r"\D", "", m)) >= 3 or m.endswith("%")]
        found, seen = [], set()
        for f in facts:
            keys = re.findall(NUMS + r"|[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})*", f)
            keys = [nums(VF._norm(k)) for k in keys if len(re.sub(r"\W", "", k)) >= 3][:3]
            if not keys or tuple(keys) in seen:
                continue
            seen.add(tuple(keys))
            found.append({"fact": f[:80], "on_pages": all(k in full for k in keys)})
        return {"checked": len(found), "found": sum(1 for x in found if x["on_pages"]), "items": found[:20]} if found else None


def kind_of(request):
    """docx, pptx or xlsx from the words of a request (an explicit file type wins)."""
    r = str(request)
    deck, book = bool(D.DECK_RX.search(r)), bool(D.BOOK_RX.search(r))
    if book and not deck:
        return "xlsx"
    if deck and not (book and re.search(r"\b(?:excel|xlsx|spreadsheet)\b", r, re.I) and not re.search(r"\b(?:powerpoint|pptx|slides?)\b", r, re.I)):
        return "pptx"
    return "docx" if not book else "xlsx"


def report_md(s):
    c = s["checks"]["counts"]
    lines = [
        f"# {s.get('title') or 'Document'}",
        "",
        f"**Request:** {s['request']}",
        "",
        f"- Document: {s['doctype']}, theme {s['theme']}"
        + (f", {s.get('pages')} page(s)" if s.get("pages") else "")
        + (f" for {s['target_pages']} asked" if s.get("target_pages") else "")
        + (f", {s['words']} words" if s.get("words") else ""),
        f"- Files: `{s['docx']}` and `{s.get('pdf')}`",
        f"- Checks: {c.get('pass', 0)} pass, {c.get('warn', 0)} warn, {c.get('fail', 0)} fail" + (f", {c['skip']} skipped" if c.get("skip") else ""),
        f"- Time: {s['timings'].get('total_s')} s (writing {s['timings'].get('write_s')} s); AI ${s.get('ai_usd', 0):.4f}",
        "",
    ]
    if s.get("client_data"):
        cd = s["client_data"]
        lines.append(f"- Client data on the pages: {cd['found']}/{cd['checked']}")
    lines += ["", "## Checks", "", "| Element | Status | Why |", "|---|---|---|"]
    for r in s["checks"]["results"]:
        lines.append(f"| {r['id']} ({r['type']}) | {r['status']} | {r['why'][:140].replace('|', '/')} |")
    if len(s["rounds"]) > 1:
        lines += ["", "## Fix rounds", ""] + [
            f"- round {r['round']}: "
            + (f"{r['pages']} pages" if r.get("pages") is not None else f"{r.get('slides')} slides")
            + f", {r['counts']}"
            + (f"; fixed: {'; '.join(r['fixed'])}" if r.get("fixed") else "")
            for r in s["rounds"]
        ]
    return "\n".join(lines) + "\n"

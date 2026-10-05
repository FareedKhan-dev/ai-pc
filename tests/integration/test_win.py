"""Engine tests for the Windows agent: files and folders, the Recycle Bin, settings, and reading requests (no model).

  .venv\\Scripts\\python.exe tests\\integration\\test_win.py
About 20 seconds, all inside out\\_tests\\win (a made-up Downloads, Documents and Pictures); settings go to a test branch
of the registry (HKCU\\Software\\AIPC_Test), so the PC's own look, wallpaper and startup apps never change. Anything
sent to the Recycle Bin here is brought back before the end.
"""
import datetime as dt
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
from ai_pc.windows import fs  # noqa: E402
from ai_pc.windows import sandbox as win_sandbox  # noqa: E402
from ai_pc.windows.settings import Fake, SettingError, Settings  # noqa: E402
from ai_pc.windows.winparse import parse  # noqa: E402

BASE = ROOT / "out" / "_tests" / "win" / "engine"
FAILS = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


def names(files):
    return sorted(f["name"] for f in files)


def main():
    t0 = time.perf_counter()
    sb = win_sandbox.build(BASE)
    dl, docs, pics = sb["downloads"], sb["documents"], sb["pictures"]
    y = dt.datetime.now().year
    g = fs.Guard([BASE])

    # ---------------------------------------------------------------- what may be changed
    def refused(p):
        try:
            g.check(p)
            return False
        except fs.FsError:
            return True
    check("the guard refuses Windows, Program Files, AppData, the project and anything outside the roots",
          all(refused(p) for p in (r"C:\Windows\System32\drivers", r"C:\Program Files\x", Path.home() / "AppData" / "Roaming" / "x", ROOT / "src" / "x.py",
                                   Path.home() / "Downloads" / "x.txt")))
    check("the guard lets the test folder be changed (a root given inside the project)", not refused(dl / "x.txt"))

    # ---------------------------------------------------------------- what is there
    idx = fs.scan(dl)
    check("scan: 23 files, the empty folder seen", len(idx["files"]) == 23 and any(Path(d).name == "New folder" for d in idx["dirs"]), f"{len(idx['files'])}")
    kinds = {f["name"]: f["kind"] for f in idx["files"]}
    check("kinds: photo, pdf, installer, unfinished download, archive, audio", kinds.get(f"IMG_{y}0812_101500.jpg") == "photo" and
          kinds.get("Bank statement September.pdf") == "pdf" and kinds.get("vlc-3.0.21-win64.exe") == "installer" and
          kinds.get("movie.mp4.crdownload") == "partial" and kinds.get("photos-from-ahmed.zip") == "archive" and kinds.get("song.mp3") == "audio")
    check("dates in names: phone, WhatsApp, screenshot, Pixel; none in a plain number",
          fs.name_date("IMG_20240812_101500.jpg") == "2024-08-12T10:15:00" and fs.name_date("WhatsApp Image 2024-08-25 at 20.11.03.jpeg") == "2024-08-25T20:11:03"
          and fs.name_date("Screenshot 2026-09-12 104455.png") == "2026-09-12T10:44:55" and fs.name_date("PXL_20250101_235959123.jpg") == "2025-01-01T23:59:59"
          and fs.name_date("invoice 12345678.pdf") is None and fs.name_date("IMG_20241399_101500.jpg") is None)
    check("taken: the EXIF date, else the date in the name (WhatsApp keeps no EXIF)",
          fs.taken(dl / f"IMG_{y}0903_090500.jpg") == f"{y}-09-03T09:05:00" and fs.taken(dl / f"WhatsApp Image {y}-08-25 at 20.11.03.jpeg") == f"{y}-08-25T20:11:03")
    big = fs.find(idx["files"], kind="pdf", sort="largest")
    check("find: PDFs biggest first; by words; by size", big[0]["size"] >= big[-1]["size"] and len(big) == 3 and
          names(fs.find(idx["files"], words=["invoice"])) == ["Invoice INV-001.docx", "Invoice INV-002.docx"] and
          all(f["size"] > 100_000 for f in fs.find(idx["files"], larger=100_000)))
    groups = fs.duplicates(idx["files"])
    keepers = sorted(fs._keeper(gr)["name"] for gr in groups)
    check("duplicates: the photo and the bill downloaded twice; the originals are kept", len(groups) == 2 and
          keepers == ["Electricity bill Aug.pdf", f"IMG_{y}0812_101500.jpg"], f"{keepers}")

    # ---------------------------------------------------------------- plans
    notes = []
    plan = fs.plan_cleanup(idx, notes=notes)
    binned = sorted(Path(s["src"]).name for s in plan)
    check("clean-up plan: an abandoned download, 2 old installers, 2 copies, the empty folder",
          binned == sorted(["big-file.zip.part", "python-3.12.4-amd64.exe", "vlc-3.0.21-win64.exe", "Electricity bill Aug (1).pdf",
                            f"IMG_{y}0812_101500 (1).jpg", "New folder"]), f"{binned}")
    check("clean-up leaves alone a download still in progress and a new installer", any("movie.mp4.crdownload" in n for n in notes) and
          any("ZoomInstaller.exe" in n for n in notes), f"{notes}")
    org = fs.plan_organize(idx)
    moves = [s for s in org if s["do"] == "move"]
    check("organize plan: every loose file into a folder by kind", len(moves) == 23 and
          {s["group"] for s in moves} >= {"Photos", "PDFs", "Documents", "Installers", "Archives", "Videos", "Music"})
    photos = fs.find(idx["files"], kind="photo")
    ren = fs.plan_rename([f for f in photos if f["name"].startswith("IMG_")], pattern="{taken:%Y-%m-%d %H.%M.%S}")
    pairs = [(Path(s["src"]).name, Path(s["dst"]).name) for s in ren]
    check("rename by date taken: in date order, the original before its copy", pairs[0] == (f"IMG_{y}0812_101500.jpg", f"{y}-08-12 10.15.00.jpg") and
          pairs[1] == (f"IMG_{y}0812_101500 (1).jpg", f"{y}-08-12 10.15.00 (2).jpg"), f"{pairs[:2]}")
    check("a free name when it is taken", fs.unique(dl / "song.mp3").name == "song (2).mp3")

    # ---------------------------------------------------------------- doing and undoing, checked on the disk
    res = fs.execute(org, g)
    left = [p.name for p in dl.iterdir() if p.is_file()]
    check("organize done: no loose files left, every step checked", not left and all(c["ok"] for c in res["checks"]) and not res["errors"], f"{left}")
    back = fs.execute(res["undo"], g)
    check("undo: every file back where it was, the new folders gone", len([p for p in dl.iterdir() if p.is_file()]) == 23 and
          not (dl / "Photos").exists() and not back["errors"])
    victims = [dl / "notes.txt", dl / "budget.xlsx", dl / "song.mp3", dl / "New folder", dl / "Invoice INV-002.docx"]
    t = time.perf_counter()
    r1 = fs.execute([{"do": "trash", "src": str(p)} for p in victims], g)
    t_bin = time.perf_counter() - t
    check("to the Recycle Bin: 5 items in one shell call", len(r1["done"]) == 5 and not any(p.exists() for p in victims), f"{t_bin:.2f}s")
    listed = [it for it in fs.bin_items() if str(BASE).lower() in it["orig"].lower()]
    check("the Recycle Bin lists them with where they were", {it["name"] for it in listed} >= {p.name for p in victims})
    (dl / "notes.txt").write_text("a new file with the old name", encoding="utf-8")
    t = time.perf_counter()
    r2 = fs.execute(r1["undo"], g)
    t_back = time.perf_counter() - t
    check("restore: 4 back in one shell operation", all((dl / n).exists() for n in ("budget.xlsx", "song.mp3", "New folder", "Invoice INV-002.docx")) and
          t_back < 4, f"{t_back:.2f}s")
    check("restore never writes over a file that is there now", (dl / "notes.txt").read_text(encoding="utf-8") == "a new file with the old name" and
          any("is there now" in e for e in r2["errors"]), f"{r2['errors']}")
    (dl / "notes.txt").unlink()
    fs.restore([str(dl / "notes.txt")])
    check("... and once that file is gone, the old one comes back", (dl / "notes.txt").read_text(encoding="utf-8").startswith("Call the bank"))

    # ---------------------------------------------------------------- making things
    z = fs.execute(fs.plan_zip([str(dl / "Bank statement September.pdf"), str(dl / "Electricity bill Aug.pdf")], dl / "bills.zip"), g)
    check("zip: every file reads back", z["checks"][0]["ok"] and zipfile.ZipFile(dl / "bills.zip").testzip() is None)
    u = fs.execute(fs.plan_unzip(dl / "photos-from-ahmed.zip"), g)
    check("unzip into its own folder", u["checks"][0]["ok"] and (dl / "photos-from-ahmed" / "ahmed" / "IMG_1.jpg").exists())
    with zipfile.ZipFile(dl / "evil.zip", "w") as zz:
        zz.writestr("../../outside.txt", "x")
    ev = fs.execute(fs.plan_unzip(dl / "evil.zip"), g)
    check("unzip refuses a file that would land outside its folder", ev["errors"] and not (BASE / "outside.txt").exists(), f"{ev['errors']}")
    im = fs.execute([{"do": "image", "src": str(dl / f"IMG_{y}0819_183000.jpg"), "dst": str(pics / "small.jpg"), "width": 800}], g)
    from PIL import Image
    with Image.open(pics / "small.jpg") as chk:
        ex = chk.getexif().get_ifd(0x8769).get(36867)
        size = chk.size
    check("resize: 800 wide, the date taken kept", im["checks"][0]["ok"] and size == (800, 533) and str(ex).startswith(f"{y}:08:19"), f"{size} {ex}")
    cv = fs.execute([{"do": "image", "src": str(dl / "Screenshot 2026-09-12 104455.png"), "format": "jpg"}], g)
    check("convert PNG -> JPG", cv["checks"][0]["ok"] and (dl / "Screenshot 2026-09-12 104455.jpg").exists())
    mg = fs.execute([{"do": "pdf_merge", "srcs": [str(dl / "Bank statement September.pdf"), str(dl / "Electricity bill Aug.pdf")], "dst": str(docs / "Bills.pdf")}], g)
    check("merge PDFs: every page, a bookmark each", mg["checks"][0]["ok"], mg["checks"][0]["what"] if mg["checks"] else mg["errors"])
    au = fs.execute([{"do": "audio", "src": str(dl / "clip from phone.mp4")}], g)
    check("the sound out of a video, as long as the video", au["checks"][0]["ok"], au["checks"][0]["what"] if au["checks"] else au["errors"])
    op = fs.execute([{"do": "office_pdf", "src": str(dl / "CV - Fareed Hassan.docx")}], g)
    check("Word -> PDF (Word in the background; the .docx untouched)", op["checks"] and op["checks"][0]["ok"] and (dl / "CV - Fareed Hassan.pdf").exists(),
          op["errors"])

    # ---------------------------------------------------------------- settings (a test branch of the registry)
    Fake.wipe()
    s = Settings(Fake(folder=BASE / "startup"))
    try:
        before = s.get("dark_mode")
        r = s.set("dark_mode", not before)
        check("dark mode switched, read back, the old value kept for undo", r["ok"] and s.get("dark_mode") == (not before) and r["undo"]["value"] == before)
        s.apply(r["undo"])
        check("... and undone", s.get("dark_mode") == before)
        r = s.set("file_extensions", True)
        check("file extensions shown", r["ok"] and s.get("file_extensions") is True)
        r = s.set("power_plan", "high performance")
        check("power plan -> High Performance, undo back to Balanced", r["ok"] and s.get("power_plan") == "High Performance" and r["undo"]["value"].lower() == "balanced")
        apps = {a["name"]: a["on"] for a in s.startup()}
        r = s.set_startup("spotify", False)
        check("Spotify kept from starting with Windows (the way Task Manager does it)", apps.get("Spotify") and r["ok"] and
              not {a["name"]: a["on"] for a in s.startup()}["Spotify"])
        s.apply(r["undo"])
        check("... and allowed again by undo", {a["name"]: a["on"] for a in s.startup()}["Spotify"])
        try:
            s.set("default_printer", "a printer that is not there")
            check("an unknown printer is refused", False)
        except SettingError:
            check("an unknown printer is refused", True)
    finally:
        Fake.wipe()

    # ---------------------------------------------------------------- reading requests (rules, no model)
    places = {"downloads": dl, "documents": docs, "pictures": pics}
    foc = [str(dl / "a.jpg"), str(dl / "b.jpg")]

    def op_of(msg, focus=foc):
        r = parse(msg, places, focus)
        return (r["ops"] or [{}])[0], r.get("ask")
    cases = [
        ("what's in my downloads?", lambda o: o["op"] == "summary" and o["where"] == str(dl)),
        ("what's taking space?", lambda o: o["op"] == "find" and o["sort"] == "largest"),
        ("find my CV", lambda o: o["op"] == "find" and o["what"].get("words") == ["cv"]),
        ("find the pictures in downloads", lambda o: o["what"]["where"] == str(dl) and o["what"]["kind"] == "photo"),
        ("find the photos from august", lambda o: o["what"].get("field") == "taken" and o["what"].get("any_year") and o["what"]["since"].startswith(f"{y}-08")),
        ("show me pdfs bigger than 100 kb in downloads", lambda o: o["what"].get("larger") == 100_000 and o["what"]["kind"] == "pdf"),
        ("how many pdfs are in documents?", lambda o: o.get("count") and o["what"]["where"] == str(docs)),
        ("what did I download this week?", lambda o: o["what"]["where"] == str(dl) and o["what"].get("since")),
        ("move it to documents", lambda o: o["op"] == "move" and o["what"] == {"focus": True, "one": True} and o["to"] == str(docs)),
        ("move them to documents", lambda o: o["what"] == {"focus": True}),
        ("make the second one my wallpaper", lambda o: o["op"] == "wallpaper" and o["what"].get("pick") == 2),
        ("delete number 3", lambda o: o["op"] == "trash" and o["what"].get("pick") == 3),
        ("open the last one", lambda o: o["op"] == "open" and o["what"].get("pick") == -1),
        ("move the invoices to a folder called Invoices in documents", lambda o: o["op"] == "move" and o["to"] == str(docs / "Invoices")),
        ("delete the new folder", lambda o: o["op"] == "trash" and o["what"].get("dirs") == [str(dl / "New folder")]),
        ("rename the new folder to Taxes", lambda o: o["op"] == "rename" and o["what"].get("dirs") and o["to"] == "Taxes"),
        ("rename the photos in downloads by the date taken", lambda o: o["op"] == "rename" and "taken" in o["pattern"] and o["what"]["kind"] == "photo"),
        ("rename them to Lahore trip", lambda o: o["op"] == "rename" and o["to"] == "Lahore trip"),
        ("delete movie.mp4.crdownload", lambda o: o["op"] == "trash" and o["what"]["names"] == ["movie.mp4.crdownload"]),
        ("delete it permanently", lambda o: o["op"] == "trash" and o.get("forever")),
        ("zip the pdfs in downloads", lambda o: o["op"] == "zip" and o["what"]["kind"] == "pdf"),
        ("unzip photos-from-ahmed.zip", lambda o: o["op"] == "unzip" and o["what"]["names"] == ["photos-from-ahmed.zip"]),
        ("merge the pdfs in documents into one", lambda o: o["op"] == "merge_pdfs" and not o.get("name")),
        ("merge the pdfs called Bills 2026", lambda o: o["op"] == "merge_pdfs" and o.get("name") == "Bills 2026"),
        ("convert the word documents in documents to pdf", lambda o: o["op"] == "convert" and o["to"] == "pdf" and o["what"]["where"] == str(docs)),
        ("resize them to 800 pixels wide", lambda o: o["op"] == "resize" and o["width"] == 800),
        ("extract the audio from the clip", lambda o: o["op"] == "audio"),
        ("clean up my downloads", lambda o: o["op"] == "cleanup" and o["where"] == str(dl)),
        ("organize my downloads", lambda o: o["op"] == "organize" and o["by"] == "kind"),
        ("organize my pictures", lambda o: o["op"] == "organize" and o["where"] == str(pics) and o["by"] == "date" and o["taken"]),
        ("remove the duplicates in downloads", lambda o: o["op"] == "dedupe"),
        ("what's in the recycle bin?", lambda o: o["op"] == "bin_list"),
        ("restore notes.txt from the recycle bin", lambda o: o["op"] == "bin_restore" and o["what"]["names"] == ["notes.txt"]),
        ("restore the first one", lambda o: o["op"] == "bin_restore" and o.get("pick") == 1),
        ("empty the recycle bin", lambda o: o["op"] == "say" and "don't empty" in o["text"]),
        ("turn on light mode", lambda o: o == {"op": "setting", "name": "dark_mode", "value": False}),
        ("is dark mode on?", lambda o: o["op"] == "setting_get"),
        ("show file extensions", lambda o: o == {"op": "setting", "name": "file_extensions", "value": True}),
        ("switch to high performance", lambda o: o["op"] == "setting" and o["value"] == "high performance"),
        ("stop spotify from starting with windows", lambda o: o["op"] == "startup" and o["app"] == "spotify" and o["on"] is False),
        ("what starts with windows?", lambda o: o["op"] == "startup_list"),
        ("how much space is left?", lambda o: o["op"] == "space"),
    ]
    bad = []
    for msg, ok in cases:
        o, ask = op_of(msg)
        try:
            good = bool(o) and ok(o)
        except Exception:  # noqa: BLE001
            good = False
        if not good:
            bad.append(f"{msg!r} -> {o or ask}")
    check(f"requests read by rules: {len(cases) - len(bad)}/{len(cases)}", not bad, "; ".join(bad[:4]))
    o, ask = op_of("find the pdfs in the invoices folder")
    check("a folder that is not there is said back, not guessed", o.get("what", {}).get("missing_folder") == "invoices", f"{o}")

    # ---------------------------------------------------------------- nothing left in the Recycle Bin from these tests
    left = [it["orig"] for it in fs.bin_items() if str(BASE).lower() in it["orig"].lower()]
    if left:
        fs.restore(left)
    check("the Recycle Bin holds nothing from the tests", not [it for it in fs.bin_items() if str(BASE).lower() in it["orig"].lower()])
    print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.0f} s)")
    return not FAILS


if __name__ == "__main__":
    ok = main()
    shutil.rmtree(BASE / "startup", ignore_errors=True)
    sys.exit(0 if ok else 1)

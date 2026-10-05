"""Designs to code: Figma and Canva connected, and a design becoming a checked web project.

  python tests/integration/test_design2code.py

- the converter on a landing page in Figma's exact JSON (every box worked out by hand): every element where the design
  puts it, every text there, real HTML (landmarks, a heading, a button, a list, a link), the CSS Figma's rules call for
- the checks catch a spoiled page (a moved title, a lost text), and the picture comparison finds a changed region
- fonts: Google's CSS read, only the latin parts kept, the files saved into the project
- Canva's route: a design saved as PowerPoint, read and converted; PowerPoint's own pictures of the pages as the reference
- Figma and Canva connectors against fake servers: caching, exports and downloads (no key sent to download hosts), jobs
  polled, errors explained, comments posted, checked and taken back, Canva's sign-in (PKCE) and token refresh
- the coding chat makes a project from a Figma link and from a Canva design; the hub lists, exports, uploads and comments
Nothing here writes outside out/_tests/design2code; no real Figma or Canva account is used.
"""
import base64
import hashlib
import json
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_fixture import landing, pictures  # noqa: E402
from pptx_fixture import make as make_pptx  # noqa: E402

from ai_pc.coding import design2code as D  # noqa: E402
from ai_pc.coding import designcheck as DC  # noqa: E402
from ai_pc.coding import fromdesign as FD  # noqa: E402
from ai_pc.coding import pptxtree as PT  # noqa: E402
from ai_pc.hub.http import FakeTransport, HubError  # noqa: E402
from ai_pc.hub.services import canva as CV  # noqa: E402
from ai_pc.hub.services import figma as FG  # noqa: E402

OUT = ROOT / "out" / "_tests" / "design2code"
KEY = "TESTabcdef123456"
RESULTS = []


def rmtree(p):
    """Delete a folder, git's read-only files too (Windows will not delete them otherwise)."""
    import os
    import stat

    def again(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if Path(p).exists():
        shutil.rmtree(p, onexc=again)


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f"\n     why: {str(detail)[:600]}"))


# ---------------------------------------------------------------- the converter
def converter():
    doc, nid = landing()
    imgs = pictures(OUT / "pics")
    folder = OUT / "landing"
    page = D.build(doc, nid, imgs, origin_info={"file": KEY})
    css, saved, missing = D.google_fonts(page.fonts, folder)
    files = page.write(folder, css)
    check("converter: the files are written", all((folder / f).exists() for f in ("index.html", "styles.css", "README.md", "design/design.json")), files)
    check("converter: the fonts are Arial (on the PC) and Poppins (saved, or named missing when offline)", set(page.fonts) == {"Arial", "Poppins"}
          and (saved == ["Poppins"] or missing == ["Poppins"]), (saved, missing))
    if saved:
        check("converter: Poppins' files are in the project", any((folder / "assets" / "fonts").glob("poppins-700-latin*.woff2")))
    h, c = page.html, page.css
    check("converter: landmarks for the bar, the sections and the footer", '<nav class="navbar">' in h and '<section class="hero">' in h and
          '<section class="features">' in h and '<footer class="footer">' in h, h[:400])
    check("converter: the biggest text is the heading, a logo in the bar is not", '<h1 class="title">Best prices in town</h1>' in h and
          '<p class="logo">Khan Electronics</p>' in h)
    check("converter: the button is a button, with its text inside", '<button class="call-button" type="button">' in h and
          '<span class="call-now">Call now</span>' in h)
    check("converter: the list is a list", h.count("<li>") == 3 and '<ul class="promises-list">' in h)
    check("converter: the link is a link", '<a href="https://example.com/shop">Visit our shop</a>' in h)
    check("converter: the masked photo is a picture inside a round clip", '<img class="founder-photo" src="assets/founder-photo.png" alt="Founder photo">' in h
          and ".circle {" in c and "border-radius: 50%" in c.split(".circle {")[1].split("}")[0])
    check("converter: mixed styles keep their own span", '<span class="subtitle-s1">1 year warranty</span>' in h and
          "color: #fbbf24" in c.split(".subtitle-s1 {")[1].split("}")[0])
    nav = c.split(".navbar {")[1].split("}")[0]
    check("converter: auto layout becomes flexbox (space between, centred, padding)", "display: flex" in nav and "justify-content: space-between" in nav
          and "align-items: center" in nav and "padding: 0 80px 0 80px" in nav, nav)
    card = c.split(".card {")[1].split("}")[0]
    check("converter: a card that fills its row shares it (flex 1 1 0), with its border, corners and shadow", "flex: 1 1 0" in card and
          "outline: 1px solid #e2e8f0" in card and "outline-offset: -1px" in card and "border-radius: 16px" in card and
          "box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08)" in card, card)
    check("converter: the button's gradient runs left to right", "linear-gradient(90deg, #2563eb 0%, #7c3aed 100%)" in c)
    badge = c.split(".badge {")[1].split("}")[0]
    check("converter: the badge keeps its turn (15 degrees)", "matrix(0.965926, -0.258819, 0.258819, 0.965926, 0, 0)" in badge, badge)
    check("converter: icons are SVG from the design's outlines; the turned star's turn is inside it", h.count("<svg") == 5 and
          'transform="matrix(0.866025 -0.5 0.5 0.866025' in h)
    check("converter: no notes (everything was kept)", not page.notes, page.notes)
    r = DC.check(folder)
    check("measure: every element where the design puts it", r["placed"][0] == r["placed"][1] == 37, r["lines"])
    check("measure: every text there, none spilling", r["texts"]["present"] == r["texts"]["total"] == 17 and not r["texts"]["spill"], r["texts"])
    check("measure: the fonts are loaded in the page" if saved else "measure: a missing font is named", (not r["fonts_missing"]) if saved
          else r["fonts_missing"] == ["Poppins"], r["fonts_missing"])
    return folder, r


def spoiled(folder):
    bad = OUT / "landing_spoiled"
    shutil.rmtree(bad, ignore_errors=True)
    shutil.copytree(folder, bad, ignore=shutil.ignore_patterns(".out"))
    css = (bad / "styles.css").read_text(encoding="utf-8")
    css = css.replace(".title {\n  position: absolute;\n  left: 360px;", ".title {\n  position: absolute;\n  left: 400px;")
    (bad / "styles.css").write_text(css, encoding="utf-8")
    h = (bad / "index.html").read_text(encoding="utf-8").replace("Easy instalments", "Easy payments")
    (bad / "index.html").write_text(h, encoding="utf-8")
    r = DC.check(bad, shot=False)
    check("measure: a moved title is caught and named", r["placed"][0] < r["placed"][1] and any("'Title' is 40 px right" in w for w in r["worst"]), r["worst"])
    check("measure: a changed text is caught", r["texts"]["present"] == 16 and r["texts"]["missing"] == ["Card title"], r["texts"])
    check("measure: the page is not passed", not r["ok"])


def picture_match(folder):
    shot = folder / ".out" / "page.png"
    r = DC.picture(shot, shot, OUT / "same.png")
    check("picture: a page against itself is the same (similarity 1.0)", r["ssim"] >= 0.999 and r["delta_e"] < 0.01, r)
    from PIL import Image, ImageDraw
    im = Image.open(shot).convert("RGB")
    ImageDraw.Draw(im).rectangle([960, 700, 1400, 900], fill=(200, 30, 30))  # something the page does not have, at the right of the cards
    ref = OUT / "ref_changed.png"
    im.save(ref)
    meta = json.loads((folder / "design" / "design.json").read_text(encoding="utf-8"))
    r = DC.picture(shot, ref, OUT / "changed.png", meta)
    worst = r["cells"][0]
    check("picture: a changed region lowers the similarity and is found", r["ssim"] < 0.97 and worst[2].startswith("right,"), r)
    check("picture: and the elements near it are named", "Easy instalments" in " ".join(worst[3]) or "Card" in " ".join(worst[3]), worst)


def fonts():
    css = ("/* cyrillic */\n@font-face {\n  font-family: 'Test Sans';\n  font-style: normal;\n  font-weight: 400;\n  src: url(https://fonts.gstatic.com/s/t/a-cyr.woff2) format('woff2');\n}\n"
           "/* latin */\n@font-face {\n  font-family: 'Test Sans';\n  font-style: normal;\n  font-weight: 400;\n  src: url(https://fonts.gstatic.com/s/t/a-lat.woff2) format('woff2');\n}\n")
    asked = []

    def fetch(url):
        asked.append(url)
        if "fonts.googleapis.com" in url:
            if "Nope" in url:
                raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
            return css.encode()
        return b"wOF2" + url.encode()
    import urllib.error
    old = D.FONT_CACHE
    D.FONT_CACHE = OUT / "fontcache"
    shutil.rmtree(D.FONT_CACHE, ignore_errors=True)
    try:
        folder = OUT / "fonts"
        shutil.rmtree(folder, ignore_errors=True)
        out, saved, missing = D.google_fonts({"Test Sans": {(400, False)}, "Nope Font": {(700, True)}, "Arial": {(400, False)}}, folder, fetch)
        files = sorted(p.name for p in (folder / "assets" / "fonts").glob("*"))
        check("fonts: only the latin part is kept and saved", files == ["test-sans-400-latin.woff2"] and "a-cyr" not in out, files)
        check("fonts: the CSS points at the saved file", "url(assets/fonts/test-sans-400-latin.woff2)" in out and "gstatic" not in out, out)
        check("fonts: a family Google lacks is named; Arial is never fetched", missing == ["Nope Font"] and saved == ["Test Sans"]
              and not any("Arial" in u for u in asked), (saved, missing))
        check("fonts: the request lists styles by italic, then weight", any("ital,wght@1,700" in u for u in asked), asked)
        n = len(asked)
        D.google_fonts({"Test Sans": {(400, False)}}, OUT / "fonts2", fetch)
        check("fonts: a second project uses the saved copies (no download)", len(asked) == n, asked[n:])
    finally:
        D.FONT_CACHE = old


# ---------------------------------------------------------------- Canva's route: PowerPoint
def powerpoint():
    from ai_pc.office import render
    base = OUT / "pptx"
    base.mkdir(parents=True, exist_ok=True)
    pics = pictures(OUT / "pics")
    deck = make_pptx(base / "sale.pptx", pics["hero-photo"])
    ref = base / "ref"
    shutil.rmtree(ref, ignore_errors=True)
    ref.mkdir()
    r = render.office({"app": "powerpoint", "src": str(deck.resolve()), "png_dir": str(ref.resolve()), "png_width": 1920}, timeout=180)
    check("pptx: PowerPoint draws the two pages (the reference)", r.get("ok") and len(list(ref.glob("slide*.png"))) == 2, r.get("error"))
    refs = {i: str(ref / f"slide{i:03d}.png") for i in (1, 2)}
    tree, imgs, notes = PT.load(deck, [1], refs, work=base / "img", title="Eid sale")
    root = tree["document"]["children"][0]["children"][0]
    kinds = [n["type"] for n in D.walk(root)][1:]
    check("pptx: page 1 is read as a frame of 1920 x 1080", root["absoluteBoundingBox"]["width"] == 1920 and root["absoluteBoundingBox"]["height"] == 1080)
    texts = [n for n in D.walk(root) if n["type"] == "TEXT"]
    title = next(t for t in texts if t["characters"] == "Eid Mubarak Sale")
    check("pptx: 'Montserrat Bold' is Montserrat at weight 700, 66 pt = 88 px", title["style"]["fontFamily"] == "Montserrat" and
          title["style"]["fontWeight"] == 700 and abs(title["style"]["fontSize"] - 88) < 0.01, title["style"])
    btn = next(t for t in texts if t["characters"] == "Shop now")
    check("pptx: the button's text: capitals, letter spacing, centred both ways", btn["style"].get("textCase") == "UPPER" and
          abs(btn["style"]["letterSpacing"] - 2.0) < 0.01 and btn["style"]["textAlignHorizontal"] == "CENTER" and btn["style"]["textAlignVertical"] == "CENTER",
          btn["style"])
    lst = next(t for t in texts if t["characters"].startswith("Free delivery"))
    check("pptx: bullets and a link are read", lst["lineTypes"][:2] == ["UNORDERED", "UNORDERED"] and
          any((v.get("hyperlink") or {}).get("url") == "https://example.com/shop" for v in lst["styleOverrideTable"].values()), lst["styleOverrideTable"])
    check("pptx: the photo (cropped), the rounded button, the oval, the group, the line and the triangle are all there",
          kinds.count("RECTANGLE") >= 6 and "ELLIPSE" in kinds and "GROUP" in kinds and "VECTOR" in kinds, kinds)
    out = {}
    for pages in ([1], [2], [1, 2]):
        name = "page" + "_".join(map(str, pages))
        folder = base / name
        shutil.rmtree(folder, ignore_errors=True)
        t, im, nt = PT.load(deck, pages, refs, work=base / "img", title="Eid sale")
        page = D.build(t, None, im, source="canva", title="Eid sale")
        page.notes = nt + page.notes
        fcss, saved, _ = D.google_fonts(page.fonts, folder)
        page.write(folder, fcss)
        reff = refs[pages[0]] if len(pages) == 1 else FD._stack([refs[p] for p in pages], page.w, base / "stacked.png")
        shutil.copyfile(reff, folder / "design" / "reference.png")
        out[name] = (DC.check(folder), page, nt)
    r1, p1, _ = out["page1"]
    check("pptx: page 1 as a web page: every element in place, every text there", r1["placed"][0] == r1["placed"][1] and
          r1["texts"]["present"] == r1["texts"]["total"] == 4, r1["lines"])
    check("pptx: page 1 looks like PowerPoint's picture of it (similarity >= 0.9)", r1["picture"] and r1["picture"]["ssim"] >= 0.9, r1["picture"])
    r2, p2, n2 = out["page2"]
    check("pptx: the chart has no web equivalent: it is cut from the page's picture, and said so", any("Chart" in n and "picture cut" in n for n in n2)
          and any(a.startswith("assets/") for a in p2.assets), n2)
    check("pptx: page 2 looks like PowerPoint's picture of it (similarity >= 0.95)", r2["picture"] and r2["picture"]["ssim"] >= 0.95, r2["picture"])
    r3, p3, _ = out["page1_2"]
    check("pptx: two pages become one page of two sections", p3.h == 2160 and p3.html.count("<section") == 2 and r3["placed"][0] == r3["placed"][1],
          (p3.h, r3["lines"]))
    return deck, refs


# ---------------------------------------------------------------- connectors against fake servers
def figma_fake(doc, png, version):
    comments = []

    def images(req):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req["url"]).query)
        ids = q["ids"][0].split(",")
        return 200, {"err": None, "images": {i: f"https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/{i.replace(':', '-')}" for i in ids}}

    def post_comment(req):
        c = {"id": f"c{len(comments) + 1}", "message": req["body"]["message"], "user": {"handle": "Fareed"}, "created_at": "2026-10-04T10:00:00Z"}
        comments.append(c)
        return 200, c

    def del_comment(req):
        cid = req["url"].rsplit("/", 1)[1]
        comments[:] = [c for c in comments if c["id"] != cid]
        return 200, {}
    pics = {k: Path(v).read_bytes() for k, v in pictures(OUT / "pics").items()}
    return FakeTransport({
        ("GET", "v1/me"): (200, {"id": "1", "handle": "Fareed", "email": "fareed@example.com"}),
        ("GET", f"v1/files/{KEY}/meta"): lambda req: (200, {"file": {"name": doc["name"], "version": version[0], "last_touched_at": "2026-10-04T08:00:00Z"}}),
        ("GET", f"v1/files/{KEY}/images"): (200, {"error": False, "status": 200, "meta": {"images": {
            "hero-photo": "https://s3-alpha.figma.com/img/hero", "face": "https://s3-alpha.figma.com/img/face"}}}),
        ("GET", f"v1/files/{KEY}/comments"): lambda req: (200, {"comments": list(comments)}),
        ("POST", f"v1/files/{KEY}/comments"): post_comment,
        ("DELETE", f"v1/files/{KEY}/comments/"): del_comment,
        ("GET", f"v1/files/{KEY}"): lambda req: (200, dict(doc, version=version[0])),
        ("GET", f"v1/images/{KEY}"): images,
        ("GET", "s3-alpha.figma.com/img/hero"): (200, pics["hero-photo"]),
        ("GET", "s3-alpha.figma.com/img/face"): (200, pics["face"]),
        ("GET", "amazonaws.com/images/"): (200, png),
        ("GET", "v1/files/LIMITEDkey123/meta"): (429, {"status": 429, "err": "Rate limit exceeded"}),
        ("GET", "v1/files/LIMITEDkey123"): (429, {"status": 429, "err": "Rate limit exceeded"}),
        ("GET", "v1/files/PRIVATEkey123"): (403, {"status": 403, "err": "Forbidden"}),
    })


def figma(shot_png):
    doc, nid = landing()
    version = ["2001"]
    fake = figma_fake(doc, Path(shot_png).read_bytes(), version)
    f = FG.Figma(creds={"token": "figd_TEST_SECRET"}, transport=fake)
    check("figma: who is connected", f.whoami() == {"who": "Fareed", "where": "fareed@example.com"})
    check("figma: links to keys and frames", FG.key_of("https://www.figma.com/design/AbCdEf123456/Shop?node-id=12-34&t=x") == ("AbCdEf123456", "12:34")
          and FG.key_of("https://www.figma.com/file/AbCdEf123456/Shop?node-id=12%3A34") == ("AbCdEf123456", "12:34"))
    try:
        FG.key_of("https://example.com/not-figma")
        check("figma: a link that is not Figma's is refused", False)
    except HubError:
        check("figma: a link that is not Figma's is refused", True)
    n0 = len(fake.sent)
    f.file(KEY)
    f.file(KEY)
    calls = [r["url"].split("api.figma.com/")[1].split("?")[0] for r in fake.sent[n0:]]
    check("figma: a file is read once, then only its version is asked (the cheap call)", calls == [f"v1/files/{KEY}", f"v1/files/{KEY}/meta"], calls)
    version[0] = "2002"
    n0 = len(fake.sent)
    f.file(KEY)
    calls = [r["url"].split("api.figma.com/")[1].split("?")[0] for r in fake.sent[n0:]]
    check("figma: a changed file is read again", calls == [f"v1/files/{KEY}/meta", f"v1/files/{KEY}"], calls)
    check("figma: the file is asked for with its outlines (geometry=paths)", "geometry=paths" in fake.sent[-1]["url"])
    check("figma: the key goes in Figma's own header", fake.sent[-1]["headers"].get("X-Figma-Token") == "figd_TEST_SECRET")
    fr = f.frames(KEY)
    check("figma: the frames are listed", [x["name"] for x in fr] == ["Home"] and fr[0]["w"] == 1440 and fr[0]["h"] == 1180, fr)
    n0 = len(fake.sent)
    got = f.export(KEY, ["0:1"], "png", scale=1, folder=OUT / "exports", names={"0:1": "Home"})
    check("figma: a frame exported in one request and saved", len(got) == 1 and Path(got[0]["path"]).name == "Home.png" and Path(got[0]["path"]).exists(), got)
    dl = [r for r in fake.sent[n0:] if "amazonaws.com" in r["url"]]
    check("figma: the key is never sent to the download host", dl and "X-Figma-Token" not in dl[0]["headers"])
    imgs = f.download_images(KEY, {"hero-photo", "face"}, OUT / "figma_images")
    n0 = len(fake.sent)
    again = f.download_images(KEY, {"hero-photo", "face"}, OUT / "figma_images")
    check("figma: the pictures a frame uses are downloaded once", sorted(imgs) == ["face", "hero-photo"] and again == imgs and len(fake.sent) == n0,
          (imgs, len(fake.sent) - n0))
    t = f.tokens(KEY)
    check("figma: the design's colours and text styles", t["colors"][0]["hex"] in ("#ffffff", "#0f172a") and
          {(x["family"], x["size"]) for x in t["text"]} >= {("Poppins", 56), ("Arial", 16), ("Poppins", 24)}, (t["colors"][:3], t["text"][:4]))
    res = f.comment(KEY, "Looks good, ship it", "0:1")
    check("figma: a comment is posted and read back", res["verified"] and res["undo"]["op"] == "uncomment", res)
    f.uncomment(KEY, res["id"])
    check("figma: and taken back", f.comments(KEY) == [])
    for key, want in (("LIMITEDkey123", "20 file reads a month"), ("PRIVATEkey123", "cannot open that file")):
        try:
            f.file(key, fresh=True)
            check(f"figma: {want} is explained", False)
        except HubError as e:
            check(f"figma: '{want}' is explained", want in str(e), str(e))
    return fake


def canva_fake(deck, pngs):
    state = {"polls": 0, "assets": {}}

    def designs(req):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req["url"]).query)
        if q.get("continuation") == ["p2"]:
            return 200, {"items": [{"id": "DAF00000002", "title": "Eid sale", "urls": {"edit_url": "https://www.canva.com/design/DAF00000002/edit"},
                                    "page_count": 2, "thumbnail": {"width": 1920, "height": 1080}}]}
        return 200, {"items": [{"id": "DAF00000001", "title": "Shop logo", "urls": {"edit_url": "https://www.canva.com/design/DAF00000001/edit"},
                                "page_count": 1}], "continuation": "p2"}

    def job(path_kind):
        def f(req):
            state["polls"] += 1
            jid = req["url"].rsplit("/", 1)[1].split("?")[0]
            if state["polls"] % 2:  # the first ask finds it still working
                return 200, {"job": {"id": jid, "status": "in_progress"}}
            if path_kind == "exports":
                urls = {"job-pptx": ["https://export-download.canva.com/x/design.pptx"],
                        "job-png": [f"https://export-download.canva.com/x/p{n}.png" for n in (state.get("pages") or [1, 2])],
                        "job-pdf": ["https://export-download.canva.com/x/design.pdf"]}.get(jid)
                if jid == "job-bad":
                    return 200, {"job": {"id": jid, "status": "failed", "error": {"code": "license_required", "message": "Premium elements"}}}
                return 200, {"job": {"id": jid, "status": "success", "urls": urls}}
            if path_kind == "imports":
                return 200, {"job": {"id": jid, "status": "success", "result": {"designs": [{"id": "DAF00000009", "title": "Report",
                                                                                              "urls": {"edit_url": "https://www.canva.com/design/DAF00000009/edit"}}]}}}
            state["assets"]["A1"] = {"id": "A1", "name": "logo"}
            return 200, {"job": {"id": jid, "status": "success", "asset": {"id": "A1", "name": "logo"}}}
        return f

    def start_export(req):
        t = req["body"]["format"]["type"]
        state["pages"] = req["body"]["format"].get("pages")  # Canva sends one file per page asked for
        return 200, {"job": {"id": "job-bad" if req["body"]["design_id"] == "DAF00000001" and t == "pdf" else f"job-{t}", "status": "in_progress"}}

    def asset(req):
        aid = req["url"].rsplit("/", 1)[1]
        if req["method"] == "DELETE":
            state["assets"].pop(aid, None)
            return 204, {}
        return (200, {"asset": state["assets"][aid]}) if aid in state["assets"] else (404, {"message": "no asset"})
    return FakeTransport({
        ("GET", "users/me/profile"): (200, {"profile": {"display_name": "Fareed"}}),
        ("GET", "users/me"): (200, {"team_user": {"user_id": "U1", "team_id": "T1"}}),
        ("GET", "rest/v1/designs/DAF00000099"): (200, {"design": {"id": "DAF00000099", "title": "Eid offer", "urls": {"edit_url": "https://x/edit"}}}),
        ("GET", "rest/v1/designs/DAF00000009"): (200, {"design": {"id": "DAF00000009", "title": "Report", "urls": {}}}),
        ("GET", "rest/v1/designs"): designs,
        ("POST", "rest/v1/designs"): (200, {"design": {"id": "DAF00000099", "title": "Eid offer", "urls": {"edit_url": "https://x/edit"}}}),
        ("POST", "rest/v1/imports"): (200, {"job": {"id": "imp1", "status": "in_progress"}}),
        ("GET", "rest/v1/imports/"): job("imports"),
        ("POST", "rest/v1/exports"): start_export,
        ("GET", "rest/v1/exports/"): job("exports"),
        ("POST", "rest/v1/asset-uploads"): (200, {"job": {"id": "up1", "status": "in_progress"}}),
        ("GET", "rest/v1/asset-uploads/"): job("uploads"),
        ("GET", "rest/v1/assets/"): asset,
        ("DELETE", "rest/v1/assets/"): asset,
        ("GET", "export-download.canva.com/x/design.pptx"): (200, Path(deck).read_bytes()),
        ("GET", "export-download.canva.com/x/p1.png"): (200, Path(pngs[1]).read_bytes()),
        ("GET", "export-download.canva.com/x/p2.png"): (200, Path(pngs[2]).read_bytes()),
        ("GET", "export-download.canva.com/x/design.pdf"): (200, b"%PDF-1.7 test"),
    })


def canva(deck, pngs):
    fake = canva_fake(deck, pngs)
    c = CV.Canva(creds={"access_token": "CANVA_TEST_TOKEN"}, transport=fake)
    check("canva: who is connected", c.whoami() == {"who": "Fareed", "where": "Canva"})
    ds = c.designs()
    check("canva: designs, all pages of the list", [d["name"] for d in ds] == ["Shop logo", "Eid sale"], ds)
    d = c.find("eid sale")
    check("canva: a design found by its name", d["id"] == "DAF00000002" and d["pages"] == 2)
    res = c.export(d, "pdf", folder=OUT / "canva_exports")
    check("canva: an export is started, waited for, downloaded and saved", res["files"] and Path(res["files"][0]).read_bytes().startswith(b"%PDF"), res)
    dl = [r for r in fake.sent if "export-download" in r["url"]]
    check("canva: the key is never sent to the download host", dl and "Authorization" not in dl[0]["headers"])
    res = c.export(d, "png", folder=OUT / "canva_exports")
    check("canva: a two-page PNG export saves both pages", [Path(p).name for p in res["files"]] == ["Eid_sale_p1.png", "Eid_sale_p2.png"], res)
    res = c.export(d, "png", folder=OUT / "canva_exports", pages=[2])
    check("canva: one page asked for, that page saved (named by its number)", [Path(p).name for p in res["files"]] == ["Eid_sale_p2.png"], res)
    try:
        c.export(c.find("Shop logo"), "pdf")
        check("canva: a failed export explains itself", False)
    except HubError as e:
        check("canva: a failed export explains itself (paid elements)", "paid Canva elements" in str(e), str(e))
    try:
        c.export(d, "docx")
        check("canva: a format Canva cannot make is refused", False)
    except HubError as e:
        check("canva: a format Canva cannot make is refused", "cannot export docx" in str(e))
    res = c.create("Eid offer", "instagram post")
    body = next(r["body"] for r in fake.sent if r["method"] == "POST" and r["url"].endswith("/designs"))
    check("canva: a new design of a named size, read back", res["verified"] and body["design_type"] == {"type": "custom", "width": 1080, "height": 1080}, body)
    src = OUT / "report.pptx"
    shutil.copyfile(deck, src)
    res = c.import_file(src, "Report")
    imp = next(r for r in fake.sent if r["method"] == "POST" and r["url"].endswith("/imports"))
    meta = json.loads(imp["headers"]["Import-Metadata"])
    check("canva: a file imported as an editable design (title in base64, the file as it is)", res["id"] == "DAF00000009" and
          base64.b64decode(meta["title_base64"]).decode() == "Report" and imp["headers"]["Content-Type"] == "application/octet-stream", meta)
    logo = OUT / "pics" / "face.png"
    res = c.upload(logo, "logo")
    check("canva: a picture uploaded to your Canva uploads, read back", res["verified"] and res["undo"] == {"service": "canva", "op": "delete_asset", "id": "A1"})
    c.delete_asset("A1")
    try:
        c.api().get("assets/A1")
        check("canva: and deleted again (undo)", False)
    except HubError:
        check("canva: and deleted again (undo)", True)
    return fake


def canva_signin():
    from ai_pc.core import vault as V
    from ai_pc.hub import oauth
    old_file, old_redirect = V.FILE, oauth.CANVA_REDIRECT
    V.FILE = OUT / "vault_test.bin"
    V.FILE.unlink(missing_ok=True)
    oauth.CANVA_REDIRECT = ("127.0.0.1", 0, "/oauth/redirect")  # any free port here (the real one is the fixed 3001)
    seen = {}

    def browser(url):  # the person signs in: Canva sends the browser back to this PC with a code
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        seen.update(q)
        back = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "CODE123", "state": q["state"]})
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=10).read(), daemon=True).start()

    def token(req):
        seen["token_req"] = req
        form = dict(urllib.parse.parse_qsl(req["body"].decode() if isinstance(req["body"], bytes) else str(req["body"])))
        seen["form"] = form
        if form.get("grant_type") == "refresh_token":
            return 200, {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 14400}
        return 200, {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 14400}
    fake = FakeTransport({("POST", "oauth/token"): token})
    try:
        oauth.canva_signin("OC-CLIENT", "SECRET-XYZ", open_url=browser, show=lambda s: None, timeout=20, transport=fake)
        form = seen["form"]
        ok_pkce = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode() == seen["code_challenge"]
        check("canva sign-in: PKCE (s256): the verifier sent matches the challenge shown", ok_pkce and seen["code_challenge_method"] == "s256")
        basic = seen["token_req"]["headers"]["Authorization"]
        check("canva sign-in: the code is exchanged with the client's own Basic key", basic == "Basic " + base64.b64encode(b"OC-CLIENT:SECRET-XYZ").decode()
              and form["grant_type"] == "authorization_code" and form["code"] == "CODE123")
        check("canva sign-in: the asked scopes are the listed ones", seen["scope"].split() == oauth.CANVA_SCOPES)
        v = V.get("canva")
        check("canva sign-in: the tokens are kept in the vault", v["access_token"] == "AT1" and v["refresh_token"] == "RT1" and v["client_id"] == "OC-CLIENT")
        V.put("canva", {"expires_at": time.time() - 5})
        tok = oauth.access_token("canva", transport=fake)
        v = V.get("canva")
        check("canva sign-in: an old token is refreshed, and Canva's new refresh token kept", tok == "AT2" and v["refresh_token"] == "RT2"
              and seen["form"]["refresh_token"] == "RT1")
    finally:
        V.FILE.unlink(missing_ok=True)
        V.FILE, oauth.CANVA_REDIRECT = old_file, old_redirect


# ---------------------------------------------------------------- the coding chat and the hub
def edit_forms():
    """The cheap model does not always write its edit blocks the same way: each form seen in practice is read."""
    from ai_pc.coding.project import edit_blocks
    S, E, R = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"
    cases = [(f"FILE: index.html\n{S}\nold\n{E}\nnew\n{R}", [("index.html", "old", "new")]),
             (f"index.html\n{S}\nold\n{E}\nnew\n{R}", [("index.html", "old", "new")]),
             (f"{S}\nindex.html\n{S}\nold\n{E}\nnew\n{R}", [("index.html", "old", "new")]),
             (f"**styles.css**\n```css\n{S}\n.a {{ color: red; }}\n{E}\n.a {{ color: green; }}\n{R}\n```",
              [("styles.css", ".a { color: red; }", ".a { color: green; }")]),
             (f"Here is the change:\n{S}\nold\n{E}\nnew\n{R}", [(None, "old", "new")]),
             (f"FILE: a.py\n{S}\nx = 1\n{E}\nx = 2\n{R}\n\nFile: b/c.py\n{S}\ny\n{E}\nz\n{R}", [("a.py", "x = 1", "x = 2"), ("b/c.py", "y", "z")])]
    bad = [(t[:30], edit_blocks(t)) for t, want in cases if edit_blocks(t) != want]
    check("code chat: edit blocks are read in every form the model writes them (named, bare, bold, fenced, a stray marker, unnamed)", not bad, bad)


def chats(figma_fake_t, canva_fake_t):
    from ai_pc.coding.codechat import CodeChat
    from ai_pc.hub.hubchat import HubChat
    projects = OUT / "projects"
    rmtree(projects)
    f = FG.Figma(creds={"token": "figd_TEST_SECRET"}, transport=figma_fake_t)
    c = CV.Canva(creds={"access_token": "CANVA_TEST_TOKEN"}, transport=canva_fake_t)
    cc = CodeChat.start(chats_dir=OUT / "chats", projects_dir=projects, connectors={"figma": f, "canva": c})
    r = cc.say("make a website from my figma file")
    check("code chat: without a link it asks for one", "Paste the Figma link" in r, r)
    r = cc.say(f"make a website from https://www.figma.com/design/{KEY}/Khan-Electronics?node-id=0-1")
    check("code chat: a Figma link becomes a project", "Made khan_electronics_site_home (web) from the Figma frame 'Home'" in r, r)
    check("code chat: and it is measured: all 37 elements and 17 texts", "37/37 elements where the design puts them" in r and "17/17 texts" in r, r)
    check("code chat: and compared with Figma's picture of the frame", "the design's picture (similarity" in r, r)
    proj = Path(cc.state["project"])
    check("code chat: a git version, VS Code files, the design's reference", (proj / ".git").exists() and (proj / ".vscode" / "tasks.json").exists()
          and (proj / "design" / "reference.png").exists() and "Version " in r)
    r = cc.say("does it still match the design?")
    check("code chat: 'does it still match the design?' measures again", r.startswith("Matches the design: 37/37"), r)
    r = cc.say("turn my canva design 'Eid sale' into a web page")
    check("code chat: a Canva design becomes a project (its two pages as sections)", "Made eid_sale (web) from the Canva design 'Eid sale' (1920 x 2160)" in r, r)
    check("code chat: measured against Canva's own pictures of the pages", "elements where the design puts them" in r and "the design's picture" in r, r)
    r = cc.say("make a web page from page 1 of my canva design 'Eid sale'")
    check("code chat: one page of a Canva design", "(1920 x 1080)" in r, r)

    hc = HubChat.start(chats_dir=OUT / "hubchats", transports={"figma": figma_fake_t, "canva": canva_fake_t},
                       creds={"figma": {"token": "figd_TEST_SECRET"}, "canva": {"access_token": "CANVA_TEST_TOKEN"}},
                       files=[str(OUT / "pics" / "face.png")])
    link = f"https://www.figma.com/design/{KEY}/Khan-Electronics"
    r = hc.say(f"what frames are in {link}?")
    check("hub: a Figma file's frames", "1 frame(s): Home (1440x1180, Page 1)" in r, r)
    r = hc.say("what colours and fonts does it use in figma?")
    check("hub: the design's colours and fonts (the link remembered)", r.startswith("Colours (most used first): #") and "Poppins 700 56px" in r, r)
    r = hc.say("export the 'Home' frame from figma as png")
    check("hub: a frame exported", r.startswith("Exported 1 of 1 frame(s) as PNG") and "Home.png" in r, r)
    r = hc.say("comment 'Hero looks great' on figma")
    check("hub: a Figma comment is shown first (others will see it)", r.startswith("Ready to comment"), r)
    r = hc.say("yes")
    check("hub: then posted and checked", "Commented on Figma file" in r and "(checked)" in r, r)
    r = hc.say("undo")
    check("hub: and taken back", r.startswith("Undone: comment"), r)
    r = hc.say("list my canva designs")
    check("hub: Canva designs", "Shop logo; Eid sale (2 pages)" in r, r)
    r = hc.say("export my canva design \"Eid sale\" as a pdf")
    check("hub: a Canva design saved as PDF", r.startswith('Saved "Eid sale" as PDF') and ".pdf" in r, r)
    r = hc.say("upload face.png to canva")
    check("hub: a picture uploaded to Canva at once (your own account)", "Uploaded face.png to your Canva uploads (checked)" in r, r)
    r = hc.say("undo")
    check("hub: and the upload taken back", r.startswith("Undone: upload"), r)
    r = hc.say("make a new canva instagram post \"Eid offer\"")
    check("hub: a new Canva design", 'Made the Canva design "Eid offer" (checked)' in r, r)


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    olds = (FG.CACHE, CV.EXPORTS, FD.WORK)
    FG.CACHE, CV.EXPORTS, FD.WORK = OUT / "figma_cache", OUT / "canva_exports", OUT / "work"
    CV.Canva.pause = staticmethod(lambda s: None)
    for p in (FG.CACHE, FD.WORK):
        shutil.rmtree(p, ignore_errors=True)
    try:
        folder, _ = converter()
        spoiled(folder)
        picture_match(folder)
        fonts()
        deck, refs = powerpoint()
        figma(folder / ".out" / "page.png")
        canva(deck, refs)
        canva_signin()
        edit_forms()
        shutil.rmtree(FG.CACHE, ignore_errors=True)
        chats(figma_fake(landing()[0], (folder / ".out" / "page.png").read_bytes(), ["3001"]), canva_fake(deck, refs))
    finally:
        FG.CACHE, CV.EXPORTS, FD.WORK = olds
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not bad else f'{len(bad)} FAILED'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)}, {time.time() - t0:.0f} s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

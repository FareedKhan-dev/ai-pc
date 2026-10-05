"""Engine tests for the design agent: every kind and style rendered by the hidden Chrome and passing every check; the
checks shown to fail on designs spoiled on purpose; certificates for many names; requests read by rules (no model).

  .venv\\Scripts\\python.exe tests\\test_design.py
About a minute. Everything is written under out\\_tests\\design\\engine.
"""
import copy
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image  # noqa: E402

from harness.design import check as CK  # noqa: E402
from harness.design import render as R  # noqa: E402
from harness.design.designchat import DesignChat  # noqa: E402
from harness.design.designparse import parse  # noqa: E402

OUT = ROOT / "out" / "_tests" / "design" / "engine"
CAR = ROOT / "media/derived/parked-red-sports-car-66_still_8.20.png"
GS = ROOT / "media/derived/mixkit_28287_still_7.50.png"
BMW = ROOT / "media/josh-berquist-_4sWbzH5fp8-unsplash.jpg"
FAILS = []
CARD = {"name": "Ahmed Khan", "title": "Sales Manager", "company": "Khan Electronics", "phone": "0300-1234567", "email": "ahmed@khanelectronics.pk",
        "web": "khanelectronics.pk", "address": "Shop 12, Hall Road, Lahore", "tagline": "Quality electronics since 1998"}
POST = {"brand": "Khan Electronics", "headline": "Mega Summer Sale", "sub": "Up to 30% off on ACs, fridges and LED TVs", "offer": "30% OFF",
        "dates": "1 - 15 June", "cta": "Shop now", "phone": "0300-1234567", "web": "khanelectronics.pk"}
SPECS = [
    ("card modern", {"kind": "card", "style": "modern", "fields": CARD, "qr": True}),
    ("card classic", {"kind": "card", "style": "classic", "palette": "cream", "fields": CARD}),
    ("card bold", {"kind": "card", "style": "bold", "palette": "charcoal", "fields": CARD, "qr": True}),
    ("post headline", {"kind": "post", "style": "headline", "fields": POST}),
    ("post photo", {"kind": "post", "style": "photo", "palette": "red", "image": str(BMW), "fields": POST}),
    ("portrait split", {"kind": "portrait", "style": "split", "palette": "navy", "image": str(CAR), "fields": POST}),
    ("story headline", {"kind": "story", "style": "headline", "palette": "purple", "fields": POST}),
    ("story photo", {"kind": "story", "style": "photo", "palette": "teal", "image": str(BMW), "fields": POST}),
    ("thumbnail face (cut-out)", {"kind": "thumbnail", "style": "face", "palette": "red", "image": str(GS), "fields": {"headline": "I tried every AI tool", "sub": "Honest review"}}),
    ("thumbnail center", {"kind": "thumbnail", "style": "center", "palette": "blue", "image": str(BMW), "fields": {"headline": "Is it worth it?", "sub": "BMW M4"}}),
    ("flyer sale A5", {"kind": "flyer", "style": "sale", "palette": "red", "qr": True, "fields": dict(POST, address="Shop 12, Hall Road, Lahore", items=[
        {"name": "Inverter AC 1.5 ton", "price": "Rs 145,000"}, {"name": "LED TV 43 inch", "price": "Rs 89,500"}, {"name": "Refrigerator 14 cft", "price": "Rs 118,000"},
        {"name": "Microwave oven", "price": "Rs 32,000"}])}),
    ("poster event A3", {"kind": "poster", "style": "event", "palette": "navy", "image": str(BMW), "qr": True, "fields": {
        "brand": "Lahore Auto Club", "headline": "Classic Car Show 2026", "sub": "Fifty restored classics, live music and food stalls", "date": "Sunday 14 June",
        "time": "4 pm to 10 pm", "address": "Expo Centre, Johar Town, Lahore", "phone": "0321-7654321", "web": "lahoreautoclub.pk",
        "body": "Entry is free for families. Bring your own classic and register at the gate before 5 pm."}}),
    ("certificate classic", {"kind": "certificate", "style": "classic", "palette": "navy", "fields": {
        "org": "Punjab Coding Academy", "title": "Certificate of Achievement", "recipient": "Ayesha Siddiqui",
        "reason": "for completing the twelve-week Full Stack Web Development course with distinction", "date": "3 October 2026",
        "signer1": "Dr. Imran Ali, Director", "signer2": "Sara Javed, Course Lead"}}),
    ("certificate modern", {"kind": "certificate", "style": "modern", "palette": "emerald", "fields": {
        "org": "Green Valley School", "title": "Certificate of Participation", "recipient": "Muhammad Hamza Qureshi", "reason": "for taking part in the Science Fair 2026",
        "date": "28 September 2026", "signer1": "Mrs. Nadia Hussain, Principal"}}),
    ("invitation elegant", {"kind": "invitation", "style": "elegant", "palette": "cream", "fields": {
        "heading": "You are invited", "host": "Mr. and Mrs. Tariq Mehmood request the pleasure of your company at", "event": "The Wedding Reception of Ali and Hira",
        "date": "Saturday, 21 November 2026", "time": "7:30 in the evening", "address": "Pearl Continental Hotel, Lahore", "note": "Dinner will be served",
        "rsvp": "0300-1112233"}}),
    ("invitation modern", {"kind": "invitation", "style": "modern", "palette": "navy", "fields": {
        "event": "Khan Electronics Grand Opening", "date": "Friday, 9 October 2026", "time": "6 pm", "address": "Shop 12, Hall Road, Lahore", "rsvp": "0300-1234567"}}),
]


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


def run(spec, stem):
    spec = copy.deepcopy(spec)
    info = R.prepare(spec, OUT)
    res = R.render(spec, OUT, stem)
    faces = {p["name"]: R.faces_on_page(spec, info, p["measure"]) for p in res["pages"]}
    return spec, res, CK.checks(spec, res, {k: v for k, v in faces.items() if v}), info


def fails(chk, words):
    return any(not c["ok"] and words.lower() in c["what"].lower() for c in chk)


def every_design():
    keep = {}
    for name, spec in SPECS:
        t = time.perf_counter()
        sp, res, chk, info = run(spec, name.replace(" ", "_").replace("(", "").replace(")", ""))
        bad = [c["what"] for c in chk if not c["ok"]]
        check(f"{name}: {len(chk)} checks pass ({time.perf_counter() - t:.1f} s)", not bad, "; ".join(bad))
        keep[name] = (sp, res, chk, info)
    sp, res, chk, info = keep["thumbnail face (cut-out)"]
    check("thumbnail: the person was cut from the green backdrop", info.get("cutout") == "green" and Path(sp["_cutout"]).exists())
    sp, res, _, _ = keep["card modern"]
    check("card: front and back, PDF of 2 pages at 94.9 x 56.8 mm", len(res["pages"]) == 2 and res["pdf"])
    return keep


def spoiled(keep):
    sp, res, _, _ = copy.deepcopy(keep["card bold"])
    long_ = dict(sp, fields=dict(sp["fields"], name="Muhammad Abdullah Rehman Siddiqui Qureshi Khan Durrani Chaudhry Sahib"))
    _, _, chk, _ = run(long_, "spoiled_long_name")
    check("spoiled: a name far too long for the card -> 'no text runs out' fails", fails(chk, "no text runs out"))
    same = dict(sp, colors={"fg": "#1E1F24"})  # words the colour of the card
    _, _, chk, _ = run(same, "spoiled_contrast")
    check("spoiled: words the colour of the background -> the contrast check fails", fails(chk, "stands out"))
    r2 = copy.deepcopy(res)
    it = next(i for i in r2["pages"][0]["measure"]["items"] if i["role"] == "name")
    it["tx"], it["x"] = -12, -12
    check("spoiled: the name pushed past the trim -> the safe-area check fails", fails(CK.checks(sp, r2), "inside the safe area"))
    r3 = copy.deepcopy(res)
    q = next(i for p in r3["pages"] for i in p["measure"]["items"] if i["role"] == "qr")
    q["qr"] = "https://example.com/wrong"
    check("spoiled: the QR code expected to read another link -> the QR check fails", fails(CK.checks(sp, r3), "qr code scans"))
    r4 = copy.deepcopy(res)
    r4["pages"][0]["measure"]["items"] = [i for i in r4["pages"][0]["measure"]["items"] if i["role"] != "phone"]
    check("spoiled: the phone number missing from the card -> 'every detail' fails", fails(CK.checks(sp, r4), "every detail"))
    check("spoiled: the card's PDF said to be A4 -> the PDF size check fails", fails(CK.checks(dict(sp, paper="a4"), res), "pdf"))
    r5 = copy.deepcopy(res)
    r5["pages"][0]["measure"]["fonts"] = {"Bahnschrift": False}
    check("spoiled: a font that is not on this PC -> the fonts check fails", fails(CK.checks(sp, r5), "fonts"))
    psp, pres, _, _ = keep["post headline"]
    check("spoiled: a square post checked as a story -> the picture size check fails", fails(CK.checks(dict(psp, kind="story"), pres), "exactly"))
    face = {"kind": "post", "style": "photo", "palette": "blue", "image": str(GS),
            "fields": {"headline": "Meet the new host of our Friday night comedy show", "sub": "Every Friday at 8 pm on our channel, live from Lahore"}}
    sp2 = copy.deepcopy(face)
    info = R.prepare(sp2, OUT)
    sp2["_text_at"] = "top" if sp2.get("_text_at") != "top" else "bottom"  # the words where the face is
    res2 = R.render(sp2, OUT, "spoiled_face")
    fp = {p["name"]: R.faces_on_page(sp2, info, p["measure"]) for p in res2["pages"]}
    check("spoiled: the words put over the presenter's face -> 'no words over a face' fails", fails(CK.checks(sp2, res2, {k: v for k, v in fp.items() if v}), "face"))
    tiny = OUT / "tiny.png"
    Image.open(CAR).convert("RGB").resize((90, 60)).save(tiny)
    _, _, chk, _ = run(dict(SPECS[11][1], image=str(tiny)), "spoiled_tiny_photo")
    check("spoiled: a 90 x 60 px photo on an A3 poster -> the print resolution check fails", fails(chk, "dpi"))


def batch():
    c = DesignChat.start(chats_dir=OUT / "chats")
    c.say("a certificate of participation from Green Valley School for Ali Raza for taking part in the Science Fair 2026")
    names = ["Ali Raza", "Sara Khan", "Muhammad Hamza Qureshi Siddiqui", "Ayesha Noor", "Zainab Fatima"]
    r = c.say("certificates for these names: " + ", ".join(names[:-1]) + " and " + names[-1])
    b = c.state["batches"][-1]
    check(f"batch: {len(names)} certificates in one PDF, every name printed once and fitting", all(x["ok"] for x in b["checks"]) and "5 certificates" in r, r[:200])
    names_file = OUT / "names.txt"
    names_file.write_text("Name\nBilal Ahmed\nHina Tariq\n" + "A" * 140 + "\n", encoding="utf-8")
    c.state["files"]["names.txt"] = str(names_file)
    r = c.say("certificates for the names in names.txt")
    check("batch from a file: a 140-letter 'name' is reported as not fitting", "not right" in r and "fits" in r, r[:200])


PHRASES = [
    ("make a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567, ahmed@khan.pk", None,
     lambda o: o[0]["kind"] == "card" and o[0]["fields"]["name"] == "Ahmed Khan" and o[0]["fields"]["title"] == "Sales Manager" and o[0]["fields"]["phone"] == "0300-1234567"
     and o[0]["fields"]["email"] == "ahmed@khan.pk"),
    ("business card, name: Sara Javed, title: Designer, phone: +92 321 5550000, website: sarajaved.com", None,
     lambda o: o[0]["fields"]["name"] == "Sara Javed" and o[0]["fields"]["web"] == "sarajaved.com"),
    ("an instagram post for Khan Electronics 'Mega Summer Sale' 30% off 1-15 June, shop now", None,
     lambda o: o[0]["kind"] == "post" and o[0]["fields"]["headline"] == "Mega Summer Sale" and o[0]["fields"]["offer"] == "30% OFF"
     and o[0]["fields"]["dates"] == "1 - 15 June" and o[0]["fields"]["cta"] == "Shop now" and o[0]["fields"]["brand"] == "Khan Electronics"),
    ("whatsapp status for our Eid offer 'Eid Mubarak Sale' 20% off", None, lambda o: o[0]["kind"] == "story" and o[0]["fields"]["offer"] == "20% OFF"),
    ("a youtube thumbnail saying I tried every AI tool", None, lambda o: o[0]["kind"] == "thumbnail" and o[0]["fields"]["headline"] == "I tried every AI tool"),
    ("a certificate of achievement from Punjab Coding Academy for Ayesha Siddiqui for completing the web course, signed by Dr. Imran Ali, Director", None,
     lambda o: o[0]["fields"]["recipient"] == "Ayesha Siddiqui" and o[0]["fields"]["title"] == "Certificate of Achievement" and o[0]["fields"]["signer1"] == "Dr. Imran Ali, Director"),
    ("certificates for these names: Ali Raza, Sara Khan and Hamza Ali", "certificate", lambda o: o[-1] == {"op": "batch", "names": ["Ali Raza", "Sara Khan", "Hamza Ali"]}),
    ("an invitation for my sister's wedding on Saturday 21 November at 7 pm at Pearl Continental Hotel, Lahore", None,
     lambda o: o[0]["kind"] == "invitation" and "wedding" in o[0]["fields"]["event"].lower() and o[0]["fields"]["time"] == "7 pm"),
    ("a flyer for our sale: AC - Rs 145,000, LED TV - Rs 89,500", None, lambda o: o[0]["kind"] == "flyer" and len(o[0]["fields"]["items"]) == 2),
    ("classic style in green", "card", lambda o: o[0] == {"op": "look", "style": "classic", "palette": "green"}),
    ("try another style", "card", lambda o: o[0]["style"] == "next"),
    ("make the name bigger", "card", lambda o: o[0] == {"op": "size", "role": "name", "by": 1.25}),
    ("make the headline a bit smaller", "post", lambda o: o[0]["role"] == "headline" and o[0]["by"] < 1),
    ("change the phone to 0333-7654321", "card", lambda o: o[0] == {"op": "set", "fields": {"phone": "0333-7654321"}}),
    ("remove the address", "card", lambda o: o[0] == {"op": "drop", "fields": ["address"]}),
    ("add a QR code for khanelectronics.pk", "card", lambda o: o[0] == {"op": "qr", "data": "khanelectronics.pk"}),
    ("make it a story", "post", lambda o: o[0] == {"op": "look", "kind": "story"}),
    ("use car.jpg", "post", lambda o: o[0] == {"op": "image", "path": "car.jpg"}),
    ("export the pdf for printing", "card", lambda o: o[0] == {"op": "export", "fmt": "pdf", "for": "print"}),
    ("save the png for whatsapp", "post", lambda o: o[0]["fmt"] == "png" and o[0]["for"] == "whatsapp"),
    ("dark background", "post", lambda o: o[0] == {"op": "look", "palette": "charcoal"}),
    ("sunset gradient", "post", lambda o: o[0] == {"op": "look", "gradient": "sunset"}),
]


def phrases():
    for text, kind, ok in PHRASES:
        r = parse(text, {"kind": kind, "files": {}})
        try:
            good = bool(r["ops"]) and ok(r["ops"])
        except (KeyError, IndexError, TypeError):
            good = False
        check(f"reads: {text[:80]}", good, str(r)[:220])


if __name__ == "__main__":
    t0 = time.perf_counter()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    keep = every_design()
    spoiled(keep)
    batch()
    phrases()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.0f} s)")
    sys.exit(1 if FAILS else 0)

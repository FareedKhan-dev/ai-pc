"""The one AI PC chat, offline (rules only, no AI model; Slack and Telegram are fakes, nothing is sent anywhere):
which program each request goes to, 'it' / 'the original' / 'the pdf', requests in several steps, the photo -> Slack
hand-off with its 'yes', voice notes heard by the local Whisper, your phone through the Telegram bot (photo with a
caption, a voice note, 'yes'; strangers ignored), finding 'my photo' on the PC, picking up a saved chat, secrets hidden.

  .venv\\Scripts\\python.exe tests\\test_aipc.py
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_hub as TH  # noqa: E402
from harness.aipc import router  # noqa: E402
from harness.aipc.artifacts import Artifacts  # noqa: E402
from harness.aipc.chat import AIPCChat  # noqa: E402
from harness.hub.http import FakeTransport  # noqa: E402
from harness.hub.services import connector  # noqa: E402

OUT = ROOT / "out" / "_tests" / "aipc"
PHOTO_SRC = ROOT / "media" / "josh-berquist-_4sWbzH5fp8-unsplash.jpg"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"\n     why: {str(detail)[:500]}"), flush=True)


def slack_with_uploads():
    tr = TH.fakes()
    got = {}
    s = tr["slack"]
    s.routes[("GET", "files.getUploadURLExternal")] = lambda r: (got.update(name=r["url"].split("filename=")[1].split("&")[0]) or 200,
                                                                 {"ok": True, "upload_url": "https://files.slack.com/upload/v1/ABC", "file_id": "F123"})
    s.routes[("POST", "files.slack.com/upload")] = lambda r: (got.update(data=r["body"]) or 200, b"OK")
    s.routes[("POST", "files.completeUploadExternal")] = (200, {"ok": True, "files": [{"id": "F123", "permalink": "https://khan.slack.com/files/F123"}]})
    return tr, got


def new_chat(name, tr=None, **opts):
    folder = OUT / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    options = {"chats_root": folder / "lanes", **opts}
    if tr is not None:
        options["hub"] = {"transports": tr, "creds": TH.CREDS}
    return AIPCChat.start(chats_dir=folder / "chats", planner=None, options=options), folder


def photo_in(folder, name="car.jpg"):
    p = folder / name
    shutil.copy(PHOTO_SRC, p)
    return p


# ---------------------------------------------------------------- which program
CASES = [
    ("hey can you create a simple glow effect on my video", ["me.mp4"], None, "video"),
    ("add a lightning effect at the start", ["me.mp4"], None, "video"),
    ("please send it to slack", [], "video", "hub"),
    ("send it to slack #team", [], "video", "hub"),
    ("make it under 10 MB for whatsapp", ["me.mp4"], None, "convert"),
    ("make it ready for whatsapp", [], "video", "convert"),
    ("send it on whatsapp to 03001234567", [], "video", "hub"),
    ("add word by word captions", ["me.mp4"], None, "sound"),
    ("clean up this recording", ["talk.wav"], None, "sound"),
    ("voice-over: Welcome to Khan Electronics", [], None, "sound"),
    ("make my photo brighter", ["car.jpg"], None, "photo"),
    ("remove the background", ["car.jpg"], None, "photo"),
    ("make it brighter", [], "photo", "photo"),
    ("undo", [], "photo", "photo"),
    ("a visiting card for Ahmed Khan, Sales Manager", [], None, "design"),
    ("make an instagram post for our Eid sale", [], None, "design"),
    ("post it on instagram with a caption", [], "design", "social"),
    ("upload it to youtube as private", [], "video", "social"),
    ("write a 3 page report on solar energy in Lahore", [], None, "office"),
    ("make a 10 slide presentation on our sales", [], None, "office"),
    ("make the title bigger", ["report.docx"], None, "office"),
    ("compress this pdf", ["scan.pdf"], None, "office"),
    ("clean up my downloads", [], None, "windows"),
    ("turn on dark mode", [], None, "windows"),
    ("a 5 marla house with 3 bedrooms", [], None, "cad"),
    ("a 3D model of a 7 marla house", [], None, "three"),
    ("put my logo on a mug", [], None, "three"),
    ("make a python script that counts words in a text file", [], None, "coding"),
    ("build a one-page website for Khan Electronics", [], None, "coding"),
    ("invoice for Ali Traders: 2 LED TV at 85,000 each, 18% tax", [], None, "accounts"),
    ("who owes me money?", [], None, "accounts"),
    ("send everything to tally", [], None, "accounts"),
    ("what's new in #general?", [], None, "hub"),
    ("brief me", [], None, "hub"),
    ("email it to ali@khan.pk", [], "office", "hub"),
    ("gimp make car.jpg black and white", ["car.jpg"], None, "apps"),
    ("7zip pack report.docx with password Lahore123", ["report.docx"], None, "apps"),
    ("flutter app called 'Shop'", [], None, "apps"),
    ("android studio app called 'Shop'", [], None, "apps"),
    ("mongodb database for a shop", [], None, "apps"),
    ("power bi report from sales.xlsx", ["sales.xlsx"], None, "apps"),
    ("print it", [], "office", "apps"),
    ("autohotkey script: brb -> be right back", [], None, "apps"),
    ("musescore it", [], None, "apps"),
    ("convert it to stl", ["chair.glb"], None, "three"),
]


def t_routing():
    c, folder = new_chat("routing")
    f = {}
    for n in ("me.mp4", "car.jpg", "talk.wav", "report.docx", "sales.xlsx", "scan.pdf", "chair.glb"):
        (folder / n).write_bytes(b"x")
        f[n] = str(folder / n)
    wrong = []
    for msg, files, active, want in CASES:
        refs = [f["report.docx"]] if active == "office" and " it" in f" {msg}" else []
        lane, why, ask = router.pick(msg, [f[n] for n in files], active, c.apps_claim, None, c.catalogue(), "", refs=refs)
        if lane != want:
            wrong.append(f"{msg!r} -> {lane} (want {want})")
    check(f"routing: {len(CASES) - len(wrong)} of {len(CASES)} requests go to the right program (all 14 programs and named apps)", not wrong, wrong)
    check("routing: a request in steps is split where a new action starts", router.split("add a glow effect to my video and then send it to slack #team")
          == ["add a glow effect to my video", "send it to slack #team"] and router.split("make it black and white and send it to slack")
          == ["make it black and white", "send it to slack"] and len(router.split("cut the first 5 seconds and make it under 10 MB")) == 1)
    help_text = c.say("what can you do?")
    check("help: lists every program with an example", all(l.label in help_text for l in c.lanes.values()) and help_text.count("\n- ") == len(c.lanes), help_text[:300])


def t_references():
    folder = OUT / "refs"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    for n in ("me.mp4", "me_glow.mp4", "plan.dxf", "plan.pdf", "notes.docx"):
        (folder / n).write_bytes(b"x")
    a = Artifacts()
    a.add(folder / "me.mp4", "you", 1)
    a.add(folder / "me_glow.mp4", "video", 2)
    a.add(folder / "plan.dxf", "cad", 3)
    a.add(folder / "plan.pdf", "cad", 3)
    a.add(folder / "notes.docx", "office", 4)
    nm = lambda hits: [h["name"] for h in hits]  # noqa: E731
    check("'it' is the newest thing made", nm(a.resolve("send it to slack")) == ["notes.docx"])
    check("'the video' is the edited one; 'the original video' is the one you sent",
          nm(a.resolve("send the video to ali")) == ["me_glow.mp4"] and nm(a.resolve("send the original video")) == ["me.mp4"])
    check("'the plan' is its PDF (made with the drawing); a file's name finds it", nm(a.resolve("email the plan")) == ["plan.pdf"]
          and nm(a.resolve("print me_glow.mp4")) == ["me_glow.mp4"])


# ---------------------------------------------------------------- the photo -> Slack hand-off
def t_photo_to_slack():
    tr, got = slack_with_uploads()
    c, folder = new_chat("photo_slack", tr)
    photo = photo_in(folder)
    r = c.say("make my photo brighter", files=[photo])
    made = r.files
    check("photo: 'make my photo brighter' with a photo goes to the photo program and a brighter version is made",
          r.startswith("[Photos]") and "Brighter" in r and len(made) == 1 and Path(made[0]).exists(), r)
    r = c.say("send it to slack #general")
    check("hand-off: 'send it to slack' names the edited photo (a clear name, not v1.png) and waits for a yes",
          "Ready to post car_edited.png to #general" in r and "data" not in got, r)
    r = c.say("yes")
    check("hand-off: 'yes' uploads it; Slack got the edited photo byte for byte, not the original",
          "Uploaded car_edited.png" in r and got.get("data") == Path(made[0]).read_bytes() and got["data"] != photo.read_bytes(), r)
    r = c.say("make it darker")
    check("after Slack, 'make it darker' goes back to the photo (the program in use is remembered)", r.startswith("[Photos]") and "Darker" in r, r)
    got.clear()
    r = c.say("send it to slack #general")
    r2 = c.say("no")
    check("'no' drops a pending send: nothing is uploaded", "Dropped" in r2 and "data" not in got, r2)
    items = c.say("what have you made?")
    check("'what have you made?' lists what was sent and made", "car.jpg (image, you sent it)" in items and "made by photo" in items, items)


def t_steps():
    tr, got = slack_with_uploads()
    c, folder = new_chat("steps", tr)
    photo = photo_in(folder)
    c.say("here is my photo", files=[photo])
    r = c.say("make it black and white and then send it to slack #general")
    check("steps: 'make it black and white and then send it to slack' runs the photo step, then asks before sending",
          "[Photos]" in r and "Ready to post" in r and "#general" in r, r)
    r = c.say("yes")
    check("steps: 'yes' sends the black and white version", "Uploaded" in r and got.get("data") is not None and got["data"] != photo.read_bytes(), r)


def t_voice():
    from harness.sound.tts import speak
    c, folder = new_chat("voice")
    photo = photo_in(folder)
    wav = folder / "note.wav"
    speak("Make my photo brighter please.", str(wav))
    r = c.say(files=[photo], voice=str(wav))
    check("voice: a voice note is heard by the local Whisper and done like a typed request",
          r.heard and "bright" in r.heard.lower() and r.startswith("[Photos]") and "Brighter" in r, f"heard={r.heard!r} reply={r[:200]}")


def t_find_on_pc():
    c, folder = new_chat("find", home=str(OUT / "find" / "home"))
    pics = OUT / "find" / "home" / "Pictures"
    pics.mkdir(parents=True)
    photo_in(pics, "car_for_sale.jpg")
    r = c.say("make my car photo brighter")
    check("no file sent: 'my car photo' is looked for in your Pictures and offered", "Which one?" in r and "car_for_sale.jpg" in r, r)
    r = c.say("1")
    check("choosing '1' does the request on that photo", r.startswith("[Photos]") and "Brighter" in r, r)


def t_resume_and_secrets():
    c, folder = new_chat("resume")
    photo = photo_in(folder)
    c.say("make my photo brighter", files=[photo])
    c.say("7zip pack car.jpg with password Lahore123")
    cid = c.state["id"]
    log = (folder / "chats" / cid / "chat.json").read_text(encoding="utf-8")
    check("secrets: a password typed in a request is hidden in the saved chat", "Lahore123" not in log and "[hidden]" in log)
    c2 = AIPCChat.load(cid, chats_dir=folder / "chats", planner=None, options=c.options)
    r = c2.say("make it darker")
    check("a saved chat picks up where it was: 'it' is still the photo, its versions carry on", r.startswith("[Photos]") and "Darker" in r
          and c2.state["active"] == "photo", r)


# ---------------------------------------------------------------- your phone through the Telegram bot
def telegram_fake(photo_bytes, voice_bytes, rounds):
    """getUpdates hands out one round of messages per call; files download from the bot file address."""
    sent = {"texts": [], "files": [], "actions": 0}
    calls = {"n": 0}

    def updates(req):
        body = req["body"] or {}
        if body.get("offset") == -1:
            return 200, {"ok": True, "result": [{"update_id": 9, "message": {"chat": {"id": 555}, "text": "an old message from before"}}]}
        i = calls["n"]
        calls["n"] += 1
        return 200, {"ok": True, "result": rounds[i] if i < len(rounds) else []}

    def get_file(req):
        fid = req["body"]["file_id"]
        return 200, {"ok": True, "result": {"file_id": fid, "file_size": 1000, "file_path": f"files/{fid}"}}

    def download(req):
        return 200, (photo_bytes if req["url"].endswith("files/PHOTO1") else voice_bytes)

    def message(req):
        sent["texts"].append(req["body"]["text"])
        return 200, {"ok": True, "result": {"message_id": 70 + len(sent["texts"]), "chat": {"id": req["body"]["chat_id"]}, "text": req["body"]["text"]}}

    def upload(req):
        sent["files"].append(req["url"].rsplit("/", 1)[-1])
        return 200, {"ok": True, "result": {"message_id": 99, "document": {"file_id": "D"}, "photo": [{"file_id": "P"}]}}
    return FakeTransport({("POST", "/getUpdates"): updates, ("POST", "/getFile"): get_file, ("GET", "/file/bot"): download,
                          ("POST", "/sendMessage"): message, ("POST", "/sendPhoto"): upload, ("POST", "/sendDocument"): upload,
                          ("POST", "/sendChatAction"): lambda r: (sent.update(actions=sent["actions"] + 1) or 200, {"ok": True, "result": True})}), sent


def t_telegram():
    from harness.aipc.telegram import Bridge
    from harness.sound.tts import speak
    tr, got = slack_with_uploads()
    c, folder = new_chat("telegram", tr)
    photo = photo_in(folder)
    wav = folder / "send_it.wav"
    speak("Send it to Slack, general channel.", str(wav))
    me, stranger = {"id": 555, "type": "private"}, {"id": 777, "type": "private"}
    rounds = [[{"update_id": 10, "message": {"message_id": 1, "chat": stranger, "text": "clean up my downloads"}},
               {"update_id": 11, "message": {"message_id": 2, "chat": me, "caption": "make it brighter",
                                             "photo": [{"file_id": "PHOTO0", "file_size": 10, "width": 90}, {"file_id": "PHOTO1", "file_size": 999, "width": 1200}]}}],
              [{"update_id": 12, "message": {"message_id": 3, "chat": me, "voice": {"file_id": "VOICE1", "duration": 2}}}],
              [{"update_id": 13, "message": {"message_id": 4, "chat": me, "text": "yes"}}]]
    ttr, sent = telegram_fake(photo.read_bytes(), wav.read_bytes(), rounds)
    tg = connector("telegram", {"bot_token": "123:SECRET-TELEGRAM", "chat_id": 555}, ttr)
    b = Bridge(c, tg=tg, log=lambda *a: None, typing=False)
    b.skip_backlog()
    check("telegram: messages sent before the bridge started are skipped", b.offset == 10)
    b.run(once=True)
    check("telegram: a stranger's message is ignored (nothing done, no reply to them)",
          not any(isinstance(x.get("body"), dict) and x["body"].get("chat_id") == 777 for x in ttr.sent) and c.state["active"] == "photo")
    check("telegram: your photo with the caption 'make it brighter' is edited, the reply and the brighter photo come back to you",
          any("Brighter" in t for t in sent["texts"]) and "sendPhoto" in sent["files"] + ["x"] and len(sent["files"]) == 1, sent)
    b.run(once=True)
    check("telegram: your voice note 'send it to Slack, general channel' is heard and asks before sending",
          any(t.startswith("Heard:") and "Ready to post" in t and "_edited.png to #general" in t for t in sent["texts"]), sent["texts"][-1:])
    b.run(once=True)
    check("telegram: your 'yes' sends the edited photo to Slack", any("Uploaded" in t and "_edited.png" in t for t in sent["texts"]) and got.get("data") is not None,
          sent["texts"][-1:])
    check("telegram: the bot token never appears in what the chat saved", "SECRET-TELEGRAM" not in json.dumps(c.state))


def t_web():
    import threading
    import urllib.error
    import urllib.request
    import uuid
    from harness.aipc.web import serve
    c, folder = new_chat("web")
    photo = photo_in(folder)
    box = {}
    th = threading.Thread(target=serve, args=(c,), kwargs={"port": 0, "ready": lambda url, token, srv: box.update(url=url, token=token, srv=srv)},
                          daemon=True)
    th.start()
    for _ in range(100):
        if box:
            break
        time.sleep(0.05)
    url, token = box["url"], box["token"]
    page = urllib.request.urlopen(url, timeout=10).read().decode()
    check("web: the page is served on 127.0.0.1 with this run's secret", url.startswith("http://127.0.0.1:") and token in page and "Hold to talk" in page)
    b = uuid.uuid4().hex
    crlf = "\r\n"
    body = (f"--{b}{crlf}Content-Disposition: form-data; name=\"message\"{crlf}{crlf}make my photo brighter{crlf}"
            f"--{b}{crlf}Content-Disposition: form-data; name=\"files\"; filename=\"car.jpg\"{crlf}Content-Type: image/jpeg{crlf}{crlf}").encode() + \
        photo.read_bytes() + f"{crlf}--{b}--{crlf}".encode()
    hdr = {"Content-Type": f"multipart/form-data; boundary={b}"}
    try:
        urllib.request.urlopen(urllib.request.Request(url + "say", data=body, headers=hdr, method="POST"), timeout=60)
        refused = False
    except urllib.error.HTTPError as e:
        refused = e.code == 403
    check("web: a request without the secret is refused (another web page cannot drive the chat)", refused)
    r = json.loads(urllib.request.urlopen(urllib.request.Request(url + "say", data=body, headers=dict(hdr, **{"X-AIPC-Token": token}), method="POST"),
                                          timeout=120).read())
    check("web: a message with a photo is done like any other ('make my photo brighter')", r["reply"].startswith("[Photos]") and "Brighter" in r["reply"]
          and len(r["files"]) == 1, r)
    import urllib.parse
    got = urllib.request.urlopen(f"{url}file?token={token}&path={urllib.parse.quote(r['files'][0])}", timeout=30).read()
    check("web: the file made can be opened from the page", got == Path(r["files"][0]).read_bytes())
    try:
        urllib.request.urlopen(f"{url}file?token={token}&path={urllib.parse.quote(str(ROOT / 'README.md'))}", timeout=10)
        other = False
    except urllib.error.HTTPError as e:
        other = e.code == 404
    check("web: a file that is not the chat's cannot be read through the page", other)
    box["srv"].shutdown()


def main():
    t0 = time.time()
    for t in (t_routing, t_references, t_photo_to_slack, t_steps, t_voice, t_find_on_pc, t_resume_and_secrets, t_telegram, t_web):
        try:
            t()
        except Exception:  # noqa: BLE001 - one part failing does not hide the others
            import traceback
            check(f"{t.__name__}: ran without an error", False, traceback.format_exc()[-1200:])
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not bad else f'{len(bad)} FAILED'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)}, {time.time() - t0:.0f} s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

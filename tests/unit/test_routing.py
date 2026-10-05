"""Which program a request goes to: the one chat's rules, offline (no model), for every program and named app."""

import pytest

from ai_pc.assistant import router
from ai_pc.assistant.chat import AIPCChat

# (message, files sent, program in use, the program it must go to)
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
NAMES = ("me.mp4", "car.jpg", "talk.wav", "report.docx", "sales.xlsx", "scan.pdf", "chair.glb")


@pytest.fixture(scope="module")
def chat(tmp_path_factory):
    folder = tmp_path_factory.mktemp("routing")
    return AIPCChat.start(chats_dir=folder / "chats", planner=None, options={"chats_root": folder / "lanes"})


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    folder = tmp_path_factory.mktemp("files")
    out = {}
    for n in NAMES:
        (folder / n).write_bytes(b"x")
        out[n] = str(folder / n)
    return out


@pytest.mark.parametrize(("message", "sent", "active", "want"), CASES, ids=[c[0][:40] for c in CASES])
def test_request_goes_to_the_right_program(chat, files, message, sent, active, want):
    refs = [files["report.docx"]] if active == "office" and " it" in f" {message}" else []
    lane, _why, _ask = router.pick(message, [files[n] for n in sent], active, chat.apps_claim, None, chat.catalogue(), "", refs=refs)
    assert lane == want


def test_a_request_in_steps_is_split_where_a_new_action_starts():
    assert router.split("add a glow effect to my video and then send it to slack #team") == [
        "add a glow effect to my video",
        "send it to slack #team",
    ]
    assert router.split("make it black and white and send it to slack") == ["make it black and white", "send it to slack"]
    assert len(router.split("cut the first 5 seconds and make it under 10 MB")) == 1


def test_help_lists_every_program(chat):
    text = chat.say("what can you do?")
    assert all(lane.label in text for lane in chat.lanes.values())
    assert text.count("\n- ") == len(chat.lanes)

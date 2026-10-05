"""'it', 'the video', 'the original', 'the plan' and file names resolve to the right file."""
import pytest

from ai_pc.assistant.artifacts import Artifacts, kind_of, kind_words


@pytest.fixture
def arts(tmp_path):
    for n in ("me.mp4", "me_glow.mp4", "plan.dxf", "plan.pdf", "notes.docx"):
        (tmp_path / n).write_bytes(b"x")
    a = Artifacts()
    a.add(tmp_path / "me.mp4", "you", 1)
    a.add(tmp_path / "me_glow.mp4", "video", 2)
    a.add(tmp_path / "plan.dxf", "cad", 3)
    a.add(tmp_path / "plan.pdf", "cad", 3)
    a.add(tmp_path / "notes.docx", "office", 4)
    return a


def names(hits):
    return [h["name"] for h in hits]


def test_it_is_the_newest_thing_made(arts):
    assert names(arts.resolve("send it to slack")) == ["notes.docx"]


def test_the_video_is_the_edited_one_and_the_original_is_yours(arts):
    assert names(arts.resolve("send the video to ali")) == ["me_glow.mp4"]
    assert names(arts.resolve("send the original video")) == ["me.mp4"]


def test_the_plan_is_its_pdf_and_a_name_finds_its_file(arts):
    assert names(arts.resolve("email the plan")) == ["plan.pdf"]
    assert names(arts.resolve("print me_glow.mp4")) == ["me_glow.mp4"]


def test_kinds_of_files_and_words(tmp_path):
    assert kind_of(tmp_path / "x.MP4") == "video"
    assert kind_of(tmp_path / "x.unknownext") == "file"
    assert kind_of(tmp_path) == "folder"
    assert kind_words("send the video and the invoice") == ["video", "pdf"]

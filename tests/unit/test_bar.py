"""The command bar's pieces that need no window: the key combo, the clipboard format, replies, colours, the microphone."""
import math
import struct
import wave

import pytest

from ai_pc.assistant import mic
from ai_pc.assistant import shell as S
from ai_pc.assistant.agent import split_reply
from ai_pc.assistant.bar import lum, palette, shown_text


def test_a_combo_is_modifiers_and_one_key():
    assert S.parse_hotkey("ctrl+alt+space") == (0x3, 0x20, "Ctrl+Alt+Space")
    assert S.parse_hotkey("Win + Shift + A")[1:] == (ord("A"), "Shift+Win+A")
    assert S.parse_hotkey("ctrl+alt+shift+f24")[1] == 0x87


@pytest.mark.parametrize("text", ["space", "ctrl+alt", "ctrl+a+b", "ctrl+banana"])
def test_a_combo_without_a_modifier_or_with_a_wrong_key_is_refused(text):
    with pytest.raises(ValueError):
        S.parse_hotkey(text)


def test_copied_files_use_windows_file_list_format():
    b = S.dropfiles([r"C:\a b\x.mp4", r"C:\y.png"])
    assert struct.unpack("<IiiII", b[:20]) == (20, 0, 0, 0, 1)
    assert b[20:].decode("utf-16-le").startswith("C:\\a b\\x.mp4\0C:\\y.png\0\0")


def test_each_programs_part_of_a_reply_keeps_its_name():
    parts = split_reply("[Photos] Brighter: v2.png\n[Slack, Teams] Ready to post v2.png to #team. Say 'yes'")
    assert [p[0] for p in parts] == ["Photos", "Slack, Teams"]
    assert parts[1][1].startswith("Ready")


def test_long_paths_are_shown_as_file_names():
    assert shown_text(r"Edited: C:\Users\me\out\video\agent_x.mp4 (6 of 9 checks)") == "Edited: agent_x.mp4 (6 of 9 checks)"


def test_the_accent_stays_readable_on_dark_and_light():
    assert lum(palette(True, "#0050a0")["accent"]) >= 0.42
    assert lum(palette(False, "#99ddff")["accent"]) <= 0.45


def test_microphone_level_and_wav(tmp_path):
    tone = struct.pack("<1600h", *[int(9000 * math.sin(i / 8)) for i in range(1600)])
    assert mic.level(b"\0" * 3200) == 0.0
    assert mic.level(tone) > 0.5
    w = mic.write_wav(tmp_path / "t.wav", [tone, tone], 16000, 1)
    with wave.open(str(w)) as f:
        assert (f.getframerate(), f.getnchannels(), f.getnframes()) == (16000, 1, 3200)


def test_the_start_command_uses_pythonw_and_the_package(tmp_path):
    cmd = S.launch_command(tmp_path, executable=str(tmp_path / "python.exe"))
    assert "pythonw.exe" in cmd and cmd.endswith("-m ai_pc bar")
    assert S.launch_command(tmp_path, startup=True).endswith("bar --startup")

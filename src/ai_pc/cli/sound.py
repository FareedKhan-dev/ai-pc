"""The sound agent, from the command line: recordings and videos' sound cleaned, levelled, cut, mixed and captioned by
code (FFmpeg; Whisper for words), every change measured. The original is never changed: versions and saved copies go
to the chat's folder.

  ai-pc sound talk voice.wav                        a conversation about one recording
  ai-pc sound talk voice.wav -m "clean it up" -m "remove the long pauses" -m "cut the ums" -m "save as mp3"
  ai-pc sound talk talk.mp4 --with music.mp3 -m "add captions word by word" -m "add music.mp3 under my voice" -m "export the video"
  ai-pc sound talk --chat sound_voice_210455        continue a saved chat
  ai-pc sound talk -m "voice-over: Welcome to our shop. We are open nine to nine."   a voice-over from text
  ai-pc sound look voice.wav                        how loud, how noisy, hum, clipping, pauses, pitch
  ai-pc sound batch "C:\\Users\\me\\Recordings" -m "clean it up" --save "mp3"

Things to say: 'clean it up', 'remove the background noise', 'remove the hum', 'cut the rumble', 'fix the harsh s sounds',
'remove clicks', 'even out the volume', 'normalize for youtube / podcast / broadcast', 'make it louder', 'cut the first
5 seconds', 'remove 1:20 to 1:45', 'keep only 0:30 to 2:00', 'fade in and out', 'remove the long pauses', 'cut the ums',
'speed it up 1.25x', 'make my voice deeper', 'add music.mp3 under my voice', 'make the music quieter', 'add intro.mp3 at
the start', 'add echo', 'telephone effect', 'add captions', 'word by word captions in yellow', 'karaoke captions',
"change 'open router' to 'OpenRouter'", 'export the video', 'save the srt',
'save the transcript as word', 'save as mp3 under 5 MB', 'for whatsapp', 'how loud is it?', 'is it noisy?',
'what does it say?', 'compare', 'normalize for podcast instead', 'undo', 'go back to v2', 'history'.
"""

import argparse
import sys
import time
from pathlib import Path

from ai_pc.core.paths import ROOT

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")
EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".mp4", ".mov", ".mkv", ".webm", ".avi"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the sound agent: recordings cleaned, cut, mixed and captioned by code, each change measured")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation about a recording or a video's sound")
    t.add_argument("file", nargs="?")
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="other files the chat may use (music, an intro)")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    lk = sub.add_parser("look", help="what a recording is like")
    lk.add_argument("file")
    b = sub.add_parser("batch", help="the same changes on many recordings")
    b.add_argument("inputs", nargs="+")
    b.add_argument("-m", "--say", action="append", default=[])
    b.add_argument("--save", default="mp3", help="mp3, wav, m4a, ogg, flac or mp4 (videos)")
    b.add_argument("--out", default=None)
    b.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)

    from ai_pc.sound.soundchat import SoundChat

    if a.cmd == "look":
        from ai_pc.sound import measure as M

        m = M.describe(a.file)
        hum = f"{m['hum']['hz']} Hz hum ({m['hum']['db']:.0f} dB)" if (m.get("hum") or {}).get("hz") else "no hum"
        print(
            f"{Path(a.file).name}: {m['duration']:.1f} s, {m['audio']['codec']} {m['audio']['sr']} Hz {m['audio']['channels']} ch"
            + (f", video {m['video']['w']}x{m['video']['h']}" if m.get("video") else "")
            + f"\n  loudness {m['lufs']:.1f} LUFS, true peak {m['true_peak']} dBTP; voice {m['speech_db']:.0f} dB, noise between words {m['noise_db']:.0f} dB "
            f"(SNR {m['snr_db']:.0f} dB); {hum}; rumble {m['rumble_db']:.0f} dB; clipped {m['clipped']:.3%}; {len(m['pauses'])} pauses "
            f"(longest {m['longest_pause']:.1f} s)" + (f"; voice pitch {m['pitch_hz']:.0f} Hz" if m.get("pitch_hz") else "")
        )
        return
    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    if a.cmd == "talk":
        if a.chat:
            c = SoundChat.load(a.chat, planner=planner)
        else:
            c = SoundChat.start(a.file, planner=planner, files=a.extra)
        print(
            f"Chat {c.state['id']}"
            + (f" about {Path(c.state['src']).name}" if c.state.get("src") else "")
            + f" (now v{c.state['cur']}). 'quit' to leave."
        )
        msgs = a.say
        if msgs:
            for msg in msgs:
                print(f"> {msg}")
                print(c.say(msg), flush=True)
        else:
            while True:
                try:
                    msg = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if msg.lower() in ("quit", "exit", "q", "bye"):
                    break
                if msg:
                    print(c.say(msg), flush=True)
        usd = planner.cost()[1] if planner is not None else 0.0
        print(f"(chat {c.state['id']}: {len(c.state['versions'])} versions, now v{c.state['cur']}; files in {c.folder}; AI ${usd:.4f})")
        return
    files = []
    for i in a.inputs:
        p = Path(i)
        files += sorted(q for q in p.iterdir() if q.suffix.lower() in EXTS) if p.is_dir() else ([p] if p.is_file() else [])
    if not files:
        sys.exit("no recordings found")
    out = Path(a.out) if a.out else ROOT / "out" / "sound" / f"batch_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    ok = 0
    t0 = time.perf_counter()
    for f in files:
        try:
            c = SoundChat.start(f, chats_dir=out / "chats", planner=planner)
        except (ValueError, FileNotFoundError) as e:
            print(f"BAD {f.name}: {e}")
            continue
        replies = [c.say(m) for m in a.say]
        r = c.say(f"save as {a.save}" if a.save != "mp4" else "export the video")
        saved = c.state["exports"][-1]["path"] if c.state["exports"] else None
        good = saved is not None and not any("not right" in x or "Couldn't" in x for x in replies + [r])
        if saved:
            dst = out / Path(saved).name
            dst.write_bytes(Path(saved).read_bytes())
        ok += good
        print(
            f"{'ok ' if good else 'BAD'} {f.name}: "
            + " | ".join(x.splitlines()[0][:100] for x in replies)
            + f" -> {Path(saved).name if saved else 'not saved'}",
            flush=True,
        )
    print(f"\n{ok}/{len(files)} done in {time.perf_counter() - t0:.0f} s; copies in {out}")


if __name__ == "__main__":
    main()

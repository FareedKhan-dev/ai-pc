"""Voice-overs from text with the voices Windows already has (System.Speech, offline): Zira (US), Hazel (UK).

voices()                         -> ["Microsoft Zira Desktop", ...]
speak("Hello", "out.wav", voice="zira", rate=0, pauses=True)   a WAV; '...' and blank lines become pauses
"""

import base64
import re
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

NO_WINDOW = 0x08000000


def _ps(script, timeout=300):
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], capture_output=True, timeout=timeout, creationflags=NO_WINDOW
    )
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[:300])
    return r.stdout.decode("utf-8", "replace")


def voices():
    out = _ps(
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture }; $s.Dispose()"
    )
    return [ln.split("|")[0].strip() for ln in out.splitlines() if "|" in ln]


def _ssml(text, lang="en-US"):
    """Plain text as SSML: '...' -> a short pause, '[pause 2s]' -> that pause, a blank line -> a long one."""
    parts = []
    for para in re.split(r"\n\s*\n", text.strip()):
        t = escape(para.strip())
        t = re.sub(r"\[pause (\d+(?:\.\d+)?)\s*s\]", lambda m: f'<break time="{int(float(m.group(1)) * 1000)}ms"/>', t)
        t = t.replace("...", '<break time="700ms"/>')
        parts.append(t)
    body = '<break time="1200ms"/>'.join(parts)
    return f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">{body}</speak>'


def speak(text, out_wav, voice=None, rate=0):
    """Text to a WAV file with a Windows voice ('zira', 'hazel' or a full name); rate -10..10."""
    names = voices()
    pick = next((n for n in names if voice and voice.lower() in n.lower()), names[0] if names else None)
    if pick is None:
        raise RuntimeError("no Windows voices are installed")
    out_wav = Path(out_wav).resolve()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    lang = "en-GB" if "hazel" in pick.lower() or "george" in pick.lower() or "susan" in pick.lower() else "en-US"
    ssml = _ssml(text, lang).replace("'", "''")
    _ps(
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('{pick}'); $s.Rate = {int(max(-10, min(10, rate)))}; $s.SetOutputToWaveFile('{out_wav}'); "
        f"$s.SpeakSsml('{ssml}'); $s.Dispose()"
    )
    if not out_wav.exists() or out_wav.stat().st_size < 2000:
        raise RuntimeError("the voice made no sound")
    return {"path": str(out_wav), "voice": pick}

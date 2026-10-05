"""Voice notes into words, on this PC (the same local Whisper the sound and video agents use: models/whisper/base,
nothing sent anywhere). A Telegram voice note (.oga), a phone recording (.m4a), a WAV or a video all work (FFmpeg
decodes them). Speech in another language comes back in English (Whisper's own translation)."""

from pathlib import Path


def transcribe(path):
    """The words said in a voice note, or '' when there are none (or the speech model is missing)."""
    from ai_pc.media import speech

    if not speech.available() or not Path(path).is_file():
        return ""
    r = speech.transcribe(str(path), log=lambda *a: None)
    if not r:
        return ""
    text = (r.get("text") or "").strip()
    if r.get("language") not in (None, "en") and text:
        try:
            from ai_pc.media.audio import load

            segs, _ = speech._load().transcribe(load(str(path), sr=16000), task="translate", vad_filter=True, beam_size=5)
            text = " ".join(s.text.strip() for s in segs).strip() or text
        except Exception:  # noqa: BLE001 - the words as heard are still better than nothing
            pass
    return text

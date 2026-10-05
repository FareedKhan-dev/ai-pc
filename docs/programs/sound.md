# Sound

## Sound: voice clean-up, cuts, music and captions (programmatic)

```
ai-pc sound talk interview.wav -m "is it noisy?" -m "clean it up" -m "remove the long pauses" -m "cut the ums and uhs"
   -m "normalize for youtube instead" -m "save as mp3 under 5 MB"
ai-pc sound talk talk.mp4 --with music.mp3 -m "add word by word captions" -m "change 'open router' to 'OpenRouter'"
   -m "add music.mp3 under my voice" -m "make the music quieter" -m "speed it up 1.25x" -m "export the video"
ai-pc sound talk -m "voice-over: Welcome to Khan Electronics. We are open nine to nine." -m "make the voice deeper" -m "save it for whatsapp"
ai-pc sound look voice.wav                      loudness, noise, hum, rumble, clipping, pauses, pitch
ai-pc sound batch "C:\Users\me\Recordings" -m "clean it up" --save mp3
```

FFmpeg 9 (already installed) does every change. faster-whisper (base model, already in `models/whisper`) hears the
words. Windows' own voices read voice-overs. Nothing new was downloaded. The original is never changed: each message
makes a version in the chat's folder.

| Area | What it does |
|---|---|
| Measuring | Loudness and true peak (EBU R128, by FFmpeg). The noise floor and the voice's level (SNR). Mains hum at 50 or 60 Hz (how far the harmonics stand out). Rumble, hiss, harsh "s" sounds, clipping, pauses, the voice's pitch, the format. |
| Clean-up | "Clean it up" picks the steps a recording needs from its measures and says why: cut rumble, notch out the hum, repair clipping, reduce noise, soften the "s" sounds, even out the level, set the loudness. Each step is checked. Noise reduction sets FFmpeg's noise floor just above the measured one. Hum and rumble are taken out first, because people call them noise too. |
| Levels | Platform loudness in two passes, ending within 1 LU of target: YouTube, Spotify, TikTok and Instagram -14; podcasts, Apple and WhatsApp -16; audiobooks -19; broadcast -23. Louder or quieter with a limiter, so nothing clips. |
| Time | Trim, cut ranges ("remove 1:20 to 1:45"), keep a range, fades. Shorten long pauses. Cut "um" and "uh": Whisper is prompted to write them down, then they are cut without touching the next word. Speed up or slow down with the pitch kept, or change the pitch with the length kept. |
| Mixing and effects | Music under the voice: set 18 dB under it, dipping while the voice talks (sidechain), looped to length, faded in and out. "Make the music quieter" redoes only that step. Intros and outros, with a crossfade if asked. Echo, reverb, telephone/radio voice, mono and stereo. |
| Video | A video's sound is edited, and the picture is cut and sped up the same way at export, so removing pauses makes jump cuts. Captions move with every cut. |
| Captions | Whisper's words grouped into readable cues: at most 42 characters a line and two lines, about 17 characters a second, a cue ending at a full stop or a pause. Styles: clean, word by word (the spoken word highlighted, popping in), karaoke and boxed. Colour, size and position can be set, and wrong words corrected ("change X to Y"). Saved as SRT, VTT or ASS, or burned into the video by libass. A transcript can be saved as TXT or a Word document. |
| Conversation | Versions with undo, redo, go back and history. "... instead" swaps the earlier change of that kind and redoes only what came after it, starting from the last version that still holds the unchanged steps. Questions: how loud, is it noisy, how long, what does it say, compare with the original. |
| Checks | Every change is measured again. Noise must drop while the voice keeps its level; hum must be gone; loudness must hit the target; a sped-up voice must keep its pitch. Pauses are measured against the same threshold before and after. Music must sit at least 10 dB under the voice and dip at least 5 dB while it talks. Burned captions must be on the frames while the words are said, absent between lines, with the rest of the picture unchanged. Saved files are read back for length and size. |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_sound.py](../../tests/integration/test_sound.py): measures on made-up recordings (a Windows voice plus hum, rumble, noise, hiss and clipping); 31 changes each passing its own check; 13 deliberately spoiled results, each tripping its check; captions in 4 styles, files, re-timing after cuts and speed, burning; the video timeline; 43 phrasings | 108/108 | 91 s | none |
| [tests/integration/sound_conversations.py](../../tests/integration/sound_conversations.py): 4 conversations, 29 turns (a spoiled voice recording, a talking video, a voice-over, requests only the model can read), each checked on what it made | 29/29 | 92 s | $0.0002 |

Building it, the checks caught real faults:
- Noise reduction with noise tracking turned on took out under 1 dB. A fixed floor just above the measured one takes out 16-26 dB.
- "Remove the noise" on a hummy recording failed until hum and rumble were taken out first.
- A music file name was read as a second recording to join.
- "Make the music quieter" also turned the voice down.
- Pause checks drifted, because levelling moves the automatic threshold.
- The burned-caption check misread a moving head as a caption after a speed change. It now compares the nearest of three frames.

# Converter

## Converter: videos and sound converted, shrunk, cut and fixed (programmatic)

```
ai-pc convert talk holiday.mov -m "will it play on whatsapp?" -m "make it ready for whatsapp" -m "save it to my desktop"
ai-pc convert talk clip.mp4 -m "cut the first 5 seconds and make it under 10 MB" -m "make a gif of 0:05 to 0:08" -m "undo"
ai-pc convert look holiday.mov        ai-pc convert batch "C:\Users\me\Videos" -m "for email"        ai-pc convert record --seconds 20 --mic
```

What Format Factory and HandBrake do, done by code: FFmpeg makes every file, on the Intel GPU when that helps. Every
result is read back and checked, and its look is measured against the original.

| Part | What it does |
|---|---|
| Reading files | Container, length, size; the picture as it is shown (phone turn flags and odd pixel shapes applied), frame rate and whether it varies, bit depth, HDR, interlacing; sound tracks; subtitles; whether an MP4 starts playing before it has downloaded. "Will it play on WhatsApp / my TV / an iPhone?" is answered from these, with the reasons. |
| Targets | WhatsApp, email, Discord, Telegram, Slack, Instagram (Reels, posts, stories), TikTok, YouTube and Shorts, Facebook, LinkedIn, X, a website, iPhone, Android, a TV or USB player, PowerPoint, editing (ProRes), keeping (AV1), every device. Limits checked on 2026-10-04: WhatsApp's FAQ says 100 MB at 720p (64 MB on slow connections), Discord's free limit is 10 MB, Telegram bots send up to 50 MB, and email is kept under 18 MB for Gmail and Outlook. |
| One encode, from the original | Every version is made from the original files, so nothing is compressed twice. The picture is copied, not re-encoded, whenever nothing about it changes: a new container, a cut on keyframes, a file that already fits, a change to the sound only. A cut between keyframes is re-encoded to the exact frame, unless "without re-encoding" is asked or re-encoding would take long. |
| Size limits | "Under 10 MB": the bitrate comes from the length, and a sample of this very video shows how many kbps it needs, so the biggest frame and frame rate that fit are chosen (a still screen recording keeps 1080p where busy footage drops to 540p). A file still over the limit is made again, smaller. An impossible limit is refused with the ways out (split into parts, cut it shorter, save the sound only). |
| Smaller at the same look | The quality setting is searched on samples (VMAF 94 or more) and the smallest that still looks the same is used. A file that is already as small as it goes at the same look is left alone, and it says so. |
| Encoders (measured here) | H.264 on the Intel GPU is the default: on this PC it was 2-3x faster than x264 and as good per byte (VMAF 93.0 at 1.54 Mbps, against 89.9 at 1.47). AV1 on the GPU for keeping. HEVC is made by x265, because the GPU's HEVC encoder fails here; VP9 by libvpx, because the GPU's ignores its quality setting. If the GPU encoder fails, the processor makes the file. |
| Changes | Format, codec, quality, size; 720p and other sizes; frame rate; 9:16, 1:1 or 4:5 with a blurred fill, black bars or a crop; turns and mirrors; black bars cut off; trims and cuts, speed (pitch kept; smooth slow motion), joins (clips of another shape fitted with blurred sides); mute, replace or add sound, volume, loudness levelled (two passes), sound moved into sync; stabilise (two passes), deinterlace, denoise, sharpen, black and white, fades, a logo, subtitles burned in or as a track (they follow cuts); a GIF or animated WebP under a size; pictures at given times, every N seconds, a thumbnail or a contact sheet; splits into N parts, every N seconds, or under a size each. |
| Checks on every version | It plays through (decoded); its length, frame size, frame rate, codecs and sound are what was asked; it fits the size limit; an MP4 starts playing before it has downloaded; and its look is measured against the original with VMAF. The output and the reference are put on one frame clock first: frames paired half a frame apart scored 58-78 instead of 96 on the same file. |
| Conversation | Versions, undo, redo, "go back to v2", history, compare, "how good is it?", "where is it?", and saving to your Desktop, Downloads, Videos or next to the original (never over a file). If a request needs something only the video has ("for TikTok", "720p") while the current version is a GIF or sound file made from it, it builds on that video. The cheap model reads only what the rules cannot. |
| Screen recording | The screen recorded in the background by FFmpeg (Windows Desktop Duplication, on the GPU's encoder), with the microphone when asked, for a set time or until "stop recording". The recording becomes the chat's file. Nothing is clicked or moved. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_convert.py](../../tests/integration/test_convert.py): clips made for the test, every change measured independently of the converter's own checks: lengths, sizes, frames, pixels (blurred fill, logo corner, burned subtitles after a cut, fades, black and white), loudness, where a beep lands after a sync fix, pitch after a speed-up. Also keyframe copies, refused limits, splits, joins, screen recording (`--record`), checks failing on spoiled files, and the rules. | 92/92 | 136 s | none |
| [tests/integration/convert_conversations.py](../../tests/integration/convert_conversations.py), GLM-5.3-Flash on real clips: a 96 MB HEVC screen recording for WhatsApp (11.8 MB, looks 96/100), under 8 MB, then under 15 instead, undo, compare. A square clip to TikTok (1080x1920, blurred fill), a cover picture, music removed, a GIF under 3 MB. A talking video's sound moved 0.2 s, the voice as MP3, then the video at 720p. Two clips joined under a narration, for YouTube. Everyday words: "my uncle's old tv won't open this, sort it". | 19/19 turns | 164 s | $0.0001 |

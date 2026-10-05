# Video

## Video agent (JianYing 5.9, code-first)

Video editing does not go through the screen. The agent writes the JianYing project as code (pyJianYingDraft), lets
JianYing render it in the background, and then checks the export **at each edit's own moment**.

```powershell
ai-pc video new "edit this for instagram: lightning on my eye, shaky boss entrance" --media media\clip1.mp4 media\clip2.mp4
ai-pc video revise <draft> "make the lightning stronger and end with a slow zoom"
ai-pc video verify <draft>
```

```
request + media ─► analyse media (faces/eyes, shots, motion, green screen, beats; 1 vision call per file; cached)
               └─► brief (fast model, in parallel): platform, length, mood, story, every idea as a "need"
               ─► knowledge-base search: free catalogue items per need (body-part targets first, proven items ranked up)
               ─► plan (video model): clips + edits, each edit with an id and an "expect"
               ─► resolve: names checked (VIP / undownloadable / login-only / never-rendering items replaced by meaning),
                  times made absolute, macros expanded (speed ramps, reverse, freeze, shake, zoom punch, beat sync,
                  music ducking), reframing from face positions, text kept in the platform's safe zone
               ─► build the draft (~0.5 s) ─► export in the background (no mouse; downloads checked first)
               ─► verify at the edit points ─► fix what failed ─► rebuild / re-export / re-check what changed
```

| Step | Measured (this PC, 15 s Instagram reel, 3 source clips) |
|---|---|
| media analysis (first time / cached) | 4–9 s / 0 s |
| brief + plan | 1.5 s + 8–15 s |
| resolve + build | 0.4–1 s |
| export (JianYing behind other windows) | 25–40 s (render ~15–25 s) |
| verification of ~25 edit points | 12–15 s |
| whole run incl. 2 fix rounds | 125–190 s |

Knowledge (`kb/jianying/`): 4,541 catalogue items with English descriptions, 40 parameters, 70 API functions, and
`availability.json`. That file is learned from real exports: proven, downloaded, missing, needs-login, or invisible.

`kb/capcut/` holds pyCapCut's 4,957 items, all described, for reference:
- 294 are the same resources as JianYing's.
- 1,500 more have a same-name JianYing equivalent.
- 3,163 are CapCut-only. JianYing cannot fetch them (0 of 19 downloaded in a probe, `src/ai_pc/video/ccbridge.py`), so they need the CapCut app.

Beyond the catalogue:
- **Sound design** (`src/ai_pc/media/sfx.py`): impact, hit, whoosh, swoosh, riser, sub-drop, thunder and glitch, synthesised into `media/derived/`. A riser ends on its moment; the others start there.
- **Template mode**: copy an existing JianYing project, replace its media by name, rewrite its texts, and add edits on top.
- **Clip and text options**: stretch (x≠y), pitch-with-speed, blur strength, vertical text, line width, and text-background size and offset.
- **Revisions** (`ai-pc video revise`): the model sees the edit as an absolute timeline, so "when his eyes light up" lands on the right second.

Measured runs:

| Run | Time | Edit points |
|---|---|---|
| Revision | 49–66 s | changed points only, all passing |
| Calm 12-s "Golden Hour" reel | 59 s | 13 of 14 passing |

### Editor's Mind: think before rendering, reflect after

1. **Awareness** (`src/ai_pc/video/awareness.py`, ~20 ms) works out what is possible for this request, right now:
   - each need is direct, approximate, built-in, or not possible (with what to do instead);
   - how reliable each catalogue item is here;
   - where the usable faces are, whether there is music or speech, and the hard limits.
2. **Treatment.** The plan opens with a `think` section: concept, hook, arc, climax, pacing, look, sound, and a requirement map (each ask → technique → edit ids → confidence → fallback).
3. **Critic** (`src/ai_pc/video/critic.py`, ~1.5–3 s) runs before any render:
   - ~15 rule checks, plus one fast model review of the absolute timeline;
   - its patch operations are applied only if the checks don't get worse;
   - a render costs ~30 s, so catching a mistake here is ~10× cheaper.
4. **Render, verify, repair**, as described above.
5. **Report** (`src/ai_pc/video/report.py` → `out/video/reports/<draft>.md`):
   - asked vs delivered, with the verifier's evidence;
   - what was substituted and why, quality, remaining flags;
   - the best next improvements.
6. **Lessons** (`src/ai_pc/video/lessons.py` → `kb/jianying/lessons.json`): repairs and the user's follow-ups become rules that the planner and critic read on the next run.

Exports run **off-screen**: JianYing's windows are parked beyond your monitors and put back afterwards, and JianYing pre-starts while the plan is written.

### Editing like a pro: design → rhythm → recipes

The planner no longer hand-writes every edit. It **designs**:
- a style: hype/velocity, cinematic, montage, talking-head, meme or product;
- music: a given file, or a generated bed (hype, phonk, epic, pop, chill or cinematic, built with intro, build, drop and outro);
- a shot list in beats (normal / slow / fast / velocity / freeze);
- recipes, plus a few hand-placed extras (e.g. the eye effect on the close-up).

Code then writes the dense, frame-accurate timeline:

| Module | Job |
|---|---|
| `music.py` | music beds in 1–1.5 s, with an exact beat grid |
| `cutting.py` | every shot a whole number of beats; best moments by highlight, face and motion; no repeats; velocity ramps (1.8×→0.35×→1.8×) on the key moment; long shots split to the style's pacing |
| `recipes.py` | zoom punches, shakes, flashes, RGB hits, transitions, Ken Burns, grade (+ grain, vignette, letterbox, light leaks), hook, kinetic titles, captions, sound design, jump-cut zooms, meme face punches |
| `styles.py` | pacing, default recipes, transitions, type, look and music per style |
| `speech.py` | local Whisper (`models/whisper/base`, ~2 s per 12 s of speech); see below |

Talking-head edits built on `speech.py`:
- jump cuts that drop pauses and filler words;
- 1–3-word captions that never cross a cut, with key-word lines in the accent colour;
- punch-ins and pops on key words;
- b-roll when a word is spoken;
- music ducked under the voice.

Measured, live:

| Request | Points checked | Pass | Time | AI cost |
|---|---|---|---|---|
| "Lightning on my eye, boss entrance" (hype) | 55 | 52 (0 fail) | — | — |
| "Phonk velocity edit, zooms on beats, flashes on the drop, NO DAYS OFF slamming, freeze ending" | 46 | 46 | 61 s | $0.009 |
| "YouTube Short: cut pauses, word captions, zoom key words, b-roll on 'evening', quiet music" | — | — | — | — |

The YouTube Short request went through: 28 words, 1.8 s of pauses removed, b-roll and captions verified.

Measured on the lightning/boss request: 24 of 24 edit points pass after one critic patch. All 6 asks are reported "met", with evidence. One plan + critic + export + verify pass is ~100 s and $0.008; a re-render pass is ~45 s and $0.0007.

Facts found by checking exports (all handled in code):
- JianYing places keyframes at **file time**: source start + seconds × speed.
- Scale is capped at **500%**.
- Some free catalogue items never download, need an account, or never render here.
- The export dialog's drop-downs need the real mouse, so the remembered settings are used.
- UI Automation calls from two threads of one process deadlock.

Offline check: `python tests\integration\test_video_offline.py` (46 checks).

### Understanding the request: edit types, sample styles, questions

```
ai-pc video ask "what eye filters are available?"            # catalogue questions, answered in ~1 ms
ai-pc video ask "can you add lightning to my eyes?"           # what is possible, and the closest working stand-in
ai-pc video chat "what kind of video should these become?" --media media\clips\*.mp4
ai-pc video new "a 30 s travel reel like this one" --media media\trip\*.mp4 --like media\sample.mp4
```

| Module | Job |
|---|---|
| `router.py` | the front door: catalogue question, capability, "what kind of video", sample style, new edit, revision, help; rules first, the model only when unclear |
| `catalog_qa.py` | catalogue answers grouped by ready here / free but untried / VIP (free in CapCut?) / not working here. It maps loose words to the right kind: eye "filters" are face effects; "calm wedding" means dissolves and soft fades. Recommendations come only from items that work here. |
| `taxonomy.py` | 27 edit types (travel reel, gym motivation, wedding film, recipe, podcast clip, product ad, documentary…), each with its grammar: structure, pacing, look, type, sound, what to avoid. Classified from the request, the footage, speech or narration, the brief's own vote and a sample's rhythm. |
| `reference.py` | measures a sample edit and makes the new edit match it. It reads shot changes (including ones hidden under flashes, glitches or dissolves), shot lengths, cuts on the beat, tempo, zoom punches, shakes, flashes, dissolves, brightness, contrast, saturation, warmth, letterbox and grain; one vision call reads the typography. |

When a sample is given:
- It decides the style: rhythm, grade, music tempo and effects.
- The edit type decides the structure and content (labels, story).
- Exposure is matched shot by shot with a dimming layer. JianYing ignores brightness keyframes written without its adjust material.

Measured on the travel footage cut "like" the gym video:

| | Cuts/min | Brightness | Tempo |
|---|---|---|---|
| Gym sample | 48 | 0.279 | 140 BPM |
| Travel matched to the sample | 55 | 0.278 | 140 BPM |
| Travel in its own style | 35 | 0.496 | 118 BPM |

Edit-type accuracy:
- 10 of 10 genre requests;
- 8 of 10 from footage alone, and the 2 others are fair readings (landscape stock read as nature; a narration track read as documentary).

### Conversations: editing over many turns

```
ai-pc video talk agent_road_195510           # an interactive chat about an edit; "export" renders the version you are on
ai-pc video chat "make the title red and the music a bit quieter"   # one message to the chat about the last edit
```

A message is split into its asks; each one is a question about the edit, a question about what is possible, a change,
a version command, or an answer to an option the editor offered. All changes in one message become one new version.
Every version is also a JianYing draft (`agent_<word><time>_v<n>`).

| Module | Job |
|---|---|
| `conversation.py` | versions and undo/redo/"go back to v2"/"start over"; one element back from an earlier version ("the old music was better", "the previous title FONT was nicer" keeps the new words); options to pick from ("try the second one", "1 and 3"); half-answered asks ("slow motion please" → "which moment?" → "the wheel"); vague asks get concrete directions; impossible asks get the closest alternative; the cheap model handles what the rules do not, answering in the same operations, which are then checked like any other |
| `quick_edits.py` | plain words to operations, with no model call. It handles typos, chat shorthand and Roman Urdu ("title ko bara karo aur laal"); several asks in one sentence; "it", "them" and "those" referring to the last thing discussed; texts named by their words ("the price text", "SATURDAY NIGHT"); shots by what they show ("the sunset shot", "when it accelerates"); and, after a re-cut, earlier changes applied again |
| `explain.py` | answers about the current edit from its own record: fonts, music and BPM, transitions, effects, the look, "what's at 0:12?", "why the shake?", how long, how many shots or flashes, the narration |

How changes are made:
- Structural changes go into the design, and the cut engine re-cuts on the beat. Structural means length, pacing, shot order, music, format, slow motion and footage choices.
- A re-cut keeps the effects, filters, transitions and fonts the edit already uses.
- Text, colour and effect changes go into the plan as a list of overrides. The list is applied again after any re-cut, so "title red" survives a later "make it 30 s".
- Each change is checked on the new timeline before the reply. The reply says what was done, what wasn't, and why.

Measured (2026-10-03): 287 conversation turns over the 10 batch edits, about 0.5–1.2 s per turn, $0.0016 per 50 turns.
- `tests/integration/conversations.py`: 117 turns, the set the rules were tuned on.
- `tests/conversations_holdout*.py`: 4 further sets, each written after a round of fixes and first run untouched:

| Set | First run, unseen | After fixes |
|---|---|---|
| holdout (50 turns) | 66% | 100% |
| holdout2 (50 turns) | 84% | 100% |
| holdout3 (40 turns) | 75% | 100% |
| holdout4 (30 turns) | 83% | 100% |

The first-run column is the honest estimate for new phrasing: about 75–85% of turns fully right. Each turn checks:
- the kind of turn taken;
- the change on the new timeline, or the answer;
- invariants: the music never disappears unless asked, no missing items or broken shot references appear, and a question never changes the edit.

### Templates: a finished edit's exact timing on new footage

```
ai-pc video template learn media/glowup.mp4 --name glowup     # learn once: a CapCut template preview, a trending edit, one of ours
ai-pc video template list | show glowup
ai-pc video new "my trip in this template, title 'BALI 2026'" --media media\trip\*.mp4 --template glowup
ai-pc video talk <the new draft>                               # follow-ups: footage, music, texts, format (the timing stays the template's)
```

[template.py](../../src/ai_pc/video/template.py) has three steps.

**Learn.** It reads the video frame by frame:
- cuts, typed as hard cut, cut under a flash, dissolve, or motion transition;
- flashes, zoom punches and shakes;
- each slot's shot size (faces), motion, colour, and whether it is black and white;
- the tempo and the drop;
- with the model, one look per 20 slots for each slot's on-screen text and what it shows.

How cuts are found:
- Candidates come from colour, structure and pixel change, plus a 0.4 s and a 1 s comparison for transitions.
- Each candidate is verified with ORB feature matching on frames just outside the change. A zoom, shake, glitch, light leak or strobe leaves the same scene on both sides, so it is not a cut.
- Two "cuts" with no steady picture between them are the two ends of one transition.

Templates are saved in `state/templates/`.

**Fill.** Each slot gets the best unused moment of your footage:
- matched on shot size, motion, highlight and what it shows;
- hero slots (the drop, the longest late slot, the opening) are filled first;
- no moment is used twice, and the same file rarely appears twice in a row.

On top of that, the template is rebuilt from items that work here: its transitions, flashes, zooms, shakes, black-and-white slots, grade, grain or letterbox, and texts. Your words in quotes replace the template's. The music is generated at the template's tempo, its drop is placed where the template's is, and its beats are shifted onto the template's cuts. The template's own song is licensed inside CapCut, so it is never reused.

**Check.** The usual edit-point checks and fix rounds run. In a template edit the fixer never changes the template's transition lengths. Then the exported video's cuts are detected again and compared with the plan's.

Measured (2026-10-03):

| Test | Result |
|---|---|
| Cut detection on 10 edits with known timelines (`tests/integration/template_cuts_eval.py`) | 87% of cuts found, 75% precision, F1 80%. Without the strobe-lit party edit: 92% found, 82% precision |
| Fill (`tests/integration/test_templates.py`, offline) | every cut on the template's frame (0 ms drift); same length; no moment reused; follow-ups pin or avoid footage and refuse timing changes |
| Live run: gym edit as template, travel footage | 53 slots, exported in 177 s with 2 fix rounds. Checks: 29 pass, 6 warn, 1 fail. Re-detected cuts: 45 of 52 on the template's frames (86%; all 52 are exact in the project, the scan misses look-alike shots). AI: $0.0002, plus $0.004 to learn the template once |
| Chat about a template edit (`tests/integration/conversations_template.py`) | 9/9 |

### Template explorer: a CapCut link, a screenshot or words

```
ai-pc video template add "https://www.capcut.com/template-detail/7644532345902533908"   # a link you paste (tracking parameters are dropped)
ai-pc video template add media/page.png                                                # a screenshot of a template's page
ai-pc video template add "SLOWMO HDR, 4 clips, 15s, #slowmo #eid"                      # or the words
ai-pc video template add <link> --video media/preview.mp4                              # plus a video of it: its exact cut frames
ai-pc video template suggest "slow motion eid video, 4 clips" --media media\eid\*.mp4  # the library, best fit first
ai-pc video new "my eid video, add the greeting" --media media\eid\*.mp4 --template <link | name | screenshot | words>
```

What a template's page gives ([template_meta.py](../../src/ai_pc/video/template_meta.py)): the title, author, number of clips, length, format, uses, likes and hashtags. What the title and hashtags ask for ([trends.py](../../src/ai_pc/video/trends.py)) becomes settings the filler applies:
- `#slowmo` gives every slot slow motion (0.45x), with moments full of movement picked for it;
- `velocity` gives fast-slow-fast speed ramps, and `3D zoom` slow push-ins;
- `HDR` gives a high-clarity look (the title's look leads; a hashtag's look is used only when the title has none);
- `glowup` gives black and white until the drop, and `#eid` the greeting "Eid Mubarak", offered and added only when asked;
- about 30 such trends in all. Tags like `#fyp` and `#foryou` are ignored.

A tag the dictionary does not know is mapped once by the cheap model. Only known settings, in range, are kept, and the result is remembered in `state/trends.json`. For example, `#bxl` is the creator's handle, so it maps to nothing.

Without a video of the template, the slots are even and on the beat, so the result is not exact (marked "from its page"). With a video, the page's clip count makes the learned slots exactly that many: the least sure extra cuts are left out, missed cuts between look-alike shots are taken back, and a cut the preview does not show is put on a beat and marked "guessed".

**Staying within CapCut's rules** (robots.txt and llms.txt, checked 2026-10-03):
- only a page you point at is read, never listings like /templates/ or /explore/;
- the link is cleaned to `/template-detail/<id>` (CapCut asks agents not to fetch links with tracking parameters) and checked against robots.txt;
- the page is fetched once and cached for a day;
- there is no login, and no template media or song is downloaded.

In a chat:
- "any template for eid with 4 clips?" lists the library's best fits as options;
- "use the 1st", "use the slowmo hdr template" or a pasted link recuts the edit on that template. The footage, avoided files and main title stay; "... and make the title gold" is applied in the same version;
- "no slow motion", "more slow motion" and "speed ramps" change every slot's speed and keep the timing;
- "add the greeting" adds the occasion's greeting;
- "is this good for my clips? <link>" describes the template and offers the recut.

Measured (2026-10-03):

| Test | Result |
|---|---|
| Explorer (`tests/integration/test_template_explorer.py`) | all pass: link cleaning and refusals, robots.txt, the page's own record (not a related template's), techniques, a 4-slot slow-motion template from the page (no moment reused at 0.45x), greeting only when asked, normal speed and ramps on request, the clip-count constraint, suggestions, and a screenshot read by the vision model ($0.0003) |
| Clip count known (`tests/integration/template_cuts_eval.py --count`) | cut detection precision 74.5% → 83.0%, F1 80.1% → 83.0% |
| Chat (`tests/integration/conversations_explorer.py`) | 15/15; all 296 earlier chat turns still pass |
| Live: `new --template <SLOWMO HDR link>` with 7 wedding clips | 4 slots at 0.45x, HDR filter, Eid Mubarak, 100 BPM bed; 14.61 s for 14.58 s; 3/3 cuts on the planned frames; checks 12 pass, 1 warn (a face near the edge), 0 fail; all 5 asks met; 31 s with JianYing warm (72 s cold); AI $0.0002 |

The verifier now checks speed too. Inside a slowed slot, the render must show the take's moment at the planned speed (2 s into a 0.45x slot is 0.9 s into the take), not the 1x moment. On the live export the render matched the 0.45x moment at a correlation of about 0.98, against 0.0–0.74 for the 1x moment. A 1x export whose map claims 0.45x fails this check.

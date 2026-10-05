# The desktop agent

An agent that operates Windows apps it has never seen, and gets **faster every time it repeats a task**.
It does not try to make "thinking" fast. It makes thinking **rare**: once a task succeeds, the agent turns it
into a skill and replays it in milliseconds, with no model call at all.

## How it works

```
goal ─► skill for this goal and this starting screen?
          │ yes ─► REFLEX: replay saved steps through UI Automation          ~60 ms – 1 s, 0 model calls
          │ no
          ▼
        QUICK PLANNER loop (Qwen3.8-27B, ~1 s per call)
          observe (UI tree, ~50–100 ms) → plan a batch → safety check → act (~5–10 ms per action)
          → verify (wait only until the UI reacts) → observe again ...
          • UI tree too thin (custom-drawn app)? → screenshot to a VISION planner (DeepSeek-V4.1-Flash)
            + TinyClick click-grounding on the Intel Arc GPU
          • stuck or unsure? → DEEP THINKER (Kimi-K3) writes a plan once, the quick planner follows it
          ▼
        success and a clean run → compiled into a skill (semantic steps, start-state precondition,
                                  typed parameters) → next time it takes the reflex path
```

| Lane | What it uses | Speed measured on this PC |
|---|---|---|
| Reflex (skill replay) | UI Automation patterns, keyboard | **56–64 ms** for 6 steps + reading the result (Calculator); 0.3 s from the command line; ~1 s when the app's own animations must play |
| Quick planner | Nebius `Qwen/Qwen3.8-27B` (thinking off) | ~0.9–1.1 s per model call; a new 4-step task takes ~5.5–6.6 s |
| Vision | `deepseek-ai/DeepSeek-V4.1-Flash` + TinyClick (0.23B) on the Arc 140T GPU | planner ~2–4 s; each vision click ~0.5–0.8 s |
| Deep thinker | `moonshotai/Kimi-K3` | ~10–26 s, used only when the quick planner is stuck or unsure |

The model choices come from `scripts/bench_models.py`, which benchmarks the planner prompt on your Nebius account. On 6
realistic cases × 3 runs, Qwen3.8-27B scored 18/18 correct with a ~1 s median. The other candidates scored 10–16/18 and were 1.5–3 s.

## Run it

```powershell
# dry run (default): plans and prints, touches nothing
ai-pc agent run "calculate 25 * 4 and tell me the result" --app Calculator

# act for real; risky steps are refused unless you approve them (--confirm ask prompts you)
ai-pc agent run "calculate 25 * 4 and tell me the result" --app Calculator --live

ai-pc agent skills            # learned skills (list | show NAME | delete NAME)
ai-pc agent apps calc         # installed apps, discovered at runtime
ai-pc agent probe --app Calc  # what the planner would see for a window (read-only)
ai-pc agent grounder start    # start the TinyClick vision server (auto-started when needed)
```

Options: `--planner file` routes planning through `runs/planner/req_N.json` files that a person or an assistant
answers. `--deep` makes it think first. `--param k=v` fills skill parameters. `--allow-app proc.exe` permits an
app on the blocked list.

The Nebius key comes from the environment, a `.env` file or the encrypted vault (`ai-pc keys set NEBIUS_API_KEY`); see [configuration](configuration.md). It is never printed or logged.

## Unknown software

- **Finding apps:** installed apps are found at runtime (`Get-StartApps`), so something installed a minute ago can be opened by name.
- **Seeing the window:** every window is read through Windows UI Automation in one cached cross-process call. The planner
  sees each control's role, name, automation id, current value, on/off state and what it can do. It does not need to know the app.
- **Custom-drawn apps** (like CapCut) have no UI tree. For those the planner gets a screenshot, and TinyClick finds the
  click point. When a vision click lands on something UI Automation *can* name, the skill records that, and later
  replays use the fast lane instead of vision.
- **Tested on apps it had never seen:**
  - **Calculator:** switch to Scientific mode and take √144. Learned 3/3 times in 5.5–6.6 s; replays correct 3/3.
  - **Character Map** (classic Win32): find the copyright symbol's code. Learned in 5.4 s; replay 1.0 s including app start.

## Limits

- **First-time tasks take seconds, not milliseconds.** Each model call costs ~1 s, mostly network distance to Nebius in
  the EU. The speed comes from not calling the model on repeats.
- **Skills are learned only from clean runs:** no failed actions, no stuck periods, no corrections. A messy success is
  re-planned the next time, and the cleaner run is learned then.
- **Skills replay only from a similar starting screen**, compared by the set of controls (Jaccard similarity ≥ 0.8). A different starting state means planning again, which learns a second variant.
- **Vision is the slow and weaker lane.** About 0.5–0.8 s per click, and weak on icon-only buttons (TinyClick scored 9/12 on CapCut's home screen).
- **Budgets:** 30 steps, 14 model calls and 180 s per run (`src/ai_pc/core/config.py`).
- **Not yet built:**
  - a browser lane (DOM via Playwright or CDP);
  - consolidating messy runs into clean skills (a deep model rewriting the trace, then verifying it);
  - a local small planner to remove network latency.
- **Not yet tested:** Office apps, Electron apps with very large trees, and live CapCut.

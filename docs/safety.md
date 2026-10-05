# Safety

## Safety

- Dry run by default: Use `--live` to act.
- Independent action check: Every action is classified by the agent's own code, not by the model. Delete, empty, send, buy,
  install, reset and similar actions are high risk and need confirmation. Close, cancel, sign in and similar are medium risk and are
  allowed only if your goal asked for it. In unattended mode, anything that needs confirmation is refused.
- Pointer check on vision clicks: The element actually under the predicted point is checked. Is it risky ("Close")?
  Is it plausibly the thing that was asked for ("Maximise Calculator" is not "the 7 button")? If not, the agent re-aims
  once on a settled screenshot, then refuses and tells the planner. If several batched targets collapse onto one spot,
  that grounding is discarded.
- Blocked apps: Terminals, VS Code, password managers, regedit and mmc are never controlled. Text is
  never typed into password fields.
- Keystrokes only reach the target window: If focus moves elsewhere, the agent refuses instead of typing into another app.
- Screen text is data: On-screen text that tries to give orders is ignored, and that is tested with a prompt-injection case.
- Answers must be grounded: If an answer is not visible on screen, the planner is asked to point at it.
- Kill switch: Ctrl+Alt+Q aborts a live run. Every step is logged with timings in `runs/<time>_<goal>/trace.jsonl`.

# Coding

## Coding: projects written, run and checked by code (VS Code shows them)

```
ai-pc code talk -m "make a python script that counts words, lines and characters in a text file" -m "run it"
   -m "add an option to list the 5 most common words" -m "undo"
ai-pc code talk -m "build a one-page website for Khan Electronics with our products and a contact form" -m "make the header dark blue" -m "open it in VS Code"
ai-pc code talk -m "open project word_counter" -m "fix this error: <paste the traceback>" -m "what changed?"
```

This lane works on code the way the video lane works on CapCut: code writes the project's files, and VS Code only
shows them. VS Code is set up by writing its workspace files (the project's interpreter, Run and Test tasks, debug
configurations, recommended extensions), the way a CapCut draft is written. The window opens only when you ask.

| Part | What it does |
|---|---|
| Projects | Each project gets a folder in `out/code/projects`, its own `.venv` made by uv (no download), a git history, and a `.vscode` setup. Python, web (HTML/CSS/JS) and Node projects. Standard library only unless you ask, so nothing is downloaded. |
| Writing | The cheap model writes a new project as whole files, and changes an existing one with exact search/replace blocks, never blind rewrites. It sees a map of every file's functions and the files the request is about. It is told to use your real details, or obvious placeholders ("Rs 00,000", "0300-0000000"), and never invent prices, numbers or names. |
| Checks on every version | Every file compiles (Python) or parses (JavaScript). The project's own unittest or `node --test` tests pass. The program runs and exits cleanly. A web page loads in headless Chrome, with a profile of its own, with content, no console errors, and every linked file present; a screenshot is saved. |
| Repair | A failed check's exact output goes back to the model, which fixes its own work, for up to three rounds. The reply says how many rounds it took. |
| Safety | Before anything runs, the code is scanned for things that could change your PC: deleting files, starting other programs, the network, the registry, running strings as code, paths outside the folder. Such code is saved but runs only after your yes. Paths outside the project are refused. |
| Conversation | New projects, changes, "fix this error: ...", run (with other arguments), run the tests, show or explain the code, what changed, undo and redo (git), history, list and open projects (also your own folders, whose current state is kept as the first version). |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_coding.py](../../tests/integration/test_coding.py): a scripted model; a first version with a bug repaired from its own failing test; edits by search/replace; an edit that does not fit reported; risky code held back; undo and redo; paths outside refused; VS Code tasks; web pages (clean, script error, missing file) in headless Chrome | 22/22 | 13 s | none |
| Live, GLM-5.3-Flash. A word counter: repaired in 1 round, tests 3/3, right output. Then "top 5 words": tests 5/5. A shop website: no console errors, then restyled. A temp-file deleter: held back at `f.unlink()`. | all as intended | 6-14 s a step | $0.0008 for the counter session |

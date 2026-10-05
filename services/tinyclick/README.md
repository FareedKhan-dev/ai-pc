# TinyClick grounding server

A small local HTTP server (127.0.0.1:8765) that turns "click the Export button" plus a screenshot into a point on the
screen, using TinyClick (Florence-2-base fine-tuned for clicks, MIT licence) on the Intel Arc GPU. The desktop agent's
vision lane calls it through `src/ai_pc/desktop/grounder.py` when a program draws its own controls and UI Automation
cannot see them. The default click model is Vocaela (served by llama.cpp, see `src/ai_pc/core/config.py`); TinyClick
is the alternative (`CUA_GROUNDER=tinyclick`).

It runs in its own environment because it needs PyTorch built for Intel GPUs:

```powershell
uv venv .venv-xpu --python 3.12
uv pip install --python .venv-xpu\Scripts\python.exe -r services\tinyclick\requirements.txt --index-strategy unsafe-best-match
.venv-xpu\Scripts\python.exe services\tinyclick\model.py --download-only   # the original weights, into models\hf
.venv-xpu\Scripts\python.exe services\tinyclick\convert.py                 # into models\tinyclick
services\tinyclick\run.bat        # or: ai-pc agent grounder start (starts it when needed)
```

The model runs on the Florence-2 code that ships with transformers. `convert.py` renames the downloaded weights into
that layout once, so no code from the model's repository is ever run (no `trust_remote_code`). The converted model
gives the same click points as the original code: 9 of the 12 test clicks on CapCut's home screen, point for point.

| File | What it is |
|---|---|
| `server.py` | the HTTP server and its test page (`ui.html`) |
| `model.py` | loading TinyClick (from `models/tinyclick`) and the 12-query accuracy and timing test |
| `convert.py` | turns the downloaded weights into transformers' built-in Florence-2 layout |
| `run.bat` | starts the server from the project folder |

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
services\tinyclick\run.bat        # or: ai-pc agent grounder start (starts it when needed)
```

| File | What it is |
|---|---|
| `server.py` | the HTTP server and its test page (`ui.html`) |
| `model.py` | loading TinyClick (weights cached in `models/hf`) and the 12-query accuracy and timing test |
| `run.bat` | starts the server from the project folder |

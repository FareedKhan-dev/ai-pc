"""The drafting agent, from the command line: house plans for Pakistani plots and engineering parts, drawn by code as
AutoCAD DXF files (ezdxf), printed to PDF at true scale and to PNG (headless Chrome), and checked after every change
(the plan's rules, the DXF read back, the printed sheet). AutoCAD is not needed; the DXF opens in AutoCAD, BricsCAD,
DraftSight or LibreCAD.

  .venv\\Scripts\\python.exe cad.py talk                                     a conversation (type 'quit' to leave)
  .venv\\Scripts\\python.exe cad.py talk -m "a 5 marla house with 3 bedrooms" -m "make it double story" -m "export the pdf"
  .venv\\Scripts\\python.exe cad.py talk --chat cad_20261003_211654          continue a saved chat
  .venv\\Scripts\\python.exe cad.py draw "a 10 marla house with 4 bedrooms, dining and a store"     one drawing, its files and checks
  .venv\\Scripts\\python.exe cad.py draw "a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners"

Things to say: 'a 5 marla house with 2 bedrooms' (also 10 marla, 1 kanal, 30x60, corner plot, facing north),
'make it double story', 'add a dining room / store / powder room / servant room', 'no drawing room', '3 bedrooms',
'make the kitchen bigger', 'make the drawing room smaller', 'make bedroom 2 12 x 14', 'straight stairs',
'can I fit 4 bedrooms?', 'what's the covered area?', 'how big is the lounge?', 'any problems?',
'on A2', 'scale 1:100', 'call it Khan Residence', 'export the pdf / dxf / png', 'give me the dwg',
'a flange OD 150 ID 60, 4 holes of 14 on a 110 PCD, 12 thick', 'make the holes 16', 'round the corners 10',
'give me the laser cut file', 'undo', 'redo', 'go back to v1', 'history'.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="the drafting agent: house plans and parts drawn by code, each change checked")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation about a drawing")
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    d = sub.add_parser("draw", help="one drawing from one request")
    d.add_argument("request")
    d.add_argument("--offline", action="store_true")
    a = ap.parse_args()

    from harness.cad.cadchat import CadChat
    planner = None
    if not a.offline:
        from harness.planner import ChatPlanner
        planner = ChatPlanner()
    if a.cmd == "draw":
        c = CadChat.start(planner=planner)
        print(c.say(a.request))
        v = c.cur()
        if v:
            print("\n".join(f"  {k}: {p}" for k, p in v["files"].items() if k in ("dxf", "pdf", "png", "cut")))
        return
    c = CadChat.load(a.chat, planner=planner) if a.chat else CadChat.start(planner=planner)
    print(f"Chat {c.state['id']} (now v{c.state['cur']}). Files go to {c.folder}. 'quit' to leave.")
    if a.say:
        for msg in a.say:
            print(f"> {msg}")
            print(c.say(msg), flush=True)
    else:
        while True:
            try:
                msg = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg.lower() in ("quit", "exit", "q", "bye"):
                break
            if msg:
                print(c.say(msg), flush=True)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"(chat {c.state['id']}: {len(c.state['versions'])} versions, now v{c.state['cur']}; files in {c.folder}; AI ${usd:.4f})")


if __name__ == "__main__":
    main()

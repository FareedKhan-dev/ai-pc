"""The 3D lane, from the command line: houses from plans (3D floor plans, front views, turn-around videos), 3D titles,
product mockups and someone's 3D files, made by code in Blender (portable, in tools/blender, run in the background).
Every version is rendered and checked; files go to the chat's folder.

  ai-pc 3d talk -m "a 3D model of a 5 marla house with 3 bedrooms" -m "show it from above" -m "make a video going round it"
  ai-pc 3d talk -m "make my house plan 3D"          the plan last drawn in ai-pc cad
  ai-pc 3d talk -m "a 3D intro for Khan Electronics in gold" -m "add the tagline Best prices in town"
  ai-pc 3d talk --with card.png -m "put card.png on a box" -m "now a mug"
  ai-pc 3d talk -m "show me C:\\models\\chair.glb" -m "is it ready for 3D printing?" -m "convert it to stl"
  ai-pc 3d talk --chat three_101500                continue a saved chat

Things to say: 'a 3D model of a 10 marla double story house', 'show the front', 'the 3D floor plan', 'top view', 'from
above', 'make a video going round it', 'the first floor', 'grey walls', 'cream walls with brick cladding', 'wood panels',
'black window frames', 'no furniture', 'without names', 'high quality', 'bigger image', 'make the kitchen bigger',
'a 3D intro for <name> in gold / silver / chrome / glass / neon', 'make it spin in', 'on a white background', 'put
<picture> on a box / business card / laptop / phone / mug / poster', 'make it 20 x 30 x 8 cm', 'from the side', 'show me
<file>.glb', 'how big is it?', 'convert it to glb / obj / fbx / stl', 'undo', 'go back to v1', 'history', 'save it to my desktop'.
"""

import argparse
import sys

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the 3D lane: houses, titles, mockups and 3D files made by code in Blender, each result checked")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation in 3D")
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="pictures or 3D files the chat may use")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    a = ap.parse_args(argv)
    from ai_pc.three.threechat import ThreeChat

    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    c = ThreeChat.load(a.chat, planner=planner) if a.chat else ThreeChat.start(planner=planner, files=a.extra)
    print(f"Chat {c.state['id']} (now v{c.state['cur']}). 'quit' to leave.")
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

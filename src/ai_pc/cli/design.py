"""The design agent, from the command line: visiting cards, social posts, stories, YouTube thumbnails, flyers,
posters, certificates and invitations, made by code (HTML and CSS) and rendered by a hidden Chrome to PNG and a print
PDF with bleed; each version checked (every detail on it, nothing overflowing, inside the safe area, readable
contrast, QR codes that scan, sharp photos, no words over faces).

  ai-pc design talk                                       a conversation ('quit' to leave)
  ai-pc design talk -m "a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567, khanelectronics.pk"
        -m "classic style in green" -m "add a QR code" -m "export the pdf for printing"
  ai-pc design talk --with car.jpg -m "an instagram post for Khan Motors 'Eid Sale' 20% off, use car.jpg" -m "make it a story"
  ai-pc design talk --with names.xlsx -m "a certificate of participation from Green Valley School for taking part in the Science Fair"
        -m "certificates for the names in names.xlsx" -m "export the pdf"
  ai-pc design make "a youtube thumbnail saying I tried every AI tool, with me.png"      one design, its files and checks

Things to say: 'modern / classic / bold style', 'in navy / green / maroon / black and gold', 'sunset gradient', 'try another style',
'make the name bigger', 'make the headline smaller', 'change the phone to ...', 'remove the address', 'add a QR code for ...',
'use photo.jpg', 'add my logo logo.png', 'make it a story / a square post / a thumbnail / A4', 'export the pdf for printing',
'save the png for whatsapp', 'undo', 'go back to v2', 'history'.
"""

import argparse
import sys

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the design agent: print and social designs made by code, each version checked")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation about a design")
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="photos, logos or name lists the chat may use")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    m = sub.add_parser("make", help="one design from one request")
    m.add_argument("request")
    m.add_argument("--with", dest="extra", nargs="*", default=[])
    m.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)

    from ai_pc.design.designchat import DesignChat

    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    if a.cmd == "make":
        c = DesignChat.start(planner=planner, files=a.extra)
        print(c.say(a.request))
        v = c.cur()
        if v:
            print("\n".join(f"  {p}" for p in v["files"]["png"] + ([v["files"]["pdf"]] if v["files"]["pdf"] else [])))
        return
    c = DesignChat.load(a.chat, planner=planner) if a.chat else DesignChat.start(planner=planner, files=a.extra)
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

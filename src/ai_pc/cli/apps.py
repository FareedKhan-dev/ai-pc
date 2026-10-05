"""Many programs, a basic setup each, by conversation: text from pictures (Windows OCR), PC care (winget apps, disk,
antivirus, Wi-Fi, battery), diagrams (flowcharts, org charts, mind maps; draw.io files), references (APA, MLA, Harvard,
IEEE, Chicago; BibTeX, RIS), quizzes (Moodle, GIFT, Kahoot, paper + key), ebooks (EPUB), playlists and VLC, printing,
maps (KML, GPX, GeoJSON, Google Maps routes) and Markdown notes and to-dos. Installs, removals, scans and printing are
shown first and done after a yes.

  ai-pc apps talk --with receipt.jpg -m "read the text in receipt.jpg"
  ai-pc apps talk -m "which apps can be updated?" -m "update vlc" -m "yes"
  ai-pc apps talk -m "flowchart: Start -> Take order -> In stock? -yes-> Pack -> End; In stock? -no-> Order -> Pack"
  ai-pc apps list
"""

import argparse
import sys

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="many programs, a basic setup each, by conversation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation")
    t.add_argument("-m", "--say", action="append", default=[])
    t.add_argument("--with", dest="files", nargs="*", default=[])
    sub.add_parser("list", help="the programs and what to say")
    s = sub.add_parser("steps", help="how to connect a program that needs keys (shopify, woocommerce, daraz, wordpress, odoo)")
    s.add_argument("program", nargs="?")
    c = sub.add_parser("connect", help="connect a program (keys typed at a hidden prompt, kept encrypted)")
    c.add_argument("program")
    a = ap.parse_args(argv)
    from ai_pc.apps import all_modules, load

    if a.cmd == "list":
        for m in all_modules():
            print(f"{m.LABEL}\n    e.g. " + "\n    e.g. ".join(m.EXAMPLES[:2]))
        return
    if a.cmd in ("steps", "connect"):
        mods = [load(a.program)] if a.program else [m for m in all_modules() if hasattr(m, "APP")]
        for m in mods:
            if not hasattr(m, "APP"):
                raise SystemExit(f"{m.NAME} needs no keys")
            print(f"\n== {m.APP['label']}  (ai-pc apps connect {m.NAME})")
            for i, st in enumerate(m.APP["steps"], 1):
                print(f"  {i}. {st}")
            if m.APP.get("notes"):
                print(f"  Note: {m.APP['notes']}")
        if a.cmd == "connect":
            import getpass

            m = mods[0]
            vals = {}
            for key, prompt, secret in m.APP["fields"]:
                v = (getpass.getpass(f"{prompt} (hidden): ") if secret else input(f"{prompt}: ")).strip()
                if not v:
                    raise SystemExit("nothing typed; nothing saved")
                vals[key] = v
            try:
                who = m.connect(vals)
                print(f"\nConnected {m.APP['label']}: {who.get('who')} ({who.get('where')}). Keys are kept encrypted for this Windows user.")
            except Exception as e:  # noqa: BLE001 - said, not raised
                print(f"\nNot connected: {e}")
        return
    from ai_pc.apps.appschat import AppsChat

    c = AppsChat.start(files=a.files)
    for msg in a.say or iter(lambda: input("> ").strip(), "quit"):
        if a.say:
            print(f"> {msg}")
        if msg.lower() in ("quit", "exit", "q"):
            break
        if msg:
            print(c.say(msg), flush=True)


if __name__ == "__main__":
    main()

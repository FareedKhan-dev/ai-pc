"""Social media through the platforms' official APIs: Facebook Pages, Instagram, Threads, YouTube, TikTok, LinkedIn and X.
One post composed once becomes each platform's own version (its kind of post, its words, its media converted and
measured); nothing is published without your yes; posts are read back, scheduled, measured, and their comments answered.

  ai-pc social steps [platform]       how to make each platform's free developer app and keys
  ai-pc social connect <platform>     sign in once (keys kept encrypted on this PC)
  ai-pc social status                 what is connected, checked live, and the limits left today
  ai-pc social talk --with eid.mp4 -m "post eid.mp4 to instagram reels and youtube shorts saying 'Eid sale!'" -m "yes"
  ai-pc social queue                  what is scheduled and going
  ai-pc social run [--quiet]          publish what is due now (Windows Task Scheduler runs this when
                                                            automatic posting is on)
  ai-pc social setup-tunnel           once, for Instagram pictures and Threads media: Cloudflare's free
                                                            tunnel tool into tools/cloudflared (checksum and signature checked)

Things to say: 'post <file> to instagram, tiktok and youtube tomorrow at 7 pm saying "..."', 'post it to facebook as a reel',
'what's scheduled?', 'cancel the tiktok one', 'delete that post from facebook', 'how did my posts do this week?',
'make a report', 'any new comments?', 'reply to 2: thank you!', 'hide 3', 'when should I post?', 'turn on automatic posting'.
"""
import argparse
import datetime as dt
import getpass
import sys

from ai_pc.core.paths import ROOT

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        _stream.reconfigure(encoding="utf-8", errors="replace")


def steps(name=None):
    from ai_pc.social import specs
    from ai_pc.social.auth import APPS
    for n in [name] if name else specs.NAMES:
        s = APPS[n]
        print(f"\n== {s['label']}  (ai-pc social connect {n})")
        for i, st in enumerate(s["steps"], 1):
            print(f"  {i}. {st}")
        if s.get("notes"):
            print(f"  Note: {s['notes']}")


def connect(name):
    from ai_pc.social import auth
    from ai_pc.social.base import SocialError
    if name not in auth.APPS:
        sys.exit(f"unknown platform {name}; one of: {', '.join(auth.APPS)}")
    steps(name)
    print()
    vals = {}
    for key, prompt, secret in auth.APPS[name]["fields"]:
        v = (getpass.getpass(f"{prompt} (hidden): ") if secret else input(f"{prompt}: ")).strip()
        if not v:
            sys.exit("nothing typed; nothing saved")
        vals[key] = v
    try:
        who = auth.connect(name, vals)
        print(f"\nConnected {auth.APPS[name]['label']}: {who.get('who')} ({who.get('where')}). Keys are kept encrypted for this Windows user.")
        for w in who.get("warnings") or []:
            print(f"  Note: {w}")
    except SocialError as e:
        print(f"\nNot connected: {e}")


def status():
    from ai_pc.social import specs
    from ai_pc.social.base import SocialError
    from ai_pc.social.platforms import connected
    from ai_pc.social.store import Store
    db = Store()
    have = connected(db)
    for n in specs.NAMES:
        if n not in have:
            print(f"  -  {specs.LABEL[n]}: not connected")
            continue
        try:
            w = have[n].whoami()
            lim = have[n].limits() or {}
            print(f"  ok {specs.LABEL[n]}: {w.get('who')} ({w.get('where')})" + (f"; {lim.get('words')}" if lim.get("words") else ""))
        except SocialError as e:
            print(f"  !! {specs.LABEL[n]}: {e}")


def queue():
    from ai_pc.social.socialchat import SocialChat
    print(SocialChat.start().run({"op": "queue"}))


def run(quiet=False):
    """Publish what is due (the scheduled task calls this every few minutes; one run at a time)."""
    from ai_pc.social import runner as RN
    from ai_pc.social.platforms import connected
    from ai_pc.social.prepare import prepare
    from ai_pc.social.store import Store
    log = ROOT / "state" / "social" / "runner.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with RN.Lock():
            db = Store()
            plats = connected(db)
            done = RN.run(db, plats, prepare) + RN.refresh(db, plats)
    except RN.Busy:
        done = []
    lines = [f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {d['platform']} {d['status']} {d.get('detail') or ''}" for d in done]
    if lines:
        with log.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    if not quiet:
        print("\n".join(lines) or "Nothing was due.")


def setup_tunnel():
    from ai_pc.social import tunnel_setup as TS
    if TS.DEST.exists():
        print(f"Already installed: {TS.DEST}")
        return
    print("Instagram (pictures) and Threads (all media) fetch media from a web address. The AI PC lends them one for about a minute\n"
          "through Cloudflare's free quick tunnel (no account). This downloads Cloudflare's 'cloudflared' tool (about 60 MB) from\n"
          "github.com/cloudflare/cloudflared into tools/cloudflared, checks it against Cloudflare's published SHA-256 and its Windows\n"
          "signature, and installs nothing in Windows.")
    if input("Download it now? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("Not downloaded.")
        return
    try:
        r = TS.install()
        print(f"Installed cloudflared {r['version']} (SHA-256 {r['sha256'][:16]}..., signed by {r['signer']}).")
    except Exception as e:  # noqa: BLE001
        print(f"Not installed: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="social media through official APIs: compose once, fitted per platform, nothing posted without your yes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("steps", help="how to make each platform's developer app and keys")
    s.add_argument("platform", nargs="?")
    c = sub.add_parser("connect", help="sign in to a platform once")
    c.add_argument("platform")
    sub.add_parser("status", help="what is connected, checked live")
    sub.add_parser("queue", help="what is scheduled")
    sub.add_parser("setup-tunnel", help="download Cloudflare's tunnel tool (for Instagram pictures and Threads media)")
    r = sub.add_parser("run", help="publish what is due now")
    r.add_argument("--quiet", action="store_true")
    t = sub.add_parser("talk", help="a conversation")
    t.add_argument("-m", "--say", action="append", default=[])
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="files the chat may post")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    a = ap.parse_args(argv)
    if a.cmd == "steps":
        return steps(a.platform)
    if a.cmd == "connect":
        return connect(a.platform)
    if a.cmd == "status":
        return status()
    if a.cmd == "queue":
        return queue()
    if a.cmd == "run":
        return run(a.quiet)
    if a.cmd == "setup-tunnel":
        return setup_tunnel()
    from ai_pc.social.socialchat import SocialChat
    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    sc = SocialChat.start(planner=planner, files=a.extra)
    print(f"Social chat {sc.state['id']}. Connected: {', '.join(sc.platforms()) or 'nothing yet (ai-pc social steps / ai-pc social connect)'}. 'quit' to leave.")
    for m in a.say or iter(lambda: input("> ").strip(), "quit"):
        if a.say:
            print(f"> {m}")
        if m.lower() in ("quit", "exit", "q", "bye"):
            break
        if m:
            print(sc.say(m), flush=True)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"(AI ${usd:.4f})")


if __name__ == "__main__":
    main()

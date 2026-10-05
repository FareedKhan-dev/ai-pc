"""The business hub, from the command line: Slack, Teams and Outlook, Gmail and Google Calendar/Drive/Sheets, Trello,
Notion, Asana, Jira, HubSpot, Zoom, Telegram and WhatsApp Business through their official APIs. Keys are typed at a
hidden prompt and kept encrypted on this PC (Windows DPAPI); nothing is sent or posted without your yes.

  ai-pc hub steps                  how to make each free key (or: ai-pc hub steps slack)
  ai-pc hub connect slack          paste the key (hidden); it is checked with the service at once
  ai-pc hub status                 what is connected, checked live
  ai-pc hub forget slack           remove a service's keys
  ai-pc hub talk                   a conversation ('quit' to leave)
  ai-pc hub talk -m "what's new in #general?" -m "post 'Meeting moved to 4 pm' to #general" -m "yes"

Things to say: 'post "..." to #general', 'message @ali on slack: ...', 'what's new in #sales?', 'send me a telegram: ...',
'check my email', 'draft an email to ali@x.com about the invoice saying ...', 'what's on my calendar tomorrow?',
'schedule a meeting with ali@x.com tomorrow at 3 pm about the budget', 'add a trello card "Fix the AC" to To Do',
'move "Fix the AC" to Done', 'add a task "Call the supplier" due friday in asana', 'create a jira bug "Login fails" in WEB',
'add Sara Khan sara@x.com to hubspot', 'upload report.pdf to drive', 'create a zoom meeting tomorrow at 4 pm "Weekly sync"',
'brief me', 'undo', 'what did you do today?'. Outward actions are shown first; say 'yes' (or 'send') to go ahead, 'no' to drop.
"""

import argparse
import getpass
import sys

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def steps(name=None):
    from ai_pc.hub.catalog import ORDER, SERVICES

    for n in [name] if name else ORDER:
        s = SERVICES[n]
        print(f"\n== {s['label']}  (ai-pc hub connect {n})")
        for i, st in enumerate(s["steps"], 1):
            print(f"  {i}. {st}")
        if s.get("notes"):
            print(f"  Note: {s['notes']}")


def connect(name):
    from ai_pc.core import vault
    from ai_pc.hub import oauth
    from ai_pc.hub.catalog import SERVICES
    from ai_pc.hub.http import HubError
    from ai_pc.hub.services import connector

    if name not in SERVICES:
        sys.exit(f"unknown service {name}; one of: {', '.join(SERVICES)}")
    steps(name)
    print()
    vals = {}
    for key, prompt, secret in SERVICES[name]["fields"]:
        v = (getpass.getpass(f"{prompt} (hidden): ") if secret else input(f"{prompt}: ")).strip()
        if not v:
            sys.exit("nothing typed; nothing saved")
        vals[key] = v
    vault.put(name, vals)
    try:
        if name == "google":
            oauth.google_signin(vals["client_id"], vals["client_secret"])
        elif name == "microsoft":
            teams = input("Use Teams too (needs a work or school account)? [y/N]: ").strip().lower().startswith("y")
            oauth.microsoft_signin(vals["client_id"], teams=teams)
        elif name == "canva":
            oauth.canva_signin(vals["client_id"], vals["client_secret"])
        who = connector(name).whoami()
        print(f"\nConnected {SERVICES[name]['label']}: {who.get('who')} ({who.get('where')}). The key is stored encrypted for this Windows user.")
    except HubError as e:
        print(
            f"\nThe key was saved, but the check failed: {e}\nFix it on the service's site and run 'ai-pc hub connect {name}' again, or 'ai-pc hub forget {name}'."
        )


def status():
    from ai_pc.hub.catalog import ORDER, SERVICES
    from ai_pc.hub.http import HubError
    from ai_pc.hub.services import connected, connector

    have = set(connected())
    for n in ORDER:
        if n not in have:
            print(f"  -  {SERVICES[n]['label']}: not connected")
            continue
        try:
            w = connector(n).whoami()
            print(f"  ok {SERVICES[n]['label']}: {w.get('who')} ({w.get('where')})")
        except (HubError, KeyError) as e:
            print(f"  !! {SERVICES[n]['label']}: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the business hub: work apps through their official APIs, nothing sent without your yes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("steps", help="how to make each free key")
    s.add_argument("service", nargs="?")
    c = sub.add_parser("connect", help="connect a service (the key is typed at a hidden prompt)")
    c.add_argument("service")
    sub.add_parser("status", help="what is connected, checked live")
    f = sub.add_parser("forget", help="remove a service's keys")
    f.add_argument("service")
    t = sub.add_parser("talk", help="a conversation")
    t.add_argument("-m", "--say", action="append", default=[])
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="files the chat may send or upload")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    a = ap.parse_args(argv)
    if a.cmd == "steps":
        return steps(a.service)
    if a.cmd == "connect":
        return connect(a.service)
    if a.cmd == "status":
        return status()
    if a.cmd == "forget":
        from ai_pc.core import vault

        print("Removed." if vault.remove(a.service) else "It was not connected.")
        return
    from ai_pc.hub.hubchat import HubChat

    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    hc = HubChat.start(planner=planner, files=a.extra)
    print(
        f"Hub chat {hc.state['id']}. Connected: {', '.join(hc.services()) or 'nothing yet (ai-pc hub steps / ai-pc hub connect)'}. 'quit' to leave."
    )
    msgs = a.say
    if msgs:
        for m in msgs:
            print(f"> {m}")
            print(hc.say(m), flush=True)
    else:
        while True:
            try:
                m = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if m.lower() in ("quit", "exit", "q", "bye"):
                break
            if m:
                print(hc.say(m), flush=True)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"(AI ${usd:.4f}; actions logged in state/hub/audit.jsonl)")


if __name__ == "__main__":
    main()

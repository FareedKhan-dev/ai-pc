"""The desktop agent's command line:  ai-pc agent <command>

  run "goal" [--app NAME] [--live] [--confirm ask|deny|allow] [--planner chat|file] [--deep] [--no-skill] [--no-learn]
             [--param k=v ...] [--allow-app proc.exe ...]
  skills [list | show NAME | delete NAME]
  apps [QUERY]            list/search installed apps (discovered at runtime)
  probe [--app NAME]      read-only: show what the planner would see for a window
  grounder [status|start] the vision click model server (Vocaela by default, CUA_GROUNDER=tinyclick for TinyClick)

Default is a DRY RUN (plans and prints, touches nothing). Add --live to act. Ctrl+Alt+Q aborts a live run.
"""
import argparse
import json
import sys

from ai_pc.core.config import BLOCKED_PROCS
from ai_pc.desktop import apps, observe, uia
from ai_pc.desktop.agent import Agent
from ai_pc.desktop.grounder import make_grounder
from ai_pc.desktop.safety import Confirmer
from ai_pc.desktop.skills import SkillStore


def _planner(kind):
    if kind == "file":
        from ai_pc.llm.planner import FilePlanner
        return FilePlanner()
    from ai_pc.llm.planner import ChatPlanner
    return ChatPlanner()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai-pc agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("goal")
    r.add_argument("--app")
    r.add_argument("--live", action="store_true")
    r.add_argument("--confirm", default="ask", choices=["ask", "deny", "allow"])
    r.add_argument("--planner", default="chat", choices=["chat", "file"])
    r.add_argument("--deep", action="store_true")
    r.add_argument("--no-skill", action="store_true")
    r.add_argument("--no-learn", action="store_true")
    r.add_argument("--param", action="append", default=[])
    r.add_argument("--allow-app", action="append", default=[])
    s = sub.add_parser("skills")
    s.add_argument("action", nargs="?", default="list")
    s.add_argument("name", nargs="?")
    a = sub.add_parser("apps")
    a.add_argument("query", nargs="?")
    p = sub.add_parser("probe")
    p.add_argument("--app")
    g = sub.add_parser("grounder")
    g.add_argument("action", nargs="?", default="status")
    args = ap.parse_args(argv)

    if args.cmd == "run":
        params = dict(kv.split("=", 1) for kv in args.param)
        agent = Agent(planner=_planner(args.planner), grounder=make_grounder(), confirm=Confirmer(args.confirm),
                      dry_run=not args.live, allow_apps=args.allow_app)
        if not args.live:
            print("DRY RUN: nothing will be executed (add --live to act)")
        res = agent.run(args.goal, app=args.app, params=params, use_skill=not args.no_skill, learn=not args.no_learn, deep=args.deep)
        print("\n" + json.dumps(res.__dict__, indent=1, default=str))
        return 0 if res.ok else 1
    if args.cmd == "skills":
        st = SkillStore()
        if args.action == "list":
            for sk in st.list():
                stt = sk.get("stats", {})
                print(f"{sk['name']:<40s} steps={len(sk['steps']):<3d} params={sk['params']} runs={stt.get('runs', 0)} ok={stt.get('ok', 0)} {'DISABLED' if sk.get('disabled') else ''}")
                print(f"    intent: {sk['intent']}")
        elif args.action == "show":
            print(json.dumps(st.get(args.name), indent=1, ensure_ascii=False))
        elif args.action == "delete":
            print("deleted" if st.delete(args.name) else "not found")
        return 0
    if args.cmd == "apps":
        for x in apps.installed_apps():
            if not args.query or args.query.lower() in x["name"].lower():
                print(f"{x['name']:<45s} {x['appid']}")
        return 0
    if args.cmd == "probe":
        h = apps.find_window(title_substr=args.app, exclude=BLOCKED_PROCS) if args.app else None
        if not h:
            print("no matching window (pass --app with part of the window title)")
            return 1
        snap = uia.snapshot(h)
        print(observe.render(snap))
        print(f"\n[snapshot took {snap.ms:.0f} ms]")
        return 0
    if args.cmd == "grounder":
        g = make_grounder()
        if args.action == "start":
            g.ensure()
        print("grounder alive:", g.alive())
        return 0


if __name__ == "__main__":
    sys.exit(main())

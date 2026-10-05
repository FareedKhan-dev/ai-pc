"""Studio: the whole agent, from a request in plain words to a checked video.

  new(request, files)     analyse media + brief (parallel) -> search -> plan -> resolve -> build -> export -> verify at
                          the edit points -> fix what failed -> rebuild / re-export / re-check only what changed
  revise(draft, request)  a follow-up in plain words ("make the lightning stronger", "add a title at the end") applied to
                          an existing edit: only the changed edits are rebuilt and re-checked

Exports that JianYing refuses are handled too: items it cannot download are recorded and replaced; if it asks for a
login, the items not yet proven are tested in small probe projects (split in halves) to find the ones that need an
account, which are then recorded and replaced. Everything is saved in out/video/sessions/<draft>.json.
"""
import json
import time
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json
from ai_pc.video import analyze as AN
from ai_pc.video import critic as CR
from ai_pc.video import editplan as EP
from ai_pc.video import jybuild as JB
from ai_pc.video import jyres
from ai_pc.video import lessons as LS
from ai_pc.video import report as RP
from ai_pc.video import verify as V
from ai_pc.video.director import Director
from ai_pc.video.fixer import Fixer, merge_reports, plan_diff

SESSIONS = ROOT / "out" / "video" / "sessions"

REVISE_SYSTEM = """You revise an existing video edit plan (JSON, the format below) according to the user's follow-up.
Change ONLY what the follow-up asks; keep every other clip and edit exactly as it is (same ids). New edits get new ids.
Names of effects, filters, transitions, animations and fonts: copy exactly from CANDIDATES or from the current plan.
Reply with the complete updated plan JSON only.

"""


timeline = CR.timeline


def _save(sess):
    SESSIONS.mkdir(parents=True, exist_ok=True)
    p = SESSIONS / f"{sess['map']['draft']}.json"
    p.write_text(json.dumps(sess, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load(draft):
    return json.loads((SESSIONS / f"{draft}.json").read_text(encoding="utf-8"))


class Studio:
    def __init__(self, planner=None, log=print, export=True, fix_rounds=2):
        if planner is None:
            from ai_pc.llm.planner import ChatPlanner
            planner = ChatPlanner()
        self.planner, self.log, self.do_export, self.fix_rounds = planner, log, export, fix_rounds
        self.timings = {}

    # ------------------------------------------------------------------ steps
    def _build(self, plan, analyses, R=None):
        t = time.perf_counter()
        if R is None:
            EP.Catalog._shared = None  # the availability record may have changed: reload it
            R = EP.resolve(plan, analyses)
        M = JB.build(R)
        self.log(f"built {M['draft']}: {M['seconds']:.1f} s, {len(M['tracks'])} tracks, {sum(M['stats'].values())} operations "
                 f"in {(time.perf_counter() - t) * 1000:.0f} ms" + (f"; {len(R['notes'])} note(s)" if R["notes"] else ""))
        for n in R["notes"]:
            self.log(f"    note: {n}")
        lost = [n for n in M["notes"] if n.startswith(("add video", "video piece", "add layer"))]
        if lost:  # a piece missing from the main track shows as black: never let that reach a render unnoticed
            self.log(f"    BUILD PROBLEM: {len(lost)} video piece(s) not placed: {lost[0][:120]}")
        return R, M

    def _probe_plan(self, keys, analyses):
        """A small project that uses exactly `keys` (to find out whether JianYing lets them export)."""
        video = next((a["file"] for a in analyses.values() if a.get("kind") == "video"), None) or \
            next((a["file"] for a in analyses.values() if a.get("kind") == "image"), None)
        cat = EP.Catalog.shared()
        trans = [k for k in keys if k.startswith("transition:")]
        canim = [k for k in keys if k.split(":")[0] in ("clip_intro", "clip_outro", "clip_combo")]
        n = max(2, len(trans) + 1, len(canim))
        clips = [{"id": f"c{i + 1}", "file": video, "from": 0.5 * i, "duration": 1.2} for i in range(n)]
        edits, t = [], 0.0
        for i, k in enumerate(sorted(keys)):
            c, name = k.split(":", 1)
            nm = cat.item(k)["name"]
            if c == "transition":
                edits.append({"id": f"p{i}", "type": "transition", "after": f"c{trans.index(k) + 1}", "name": nm})
            elif c in ("clip_intro", "clip_outro", "clip_combo"):
                edits.append({"id": f"p{i}", "type": "animation", "on": f"c{canim.index(k) + 1}", "kind": c.split("_")[1], "name": nm})
            elif c in ("scene_effect", "character_effect"):
                edits.append({"id": f"p{i}", "type": "effect", "name": nm, "start": t % (1.2 * n - 0.4), "duration": 0.4})
            elif c == "filter":
                edits.append({"id": f"p{i}", "type": "filter", "name": nm, "start": t % (1.2 * n - 0.4), "duration": 0.4})
            elif c == "font":
                edits.append({"id": f"p{i}", "type": "text", "text": "Aa", "start": 0, "duration": 1.0, "font": nm, "position": [0, 0.5 - 0.1 * (i % 8)]})
            elif c in ("text_intro", "text_outro", "text_loop"):
                edits.append({"id": f"p{i}", "type": "text", "text": "Aa", "start": 0, "duration": 1.0, "position": [0, -0.1 * (i % 8)],
                              c.split("_")[1]: nm})
            t += 0.4
        return {"name": "probe", "canvas": "9:16", "clips": clips, "edits": edits}

    def _find_login_items(self, keys, analyses):
        """Split the not-yet-proven items in halves until the ones that make JianYing ask for a login are found."""
        from ai_pc.video.jy_export import export
        st = jyres.states()
        todo = [sorted(k for k in keys if st.get(k) != "exported")]
        culprits = []
        while todo:
            group = todo.pop()
            if not group:
                continue
            R = EP.resolve(self._probe_plan(group, analyses), analyses)
            M = JB.build(R)
            r = export(M["draft"], log=lambda m: None, start=True, emap=M)
            self.log(f"  login probe {len(group)} item(s): {'needs login' if r['login'] else 'ok' if r['ok'] else r['error']}")
            if r["login"]:
                if len(group) == 1:
                    culprits.append(group[0])
                    jyres.record(login=group)
                else:
                    todo += [group[:len(group) // 2], group[len(group) // 2:]]
            elif not r["ok"] and r["missing"]:
                todo.append([k for k in group if k not in r["missing"]])
        return culprits

    def _export(self, sess, analyses, tries=3):
        """Export the session's draft; replace items JianYing will not give us and retry. Returns the export result."""
        from ai_pc.video.jy_export import export
        for attempt in range(tries):
            M = sess["map"]
            t = time.perf_counter()
            r = export(M["draft"], log=self.log, start=True, emap=M)
            self.timings["export_s"] = self.timings.get("export_s", 0) + round(time.perf_counter() - t, 1)
            if r["ok"]:
                self.log(f"exported {M['draft']} in {r['seconds']:.1f} s")
                return r
            self.log(f"export refused: {r['error']}")
            if r["login"]:
                found = self._find_login_items(r["used"], analyses)
                self.log(f"  needs an account: {found or 'not found'}")
                if not found:
                    return r
            elif not r["missing"]:
                return r
            R, M = self._build(sess["plan"], analyses)  # the resolver now avoids what was recorded
            sess.update(resolved=R, map=M)
            _save(sess)
        return r

    def _verify_fix(self, sess, analyses):
        video = sess["export"]["path"]
        t = time.perf_counter()
        rep = V.verify(video, sess["map"], planner=self.planner, log=self.log)
        jyres.record_checks(sess["map"], rep)
        self.timings["verify_s"] = round(time.perf_counter() - t, 1)
        sess["report"] = rep
        tried = sess.setdefault("tried", {})
        for rnd in range(self.fix_rounds):
            bad = [r for r in rep["results"] if r["status"] == "fail" or (r["status"] == "warn" and r.get("type") in ("effect", "filter", "text", "captions"))]
            if not bad:
                break
            plan2, changes, recheck = Fixer(planner=self.planner, log=self.log).patch(sess["plan"], sess["resolved"], rep, tried)
            if not changes:
                self.log("nothing more to fix automatically")
                break
            self.log(f"fix round {rnd + 1}: " + "; ".join(changes))
            LS.from_fixes(changes, sess["resolved"])  # a repair is a mistake not to plan again
            R, M = self._build(plan2, analyses)
            prev = sess.copy()
            sess.update(plan=plan2, resolved=R, map=M, previous=prev.get("map", {}).get("draft"))
            if not self.do_export:
                break
            r = self._export(sess, analyses)
            sess["export"] = r
            if not r["ok"]:
                break
            # what overlaps a changed edit in time can be affected too (an overlay can hide another effect)
            wins = [e["window"] for e in M["edits"] if e["id"] in recheck and e.get("window")]
            recheck |= {e["id"] for e in M["edits"] if e.get("window") and e["type"] in ("effect", "text", "captions", "filter")
                        and any(e["window"][0] < b and a < e["window"][1] for a, b in wins)}
            rep2 = V.verify(r["path"], M, planner=self.planner, log=self.log, only=recheck)
            jyres.record_checks(M, rep2)
            rep = merge_reports(rep, rep2)
            sess["report"] = rep
        return rep

    # ------------------------------------------------------------------ entry points
    def _reflect(self, sess):
        try:
            a, md = RP.assess(sess)
            sess["assessment"] = a
            p = RP.save(a, md)
            self.log(RP.short(a))
            self.log(f"report: {p}")
        except Exception as e:  # noqa: BLE001  (the report must never sink a finished edit)
            self.log(f"report failed: {type(e).__name__}: {e}")

    def new(self, request, files, references=None):
        """A new edit. references: sample edits whose style to match ("make it like this"); measured, not used as footage."""
        t0 = time.perf_counter()
        files = [str(Path(f)) for f in files]
        if self.do_export:
            from ai_pc.video.jy_export import prewarm
            if prewarm():  # JianYing starts while the plan is being written (saves ~15 s)
                self.log("starting JianYing in the background")
        d = Director(self.planner, log=self.log)
        plan, brief, groups, analyses, tm = d.run(request, files, references)
        self.edit_type = {k: d.edit_type[k] for k in ("type", "label", "confidence", "reasons", "alternatives")}
        self.reference = d.reference
        files += [a["path"] for a in analyses.values() if a.get("path") and a["path"] not in files]  # e.g. a generated music bed
        self.timings.update(tm)
        t = time.perf_counter()
        plan, R, crit = CR.improve(self.planner, request, brief, plan, analyses, d.aware_text, groups, log=self.log, design=d.design_json)
        if crit.get("design") is not None:
            d.design_json = crit["design"]
        crit.pop("design", None)
        self.timings["critic_s"] = round(time.perf_counter() - t, 1)
        R, M = self._build(plan, analyses, R=R)
        # the critic may have re-cut the edit with a new music bed: the session lists every file the final plan uses
        files += [a["path"] for a in analyses.values() if a.get("path") and a["path"] not in files]
        sess = {"request": request, "files": files, "brief": brief, "plan": plan, "resolved": R, "map": M, "timings": self.timings,
                "awareness": d.aware, "critic": crit, "design": d.design_json, "edit_type": self.edit_type,
                "reference": self.reference, "references": [str(r) for r in references or []]}
        _save(sess)
        if self.do_export:
            r = self._export(sess, analyses)
            sess["export"] = r
            _save(sess)
            if r["ok"]:
                self._verify_fix(sess, analyses)
        self.timings["total_s"] = round(time.perf_counter() - t0, 1)
        sess["timings"] = self.timings
        sess["ai_usage"], sess["ai_usd"] = self.planner.cost()
        self._reflect(sess)
        _save(sess)
        jyres.note_usage(sess["map"])  # the next videos avoid this one's filters, transitions and fonts
        return sess

    def from_template(self, request, files, template, texts=None):
        """A new edit that follows a template exactly: learn it (or take it from the library), fill its slots with the
        client's footage, build, export, check every edit point, fix, then check the cuts against the template's."""
        import re as _re

        from ai_pc.video import template as TP
        t0 = time.perf_counter()
        files = [str(Path(f)) for f in files]
        if self.do_export:
            from ai_pc.video.jy_export import prewarm
            if prewarm():
                self.log("starting JianYing in the background")
        # a library name, a video of the template, its CapCut link, a screenshot of its page, or words describing it
        tpl = TP.resolve(template, self.planner, log=self.log)
        t = time.perf_counter()
        analyses = AN.analyze(files, planner=self.planner, log=self.log)
        self.timings["analysis_s"] = round(time.perf_counter() - t, 1)
        req = str(request or "").lower()
        canvas = "16:9" if _re.search(r"\b(?:16:9|youtube|horizontal|landscape)\b", req) else \
            "9:16" if _re.search(r"\b(?:9:16|tiktok|reels?|shorts|vertical|portrait)\b", req) else None
        plan, info = TP.fill(tpl, analyses, request, canvas=canvas, texts=texts, log=self.log)
        files += [a["path"] for a in analyses.values() if a.get("path") and a["path"] not in files]  # the music bed
        R, M = self._build(plan, analyses)
        design = {"template": tpl["name"], "template_source": tpl.get("source"), "pins": {}, "avoid_files": [], "music": None,
                  "canvas": plan["canvas"], "texts": texts}
        sess = {"request": request, "files": files, "brief": {}, "plan": plan, "resolved": R, "map": M, "design": design,
                "template_info": info, "timings": self.timings,
                "edit_type": {"type": "template", "label": f"Template '{tpl['name']}'", "confidence": 1.0, "reasons": ["follows a template"],
                              "alternatives": []}}
        _save(sess)
        if self.do_export:
            r = self._export(sess, analyses)
            sess["export"] = r
            _save(sess)
            if r["ok"]:
                self._verify_fix(sess, analyses)
                if sess.get("export", {}).get("ok"):
                    planned = [c["start"] for c in sess["resolved"]["clips"][1:]]
                    sess["template_match"] = m = TP.match(tpl, sess["export"]["path"], cuts_planned=planned)
                    self.log(f"template match: {m['found_on_time']}/{m['template_cuts']} cuts on the template's frames, "
                             f"{m['length']} s for {m['template_length']} s")
                    rep = sess.get("report") or {}
                    if rep.get("results") is not None:  # the scan misses cuts between look-alike shots: most of them on time is a pass
                        ok = m["rhythm_match"] >= 0.8 and abs(m["length"] - float(m["template_length"] or m["length"])) < 0.3
                        rep["results"].append({"id": "template_match", "type": "template", "status": "pass" if ok else "warn",
                                               "why": f"{m['found_on_time']}/{m['template_cuts']} cuts found on the planned frames, "
                                                      f"{m['length']} s for {m['template_length']} s", "evidence": m})
                        rep["counts"] = {k: sum(1 for r in rep["results"] if r.get("status") == k) for k in ("fail", "warn", "pass", "skip")}
        self.timings["total_s"] = round(time.perf_counter() - t0, 1)
        sess["timings"] = self.timings
        sess["ai_usage"], sess["ai_usd"] = self.planner.cost()
        self._reflect(sess)
        _save(sess)
        jyres.note_usage(sess["map"])
        return sess

    def revise(self, draft, request):
        """A follow-up request on an existing edit: the model updates the plan, only the changes are rebuilt/checked."""
        t0 = time.perf_counter()
        old = load(draft)
        LS.from_feedback(request)  # what a user asks to change is a preference for next time
        analyses = AN.analyze(old["files"], planner=self.planner, log=self.log)
        d = Director(self.planner, log=self.log)
        brief = {"needs": [{"id": "n1", "what": request, "kinds": ["scene_effect", "character_effect", "filter", "transition", "text_intro", "font"],
                            "query": request}], "mood": (old.get("brief") or {}).get("mood", "")}
        groups = d.candidates(brief, per_kind=4)
        from ai_pc.video.director import PLAN_SYSTEM, _card_line
        cands = "\n".join(f"[{g}]\n" + "\n".join(_card_line(c) for c in cs) for g, cs in groups.items())
        media = "\n".join(AN.describe(a) for a in analyses.values())
        user = (f"FOLLOW-UP: {request}\n\nORIGINAL REQUEST: {old['request']}\n\nCURRENT PLAN:\n{json.dumps(old['plan'], ensure_ascii=False)}\n\n"
                f"TIMELINE OF THE CURRENT EDIT (absolute seconds; use it to place anything 'when X happens'):\n{timeline(old['resolved'])}\n\n"
                f"MEDIA:\n{media}\n\nCANDIDATES:\n{cands}\n\nReply with the updated plan JSON.")
        t = time.perf_counter()
        r = self.planner._call("video", [{"role": "system", "content": REVISE_SYSTEM + PLAN_SYSTEM}, {"role": "user", "content": user}])
        plan = parse_json(r.text)
        if not isinstance(plan, dict):
            raise ValueError("the model returned no valid plan")
        plan.setdefault("think", old["plan"].get("think"))
        self.timings["revise_s"] = round(time.perf_counter() - t, 1)
        from ai_pc.video import awareness
        aware, aware_text = awareness.snapshot(old.get("brief") or {}, analyses, groups, d.cat, LS.text())
        plan, R, crit = CR.improve(self.planner, f"{old['request']}\nFOLLOW-UP: {request}", old.get("brief") or {}, plan, analyses,
                                   aware_text, groups, log=self.log)
        changed = plan_diff(old["plan"], plan)
        self.log(f"revised plan in {self.timings['revise_s']} s; changed edits: {sorted(changed) or 'clips only'}")
        R, M = self._build(plan, analyses, R=R)
        sess = {"request": old["request"], "followups": old.get("followups", []) + [request], "files": old["files"], "brief": old.get("brief"),
                "plan": plan, "resolved": R, "map": M, "previous": draft, "timings": self.timings, "awareness": aware, "critic": crit}
        _save(sess)
        if self.do_export:
            r = self._export(sess, analyses)
            sess["export"] = r
            if r["ok"]:
                ids = {e["id"] for e in R["edits"] if e["id"] in changed or any(e.get("on") == c for c in changed)} or None
                rep = V.verify(r["path"], M, planner=self.planner, log=self.log, only=ids)
                sess["report"] = rep
        self.timings["total_s"] = round(time.perf_counter() - t0, 1)
        sess["ai_usage"], sess["ai_usd"] = self.planner.cost()
        self._reflect(sess)
        _save(sess)
        return sess

"""How exactly the template learner finds shot changes: our 10 batch exports have known timelines (where every clip
starts, which transition or flash hides each cut), so detected cuts can be scored against the truth.

  .venv\\Scripts\\python.exe tests\\integration\\template_cuts_eval.py [--count] [--no-beats]
--count: the number of clips is known (as a CapCut template's page says "4 clips"): the weakest extra cuts are left out
and missed ones taken back (template.constrain_cuts).
A true cut counts as found when a detected cut lies within 2 frames of it (hard cuts) or within half the transition's
length plus 2 frames (cuts under a transition or flash). Boundaries between two clips of the same file that continue
the same moment are not visible and are not counted.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from ai_pc.media import frames as F  # noqa: E402
from ai_pc.video import template as TP  # noqa: E402
from ai_pc.video.studio import load  # noqa: E402

DRAFTS = [
    "agent_road_195510",
    "agent_no_180359",
    "agent_easystirfr_183910",
    "agent_coastal_180718",
    "agent_unleashed_181048",
    "agent_saraadamfo_181609",
    "agent_smart_181728",
    "agent_match_195204",
    "agent_thetwoseas_200445",
    "agent_saturday_200044",
]


def truth(sess):
    R = sess["resolved"]
    clips = R["clips"]
    trans = {e.get("after"): e for e in R["edits"] if e["type"] == "transition"}
    out = []
    for a, b in zip(clips, clips[1:]):
        pa, pb = a["pieces"][-1], b["pieces"][0]
        same = (
            a["file"] == b["file"]
            and abs(pa["src_from"] + pa["src_span"] - pb["src_from"]) < 0.15
            and a.get("settings", {}).get("scale") == b.get("settings", {}).get("scale")
        )
        if same:
            continue
        tr = trans.get(a["id"])
        out.append({"t": round(b["start"], 3), "tol": (tr["duration"] / 2 if tr else 0.0), "kind": "transition" if tr else "cut"})
    return out


def score(found, true, fps):
    used, hit = set(), 0
    for t in true:
        tol = t["tol"] + 2.0 / fps
        best = min(
            (j for j in range(len(found)) if j not in used and abs(found[j]["t"] - t["t"]) <= tol + 1e-6),
            key=lambda j: abs(found[j]["t"] - t["t"]),
            default=None,
        )
        if best is not None:
            used.add(best)
            hit += 1
            t["found"] = found[best]["kind"]
    return hit, len(found) - len(used)


def main():
    rows, tp_all, fn_all, fp_all = [], 0, 0, 0
    for d in DRAFTS:
        sess = load(d)
        path = sess["export"]["path"]
        info = F.probe(path)
        fps = min(TP.FPS_MAX, float(info.get("fps") or 30) or 30)
        t0 = time.perf_counter()
        fr = F.window(path, 0, float(info["seconds"]), fps=fps, width=112)
        gb = TP.decode_gray(path, float(info["seconds"]), fps)
        from ai_pc.media import audio as AU

        snd = AU.analyze(path) if info.get("has_audio") else None
        beats = (snd or {}).get("beats") if (snd or {}).get("beat_confidence", 0) > 0.12 else None
        cuts, flashes, sig = TP.detect_cuts(fr, fps, gb, beats=beats if "--no-beats" not in sys.argv else None)
        secs = time.perf_counter() - t0
        tr = truth(sess)
        if "--count" in sys.argv:
            cuts, _ = TP.constrain_cuts(cuts, len(tr), sig.get("rejected") or [], len(fr), fps, beats)
        hit, extra = score(cuts, tr, fps)
        miss = len(tr) - hit
        tp_all, fn_all, fp_all = tp_all + hit, fn_all + miss, fp_all + extra
        hard = [t for t in tr if t["kind"] == "cut"]
        soft = [t for t in tr if t["kind"] == "transition"]
        rows.append(
            {
                "draft": d,
                "true": len(tr),
                "found": len(cuts),
                "hit": hit,
                "missed": miss,
                "extra": extra,
                "hard_hit": f"{sum(1 for t in hard if t.get('found'))}/{len(hard)}",
                "soft_hit": f"{sum(1 for t in soft if t.get('found'))}/{len(soft)}",
                "flashes": len(flashes),
                "seconds": round(secs, 1),
                "missed_at": [t["t"] for t in tr if not t.get("found")][:8],
            }
        )
        r = rows[-1]
        print(
            f"{d:26s} true {r['true']:3d} found {r['found']:3d} | hit {hit:3d} missed {miss:2d} extra {extra:2d} | hard {r['hard_hit']:>6s} "
            f"under transitions {r['soft_hit']:>6s} | flashes {len(flashes):2d} | {secs:.1f}s  missed at {r['missed_at']}"
        )
    prec = tp_all / max(1, tp_all + fp_all)
    rec = tp_all / max(1, tp_all + fn_all)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    print(f"\nALL: recall {rec:.1%}, precision {prec:.1%}, F1 {f1:.1%} ({tp_all} found, {fn_all} missed, {fp_all} extra)")
    (ROOT / "out" / "video" / "template_cuts_eval.json").write_text(
        json.dumps({"recall": rec, "precision": prec, "f1": f1, "rows": rows}, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

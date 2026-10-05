"""Results written down: an Excel workbook of every post's numbers with a chart, and the posting times that worked best
for YOUR posts (from their own numbers only: with too few posts it says so instead of guessing).

  excel(rows, db, path) -> path        rows: [(job, metrics)]
  best_times(db, platforms=None) -> words
"""

import datetime as dt
from collections import defaultdict
from pathlib import Path

from ai_pc.social import specs

KEYS = ("views", "reach", "likes", "comments", "shares", "saves")


def excel(rows, db, path):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Posts"
    head = ["Platform", "Kind", "Published", "Caption", "Link"] + [k.title() for k in KEYS]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
        c.alignment = Alignment(vertical="center")
    for j, m in rows:
        p = db.post(j["post_id"]) or {}
        when = (j.get("published_at") or "")[:16].replace("T", " ")
        ws.append(
            [
                specs.LABEL.get(j["platform"], j["platform"]),
                specs.FORMAT_WORDS.get(j.get("format"), j.get("format")),
                when,
                (p.get("text") or "")[:120],
                (j.get("remote") or {}).get("permalink") or "",
            ]
            + [m.get(k) for k in KEYS]
        )
    n = len(rows)
    if n:
        ws.append(["Total", "", "", "", ""] + [f"=SUM({chr(70 + i)}2:{chr(70 + i)}{n + 1})" for i in range(len(KEYS))])
        for c in ws[n + 2]:
            c.font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJK", (12, 10, 17, 50, 40, 9, 9, 9, 10, 9, 9)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    if n:
        ch = BarChart()
        ch.title = "Views per post"
        ch.y_axis.title = "Views"
        ch.y_axis.delete = False
        ch.x_axis.delete = False
        ch.add_data(Reference(ws, min_col=6, min_row=1, max_row=n + 1), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + 1))
        ch.width, ch.height = 22, 9
        ws.add_chart(ch, f"A{n + 4}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return str(path)


def best_times(db, platforms=None, minimum=6):
    """When your own posts did best: engagement per post by weekday and hour slot (morning, afternoon, evening, night)."""
    slots = defaultdict(list)
    n = 0
    for j in db.jobs(status=["published"]):
        if platforms and j["platform"] not in platforms:
            continue
        at, m = db.latest_metrics(j["id"])
        if not m or not j.get("published_at"):
            continue
        t = dt.datetime.fromisoformat(j["published_at"])
        eng = sum((m.get(k) or 0) for k in ("likes", "comments", "shares", "saves"))
        part = "morning" if 5 <= t.hour < 12 else "afternoon" if t.hour < 17 else "evening" if t.hour < 22 else "night"
        slots[(t.strftime("%A"), part)].append(eng)
        n += 1
    if n < minimum:
        return (
            f"Not enough of your own posts with numbers yet ({n}; at least {minimum} are needed). Post at a few different times, ask "
            f"'how did my posts do?' a day later, then ask again: the answer will come from your followers, not from general advice."
        )
    best = sorted(((sum(v) / len(v), k, len(v)) for k, v in slots.items()), reverse=True)[:3]
    return (
        "Your posts did best on: "
        + "; ".join(f"{d} {p} (average {avg:.0f} likes, comments, shares and saves, {c} posts)" for avg, (d, p), c in best)
        + "."
    )

"""Calendar invites and reminders as .ics files (Google Calendar, Outlook, Apple and phone calendars import them): an
event in words becomes one with its date, time, length, place, a reminder before it and, if said, a repeat (daily,
every Friday, monthly on the 5th); all events are also kept in one calendar file to import at once. Times are
Pakistan time (Asia/Karachi, UTC+5).

  'meeting with Ali Traders on 12 October at 3 pm for 1 hour at the shop'   'remind me to pay rent every month on the 5th at 10 am'
"""

import datetime as dt
import re
import uuid
from pathlib import Path

from ai_pc.hub.hubparse import when

NAME, LABEL = "calendar", "Calendar invites and reminders (.ics)"
EXAMPLES = ["meeting with Ali Traders on 12 October at 3 pm for 1 hour at the shop", "remind me to pay rent every month on the 5th at 10 am"]
TZ = (
    "BEGIN:VTIMEZONE\r\nTZID:Asia/Karachi\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0500\r\nTZOFFSETTO:+0500\r\nTZNAME:PKT\r\n"
    "END:STANDARD\r\nEND:VTIMEZONE\r\n"
)
DAYS = {"monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR", "saturday": "SA", "sunday": "SU"}


def _esc(s):
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def read(text, now):
    c = text.lower()
    day, t = when(c, now)
    rule = None
    m = re.search(r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", c)
    if m:
        rule = f"FREQ=WEEKLY;BYDAY={DAYS[m.group(1)]}"
        k = list(DAYS).index(m.group(1))
        day = day or now.date() + dt.timedelta(days=(k - now.weekday()) % 7 or 7)
    m2 = re.search(r"\bevery month\b.*?\bon the (\d{1,2})(?:st|nd|rd|th)?\b|\bmonthly on the (\d{1,2})", c)
    if m2:
        d = int(m2.group(1) or m2.group(2))
        rule = f"FREQ=MONTHLY;BYMONTHDAY={d}"
        first = now.date().replace(day=min(d, 28))
        day = day or (first if first >= now.date() else (first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12))))
    if re.search(r"\bevery ?day\b|\bdaily\b", c):
        rule = "FREQ=DAILY"
        day = day or now.date()
    if not day:
        return None
    mins = 60
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)\b", c)
    if m:
        mins = int(float(m.group(1)) * (60 if m.group(2).startswith("h") else 1))
    place = re.search(r"\b(?:at|in)\s+(?:the\s+)?([a-z][\w' ]{2,40}?)(?:\s+(?:on|for|at|every)\b|$)", c[c.find(" ", 0) :] if t else c)
    where = None
    if place and not re.match(r"^\d", place.group(1)) and place.group(1).strip() not in ("noon",):
        where = place.group(1).strip()
    title = (
        re.sub(
            r"\b(?:on|at|for|every|from|in)\b.*$",
            "",
            re.sub(r"^\s*(?:remind me to|reminder to|add|schedule|book)\s+", "", text, flags=re.I),
            flags=re.I,
        ).strip(" ,.")
        or "Event"
    )
    title = re.sub(r"\b(?:tomorrow|today|tonight|next \w+)\b", "", title, flags=re.I).strip(" ,.")
    return {
        "title": title[:1].upper() + title[1:],
        "start": dt.datetime.combine(day, t or dt.time(9, 0)),
        "all_day": t is None and not rule,
        "minutes": mins,
        "where": where,
        "rule": rule,
        "reminder": 30 if re.search(r"\bremind", c) else 15,
    }


def ics(events):
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI PC//Calendar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    body = []
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        b = ["BEGIN:VEVENT", f"UID:{e.get('uid') or uuid.uuid4()}@aipc", f"DTSTAMP:{stamp}", f"SUMMARY:{_esc(e['title'])}"]
        s = e["start"] if isinstance(e["start"], dt.datetime) else dt.datetime.fromisoformat(e["start"])
        if e.get("all_day"):
            b += [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{s + dt.timedelta(days=1):%Y%m%d}"]
        else:
            b += [f"DTSTART;TZID=Asia/Karachi:{s:%Y%m%dT%H%M%S}", f"DTEND;TZID=Asia/Karachi:{s + dt.timedelta(minutes=e['minutes']):%Y%m%dT%H%M%S}"]
        if e.get("where"):
            b.append(f"LOCATION:{_esc(e['where'])}")
        if e.get("rule"):
            b.append(f"RRULE:{e['rule']}")
        b += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(e['title'])}", f"TRIGGER:-PT{e.get('reminder', 15)}M", "END:VALARM", "END:VEVENT"]
        body += b
    return "\r\n".join(out) + "\r\n" + TZ + "\r\n".join(body) + "\r\nEND:VCALENDAR\r\n"


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\b(?:meeting|appointment|call|event|remind me|reminder|schedule|book|class|lecture|wedding|party|dinner|interview)\b", c):
        return None
    if re.search(r"\b(?:invoice|quote|bill)\b", c):
        return None
    e = read(text, ctx.get("now") or dt.datetime.now())
    return {"op": "event", "event": e} if e else None


def run(op, ctx):
    e = op["event"]
    out = Path(ctx["out"]) / "calendar"
    out.mkdir(parents=True, exist_ok=True)
    one = out / (re.sub(r"[^\w-]+", "_", e["title"])[:50] + ".ics")
    one.write_text(ics([e]), encoding="utf-8", newline="")
    text = one.read_text(encoding="utf-8")
    ok = text.count("BEGIN:VEVENT") == 1 and "END:VCALENDAR" in text and (e["title"].split()[0] in text)
    when_ = "all day " + f"{e['start']:%a %d %b %Y}" if e["all_day"] else f"{e['start']:%a %d %b %Y, %I:%M %p}".replace(" 0", " ")
    rep = {"FREQ=DAILY": "every day"}.get(e["rule"]) or (
        f"every {next(k for k, v in DAYS.items() if v == e['rule'][-2:]).title()}"
        if e["rule"] and "WEEKLY" in e["rule"]
        else f"monthly on the {e['rule'].split('=')[-1]}"
        if e["rule"]
        else ""
    )
    return (
        f"'{e['title']}', {when_}"
        + (f", {e['minutes']} min" if not e["all_day"] else "")
        + (f", at {e['where']}" if e.get("where") else "")
        + (f", {rep}" if rep else "")
        + f", reminder {e['reminder']} min before: {one} ({'checked' if ok else 'NOT right'}). "
        "Open it to add it to Outlook, or import it in Google Calendar (Settings > Import)."
    )

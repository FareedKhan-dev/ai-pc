"""Business hub tests with no network and no keys: every connector against canned answers (the exact requests it sends
are checked), the hub chat's preview-and-confirm (nothing outward goes without a yes), read-backs, undo, the briefing,
errors with secrets kept out of them, the encrypted vault, and requests read by rules.

  .venv\\Scripts\\python.exe tests\\integration\\test_hub.py
A few seconds. Live checks with your own keys: ai-pc hub status, then ai-pc hub talk.
"""
import datetime as dt
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from ai_pc.hub.http import FakeTransport, HubError  # noqa: E402
from ai_pc.hub.hubchat import HubChat  # noqa: E402
from ai_pc.hub.hubparse import parse, when  # noqa: E402
from ai_pc.hub.services import connector  # noqa: E402

OUT = ROOT / "out" / "_tests" / "hub"
FAILS = []
NOW = dt.datetime(2026, 10, 5, 10, 0)  # a Monday


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------- canned services
def slack_fake():
    posted = {}

    def post(req):
        posted.update(text=req["body"]["text"], channel=req["body"]["channel"])
        return 200, {"ok": True, "channel": req["body"]["channel"], "ts": "1700000000.000100"}

    def history(req):
        if "latest=" in req["url"]:
            return 200, {"ok": True, "messages": [{"type": "message", "text": posted.get("text"), "ts": "1700000000.000100"}]}
        return 200, {"ok": True, "messages": [{"type": "message", "user": "U1", "text": "Can someone send the Q3 numbers by Friday?", "ts": "1"},
                                             {"type": "message", "user": "U2", "text": "Client meeting moved to 4 pm", "ts": "2"}]}
    return FakeTransport({
        ("POST", "auth.test"): (200, {"ok": True, "user": "ai_pc", "team": "Khan Electronics", "url": "https://khan.slack.com/"}),
        ("GET", "conversations.list"): (200, {"ok": True, "channels": [{"id": "C01GENERAL", "name": "general", "is_member": True},
                                                                     {"id": "C02SALES", "name": "sales", "is_member": True}], "response_metadata": {"next_cursor": ""}}),
        ("GET", "users.list"): (200, {"ok": True, "members": [{"id": "U1", "name": "ali", "real_name": "Ali Raza", "profile": {"email": "ali@khan.pk"}},
                                                             {"id": "U2", "name": "sara", "real_name": "Sara Khan", "profile": {"email": "sara@khan.pk"}}]}),
        ("POST", "conversations.open"): (200, {"ok": True, "channel": {"id": "D0ALI"}}),
        ("POST", "chat.postMessage"): post,
        ("GET", "chat.getPermalink"): (200, {"ok": True, "permalink": "https://khan.slack.com/archives/C01GENERAL/p1700000000000100"}),
        ("GET", "conversations.history"): history,
        ("POST", "chat.delete"): (200, {"ok": True}),
        ("POST", "chat.update"): (200, {"ok": True}),
    })


def telegram_fake():
    return FakeTransport({
        ("POST", "/getMe"): (200, {"ok": True, "result": {"id": 1, "username": "aipc_bot", "first_name": "AI PC"}}),
        ("POST", "/getUpdates"): (200, {"ok": True, "result": [{"update_id": 1, "message": {"chat": {"id": 555, "type": "private"}, "text": "hi",
                                                                                             "from": {"first_name": "Fareed"}, "date": 1}}]}),
        ("POST", "/sendMessage"): lambda r: (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": r["body"]["chat_id"]}, "text": r["body"]["text"]}}),
        ("POST", "/deleteMessage"): (200, {"ok": True, "result": True}),
    })


def trello_fake():
    card = {}

    def create(r):
        card.update(id="CARD1", name=r["body"]["name"], idList=r["body"]["idList"], url="https://trello.com/c/abc")
        return 200, dict(card)
    return FakeTransport({
        ("GET", "members/me/boards"): (200, [{"id": "B1", "name": "Shop Work", "url": "u", "closed": False}]),
        ("GET", "members/me"): (200, {"username": "fareed", "fullName": "Fareed"}),
        ("GET", "boards/B1/lists"): (200, [{"id": "L1", "name": "To Do"}, {"id": "L2", "name": "Doing"}, {"id": "L3", "name": "Done"}]),
        ("GET", "boards/B1/cards"): lambda r: (200, ([{"id": "CARD1", "name": card["name"], "idList": card.get("idList", "L1"), "url": "https://trello.com/c/abc",
                                                       "due": "2026-10-04T12:00:00.000Z", "dueComplete": False}] if card else [])),
        ("POST", "/cards/CARD1/actions/comments"): lambda r: (200, {"id": "ACT1", "data": {"text": r["body"]["text"]}}),
        ("POST", "/cards"): create,
        ("GET", "/cards/CARD1"): lambda r: (200, {"name": card.get("name"), "idList": card.get("idList")}),
        ("PUT", "/cards/CARD1"): lambda r: (card.update(idList=r["body"].get("idList", card.get("idList"))) or 200, {"id": "CARD1"}),
        ("DELETE", "/cards/CARD1"): (200, {}),
    })


def google_fake():
    ev = {}

    def insert(r):
        ev.update(id="EV1", summary=r["body"]["summary"])
        return 200, {"id": "EV1", "summary": r["body"]["summary"], "hangoutLink": "https://meet.google.com/abc-defg-hij", "htmlLink": "h"}
    return FakeTransport({
        ("GET", "users/me/profile"): (200, {"emailAddress": "fareed@gmail.com"}),
        ("GET", "users/me/messages?"): (200, {"messages": [{"id": "M1"}]}),
        ("GET", "users/me/messages/M1"): (200, {"snippet": "Please find the invoice attached", "payload": {"headers": [
            {"name": "From", "value": "Ali <ali@khan.pk>"}, {"name": "Subject", "value": "Invoice 1042"}, {"name": "Date", "value": "Mon"}]}}),
        ("POST", "users/me/drafts/send"): (200, {"id": "SENT1"}),
        ("POST", "users/me/drafts"): (200, {"id": "D1"}),
        ("GET", "users/me/drafts/D1"): (200, {"id": "D1"}),
        ("GET", "users/me/messages/SENT1"): (200, {"labelIds": ["SENT"]}),
        ("GET", "calendars/primary/events/EV1"): lambda r: (200, {"summary": ev.get("summary")}),
        ("GET", "calendars/primary/events"): (200, {"items": [{"id": "E0", "summary": "Supplier call", "start": {"dateTime": "2026-10-05T11:00:00+05:00"}}]}),
        ("POST", "calendars/primary/events"): insert,
        ("DELETE", "calendars/primary/events/EV1"): (204, {}),
    })


def asana_fake():
    return FakeTransport({
        ("GET", "users/me"): (200, {"data": {"gid": "U", "name": "Fareed", "workspaces": [{"gid": "W1", "name": "Khan"}]}}),
        ("GET", "/projects"): (200, {"data": [{"gid": "P1", "name": "Shop"}]}),
        ("POST", "/tasks"): lambda r: (201, {"data": {"gid": "T1", "name": r["body"]["data"]["name"], "permalink_url": "https://app.asana.com/0/1/T1"}}),
        ("GET", "/tasks/T1"): (200, {"data": {"name": "Call the supplier"}}),
        ("GET", "/tasks?"): (200, {"data": [{"gid": "T1", "name": "Call the supplier", "due_on": "2026-10-05", "completed": False}]}),
        ("PUT", "/tasks/T1"): (200, {"data": {"gid": "T1"}}),
        ("DELETE", "/tasks/T1"): (200, {"data": {}}),
    })


def jira_fake():
    return FakeTransport({
        ("GET", "/myself"): (200, {"displayName": "Fareed"}),
        ("GET", "/project/search"): (200, {"values": [{"id": "1", "key": "WEB", "name": "Website"}]}),
        ("POST", "/issue/WEB-7/transitions"): (204, {}),
        ("POST", "/issue"): lambda r: (201, {"id": "1007", "key": "WEB-7"}),
        ("GET", "/issue/WEB-7/transitions"): (200, {"transitions": [{"id": "31", "name": "Done", "to": {"name": "Done"}}]}),
        ("GET", "/issue/WEB-7"): (200, {"fields": {"summary": "Login fails on mobile", "status": {"name": "To Do"}}}),
        ("POST", "/search/jql"): (200, {"issues": [{"key": "WEB-7", "fields": {"summary": "Login fails on mobile", "status": {"name": "To Do"}}}]}),
        ("DELETE", "/issue/WEB-7"): (204, {}),
    })


def hubspot_fake():
    return FakeTransport({
        ("POST", "contacts/search"): (200, {"results": []}),
        ("POST", "crm/v3/objects/contacts"): (201, {"id": "501"}),
        ("GET", "crm/v3/objects/contacts/501"): (200, {"properties": {"email": "sara@khan.pk", "firstname": "Sara"}}),
        ("GET", "crm/v3/objects/contacts?"): (200, {"results": [], "total": 0}),
        ("DELETE", "crm/v3/objects/contacts/501"): (204, {}),
    })


def whatsapp_fake():
    return FakeTransport({("POST", "/messages"): (200, {"messages": [{"id": "wamid.X"}]}),
                          ("GET", "PNID"): (200, {"display_phone_number": "+1 555 0100", "verified_name": "Test Number"})})


CREDS = {"slack": {"bot_token": "xoxb-SECRET-SLACK-TOKEN"}, "telegram": {"bot_token": "123:SECRET-TELEGRAM"}, "trello": {"key": "TRELLOKEY123", "token": "TRELLOTOKEN456"},
         "google": {"access_token": "ya29.SECRET"}, "asana": {"token": "ASANA-SECRET-TOKEN"}, "jira": {"site": "khan.atlassian.net", "email": "f@k.pk", "token": "JIRASECRET1"},
         "hubspot": {"token": "pat-SECRET-HUBSPOT"}, "whatsapp": {"token": "EAA-SECRET", "phone_number_id": "PNID"}}


def fakes():
    return {"slack": slack_fake(), "telegram": telegram_fake(), "trello": trello_fake(), "google": google_fake(), "asana": asana_fake(), "jira": jira_fake(),
            "hubspot": hubspot_fake(), "whatsapp": whatsapp_fake()}


# ---------------------------------------------------------------- connectors
def connectors():
    tr = fakes()
    s = connector("slack", CREDS["slack"], tr["slack"])
    check("slack: who am I", s.whoami()["where"] == "Khan Electronics")
    r = s.post("#general", "Meeting moved to 4 pm")
    req = next(x for x in tr["slack"].sent if "chat.postMessage" in x["url"])
    check("slack: posts to the channel's id with the text, read back from history", req["body"] == {"channel": "C01GENERAL", "text": "Meeting moved to 4 pm"}
          and r["verified"] and r["link"].startswith("https://"), str(req["body"]))
    check("slack: the token goes in a header, never in the address", all("xoxb" not in x["url"] for x in tr["slack"].sent) and
          req["headers"]["Authorization"] == "Bearer xoxb-SECRET-SLACK-TOKEN")
    s.post("@ali", "Please send the Q3 numbers")
    check("slack: '@ali' opens a direct message", any("conversations.open" in x["url"] and x["body"] == {"users": "U1"} for x in tr["slack"].sent))
    rd = s.read("#sales")
    check("slack: reading a channel names the people", rd["messages"][0]["who"] in ("Ali Raza", "Sara Khan") and len(rd["messages"]) == 2)
    bad = FakeTransport({("POST", "chat.postMessage"): (200, {"ok": False, "error": "not_in_channel"}), ("GET", "conversations.list"):
                         (200, {"ok": True, "channels": [{"id": "C9", "name": "private-room"}], "response_metadata": {}})})
    try:
        connector("slack", CREDS["slack"], bad).post("#private-room", "x")
        check("slack: an 'ok: false' answer becomes an error", False)
    except HubError as e:
        check("slack: an 'ok: false' answer becomes an error naming it", "not_in_channel" in str(e), str(e))
    t = connector("telegram", CREDS["telegram"], tr["telegram"])
    r = t.send("Stock count done")
    check("telegram: learns your chat from your first message, sends, reads back", r["chat"] == 555 and r["verified"])
    tl = connector("trello", CREDS["trello"], tr["trello"])
    r = tl.create("Fix the AC", "To Do")
    req = next(x for x in tr["trello"].sent if x["method"] == "POST" and x["url"].endswith("/cards"))
    check("trello: a card in the named list, read back", req["body"]["idList"] == "L1" and req["body"]["name"] == "Fix the AC" and r["verified"])
    check("trello: key and token in the OAuth header, not the address", all("TRELLOTOKEN456" not in x["url"] for x in tr["trello"].sent) and
          'oauth_token="TRELLOTOKEN456"' in req["headers"]["Authorization"])
    r = tl.move("Fix the AC", "Done")
    check("trello: move a card by name to a list, checked", r["verified"] and r["where"] == "To Do -> Done", r["where"])
    g = connector("google", CREDS["google"], tr["google"])
    r = g.draft(["ali@khan.pk"], "Invoice 1042", "It is paid.")
    req = next(x for x in tr["google"].sent if x["url"].endswith("users/me/drafts") and x["method"] == "POST")
    import base64
    mime = base64.urlsafe_b64decode(req["body"]["message"]["raw"]).decode()
    check("gmail: a real MIME draft (to, subject, body), read back", "To: ali@khan.pk" in mime and "Subject: Invoice 1042" in mime and "It is paid." in mime
          and r["verified"])
    r = g.create_event("Budget review", dt.datetime(2026, 10, 6, 15, 0), dt.datetime(2026, 10, 6, 15, 30), attendees=["ali@khan.pk"])
    req = next(x for x in tr["google"].sent if x["method"] == "POST" and x["url"].split("?")[0].endswith("calendars/primary/events"))
    check("calendar: event with a Meet link and invites sent, read back", "conferenceData" in req["body"] and "sendUpdates=all" in req["url"]
          and req["body"]["attendees"] == [{"email": "ali@khan.pk"}] and r["verified"] and "meet.google.com" in r["link"])
    a = connector("asana", CREDS["asana"], tr["asana"])
    r = a.create("Call the supplier", due="2026-10-09")
    req = next(x for x in tr["asana"].sent if x["method"] == "POST")
    check("asana: task in your workspace, assigned to you, due date, read back", req["body"]["data"]["workspace"] == "W1" and
          req["body"]["data"]["assignee"] == "me" and req["body"]["data"]["due_on"] == "2026-10-09" and r["verified"])
    j = connector("jira", CREDS["jira"], tr["jira"])
    r = j.create("Login fails on mobile", "WEB", "Bug", "Steps:\nopen app\nlog in")
    req = next(x for x in tr["jira"].sent if x["method"] == "POST" and x["url"].endswith("/issue"))
    check("jira: issue in the project with an ADF description, link to it", req["body"]["fields"]["project"] == {"key": "WEB"} and
          req["body"]["fields"]["description"]["type"] == "doc" and r["url"] == "https://khan.atlassian.net/browse/WEB-7" and r["verified"])
    check("jira: basic auth in a header (email:token), not the address", all("JIRASECRET1" not in x["url"] for x in tr["jira"].sent) and
          req["headers"]["Authorization"].startswith("Basic "))
    h = connector("hubspot", CREDS["hubspot"], tr["hubspot"])
    r = h.add_contact("sara@khan.pk", "Sara", "Khan", "0300-1234567", "Khan Electronics")
    check("hubspot: contact added after checking it is not there already, read back", r["verified"] and any("contacts/search" in x["url"] for x in tr["hubspot"].sent))
    w = connector("whatsapp", CREDS["whatsapp"], tr["whatsapp"])
    w.send("0300-1234567", "Your order is ready")
    req = next(x for x in tr["whatsapp"].sent if x["url"].endswith("/messages"))
    check("whatsapp: a Pakistani number to international form (923...)", req["body"]["to"] == "923001234567" and req["body"]["text"]["body"] == "Your order is ready")


# ---------------------------------------------------------------- the chat
def chat():
    tr = fakes()
    hc = HubChat.start(chats_dir=OUT, transports=tr, creds=CREDS)
    r = hc.say("post 'Meeting moved to 4 pm' to #general")
    check("chat: a post waits for a yes (nothing sent yet)", "Ready to post" in r and not any("chat.postMessage" in x["url"] for x in tr["slack"].sent), r)
    r = hc.say("yes")
    check("chat: 'yes' posts it, read back, with its link", "Posted to #general (checked)" in r and "https://" in r, r)
    r = hc.say("post 'Lunch is on me' to #general")
    r = hc.say("no")
    check("chat: 'no' drops it and nothing is sent", "nothing was sent" in r and sum("chat.postMessage" in x["url"] for x in tr["slack"].sent) == 1, r)
    hc.say("post 'Shop opens at 9' to #general")
    r = hc.say("change the text to Shop opens at 10")
    check("chat: the draft can be changed before the yes", "Shop opens at 10" in r and hc.state["pending"]["text"] == "Shop opens at 10", r)
    hc.say("yes")
    r = hc.say("undo")
    check("chat: undo deletes the bot's own last post", "Undone" in r and any("chat.delete" in x["url"] for x in tr["slack"].sent), r)
    r = hc.say("send me a telegram: stock count done")
    check("chat: a message to yourself goes without asking", "Posted to Telegram" in r, r)
    r = hc.say("draft an email to ali@khan.pk about invoice 1042 saying it has been paid in full")
    check("chat: an email is saved as a draft first and shown", "Draft saved in Gmail drafts" in r and "it has been paid in full" in r and
          hc.state["pending"]["op"] == "send_draft", r)
    r = hc.say("send")
    check("chat: 'send' sends the draft, checked in Sent", "Sent the email to ali@khan.pk (checked)" in r, r)
    r = hc.say("schedule a meeting with ali@khan.pk tomorrow at 3 pm about budget review for 45 minutes")
    check("chat: a meeting with invites waits for a yes", "Ready to book" in r and "ali@khan.pk" in r, r)
    r = hc.say("yes")
    check("chat: booked with its Meet link", "Booked" in r and "meet.google.com" in r, r)
    r = hc.say("add a trello card 'Fix the AC' to To Do")
    hc.say("yes")
    r = hc.say("move 'Fix the AC' to Done")
    r2 = hc.say("yes")
    check("chat: a trello card added then moved, each after a yes", "Moved" in r2 and "To Do -> Done" in r2, r2)
    r = hc.say("add a task 'Call the supplier' due friday in asana")
    check("chat: an asana task with the due date read from 'friday'", "due 2026-10" in r and "Ready to add" in r, r)
    hc.say("yes")
    r = hc.say("check my email")
    check("chat: reading the inbox needs no yes", "1 unread in Gmail" in r and "Invoice 1042" in r, r)
    r = hc.say("what's new in #sales?")
    check("chat: reading a channel (offline: listed, not summed up)", "#sales" in r and "Q3 numbers" in r, r)
    r = hc.say("brief me")
    check("chat: the briefing gathers calendar, mail, Slack and late cards", "Calendar" in r and "Unread mail: 1" in r and "Slack (last 24 h)" in r
          and "Trello due or late" in r, r)
    r = hc.say("what did you do today?")
    check("chat: the day's log lists what was done", "post" in r and "send_draft" in r, r)
    r = hc.say("create a zoom meeting tomorrow at 4 pm 'Weekly sync'")
    check("chat: a service that is not connected says how to connect it", "not connected" in r and "ai-pc hub connect zoom" in r, r)
    r = hc.say("send 'hi' on whatsapp to 0300-1234567")
    check("chat: whatsapp waits for a yes too", "Ready to post to 0300-1234567 on WhatsApp" in r, r)


def secrets():
    from ai_pc.core import vault as V
    old = V.FILE
    V.FILE = OUT / "vault_test.bin"
    try:
        V.put("slack", {"bot_token": "xoxb-ROUNDTRIP-123456"})
        raw = V.FILE.read_bytes()
        check("vault: the key is not readable in the file (DPAPI)", b"xoxb" not in raw and b"ROUNDTRIP" not in raw)
        check("vault: and comes back for this Windows user", V.get("slack") == {"bot_token": "xoxb-ROUNDTRIP-123456"})
        check("vault: errors are scrubbed of stored keys", V.redact("failed with xoxb-ROUNDTRIP-123456 in it") == "failed with *** in it")
        V.remove("slack")
        check("vault: forget removes the key", V.get("slack") is None)
    finally:
        V.FILE = old


PHRASES = [
    ("post 'Meeting moved to 4 pm' to #general", lambda o: o[0] == {"op": "post", "service": "slack", "to": "#general", "text": "Meeting moved to 4 pm"}),
    ("message @ali on slack: please send the Q3 numbers", lambda o: o[0]["to"] == "@ali" and o[0]["text"] == "please send the Q3 numbers"),
    ("send me a telegram: stock count done", lambda o: o[0]["service"] == "telegram" and o[0]["to"] == "me"),
    ("whatsapp 0300-1234567 saying your order is ready", lambda o: o[0]["service"] == "whatsapp" and o[0]["to"] == "0300-1234567"),
    ("what's new in #sales?", lambda o: o[0]["op"] == "read" and o[0]["where"] == "#sales" and o[0]["summarize"]),
    ("check my email", lambda o: o[0]["op"] == "inbox"),
    ("draft an email to ali@khan.pk about the invoice saying it is paid", lambda o: o[0]["op"] == "email" and o[0]["to"] == ["ali@khan.pk"]
     and o[0]["subject"] == "Invoice" and o[0]["body"] == "it is paid"),
    ("what's on my calendar tomorrow?", lambda o: o[0] == {"op": "events", "service": "google", "day": "2026-10-06"}),
    ("schedule a meeting with ali@khan.pk friday at 3:30 pm about pricing", lambda o: o[0]["start"] == "2026-10-09T15:30:00" and o[0]["title"] == "pricing"
     and o[0]["with"] == ["ali@khan.pk"]),
    ("add a trello card 'Fix the AC' to To Do", lambda o: o[0]["op"] == "task" and o[0]["service"] == "trello" and o[0]["title"] == "Fix the AC" and o[0]["where"] == "To Do"),
    ("create a jira bug 'Login fails' in WEB", lambda o: o[0]["service"] == "jira" and o[0]["kind"] == "Bug" and o[0]["where"] == "WEB"),
    ("move 'Fix the AC' to Done", lambda o: o[0] == {"op": "move", "service": "trello", "item": "Fix the AC", "to": "Done"}),
    ("mark 'Call the supplier' as done", lambda o: o[0]["op"] == "done" and o[0]["item"] == "Call the supplier"),
    ("add Sara Khan sara@khan.pk 0300-1234567 to hubspot", lambda o: o[0]["op"] == "contact" and o[0]["first"] == "Sara" and o[0]["email"] == "sara@khan.pk"),
    ("upload report.pdf to drive and share it with ali@khan.pk", lambda o: o[0]["op"] == "upload" and o[0]["share_with"] == ["ali@khan.pk"]),
    ("brief me and send it to my telegram", lambda o: o[0] == {"op": "brief", "send_to": "telegram"}),
    ("undo", lambda o: o[0] == {"op": "undo"}),
    ("what did you do today?", lambda o: o[0] == {"op": "log"}),
]


def phrases():
    ctx = {"services": ["slack", "telegram", "google", "trello", "jira", "asana", "hubspot", "whatsapp"], "files": {}, "now": NOW}
    for text, ok in PHRASES:
        r = parse(text, ctx)
        try:
            good = bool(r["ops"]) and ok(r["ops"])
        except (KeyError, IndexError, TypeError):
            good = False
        check(f"reads: {text}", good, str(r)[:220])
    d, t = when("next monday at 11 am", NOW)
    check("times: 'next monday at 11 am' from a Monday is a week ahead", d == dt.date(2026, 10, 12) and t == dt.time(11, 0), f"{d} {t}")


if __name__ == "__main__":
    import ai_pc.hub.hubchat as HC
    HC._now = lambda: NOW
    t0 = time.perf_counter()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    connectors()
    chat()
    secrets()
    phrases()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.1f} s)")
    sys.exit(1 if FAILS else 0)

# Business hub: work apps

## Business hub: Slack, Teams, Outlook, Gmail, Trello, Notion, Jira and more (official APIs)

```
ai-pc hub steps                 how to make each free key (ai-pc hub steps slack for one)
ai-pc hub connect slack         you paste the key at a hidden prompt; it is checked with Slack at once
ai-pc hub status                what is connected, checked live
ai-pc hub talk -m "what's new in #sales?" -m "post 'Meeting moved to 4 pm' to #general" -m "yes"
ai-pc hub talk -m "draft an email to ali@khan.pk about invoice 1042 saying it has been paid" -m "send"
ai-pc hub talk -m "schedule a meeting with ali@khan.pk tomorrow at 3 pm about the budget" -m "yes" -m "brief me"
```

Every service is driven through its official API: no desktop app is clicked and no web page is scraped. Keys are
typed by you at a hidden prompt and stored encrypted with Windows DPAPI in `state/hub/vault.bin`, so only this
Windows user can read them. They are kept out of addresses and logs, scrubbed from error messages, and never sent to
the language model. Google signs in once in your browser, through a loopback page on 127.0.0.1 with PKCE. Microsoft
signs in with a device code.

| Service | What it can do |
|---|---|
| Slack | Post (to a channel, a person, a thread, or later), read a channel, edit, delete, upload a file, react. Every post is read back from the channel's history. |
| Microsoft 365 | Outlook mail (unread, draft, send), Outlook calendar (events; new events with a Teams link on work accounts), OneDrive (upload, share link), Teams channel posts (work or school accounts). |
| Google | Gmail (unread, a MIME draft with attachments, send, checked in Sent), Calendar (events; new events with a Meet link and invites), Drive (upload, share), Sheets (create, read, append, write). |
| Trello, Asana, Notion, Jira | Cards, tasks and issues: add (with due dates), move through lists or workflows, complete, comment, list what is open or due. |
| HubSpot | Contacts (checked for duplicates first), deals, updates. |
| Zoom | Upcoming meetings, and new ones with join links. |
| Telegram | Messages and files to you: alerts and briefings on your phone. |
| WhatsApp Business | Texts and approved templates through the Cloud API's free test number. A personal WhatsApp account has no API. |
| Figma, Canva | See [Designs to code](design-to-code.md): frames, colours, exports and comments; designs, imports, exports and uploads. |

How it behaves:
- Reads run at once: a channel, your inbox, your calendar, your tasks.
- Anything other people will see waits for your yes: a post, an email, an invite, a shared task, a CRM record, a shared file. The preview says exactly what will go where. "Change the text to ..." edits the draft; "no" drops it.
- Emails are drafts first: "Send" sends the draft.
- Every action is read back from the service, written to `state/hub/audit.jsonl`, and can be undone where the service allows it: a post deleted, a card moved back, a task reopened, an event deleted. Sent emails and WhatsApp messages cannot be unsent, and the reply says so.
- "Brief me" gathers today's calendar, unread mail, the last 24 hours of the Slack channels the bot is in, and late cards and tasks. The cheap model sums up what needs you, and the briefing can go to your Telegram. This sends message text to the model provider; use `--offline` to keep it on the PC.

Measured (2026-10-04): [tests/integration/test_hub.py](../../tests/integration/test_hub.py) runs with no network and no keys, against canned answers for 8 services, in 0.2 s, and passes 58/58. It covers:
- the exact requests sent, with secrets never in addresses;
- nothing outward without a yes, and "no" sends nothing;
- drafts then sends, read-backs, undo, the briefing and a day's log;
- vault encryption and scrubbing;
- 18 phrasings.

Live tests need your keys.

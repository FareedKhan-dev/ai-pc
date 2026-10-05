# 0003. Read requests by rules first; a low-cost model only when the rules cannot tell

- Status: accepted
- Date: 2026-10-02

## Context

Most requests are routine ("make it brighter", "send it to Slack #team", "compress this pdf"). A language model call
adds seconds and cost to each, its availability varies, and the provider's slowest answers take tens of seconds.

## Decision

Every program reads requests with its own rules first (`*parse.py` modules, each app module's `parse()`), and the one
chat routes by rules (words, file kinds, the conversation in progress). A model is asked only when the rules cannot
tell, for open-ended writing and planning, and for vision checks. Every role uses the cheapest model on the account
that also reads images (GLM-5.3-Flash on Nebius, reasoning effort low); slow calls are hedged with a second request.

## Consequences

- Routine requests are instant, free, and work when the model provider is down; the chat says plainly when a request
  needs the model and it is not answering.
- Rules need tests: every phrasing they cover is in a unit or integration suite.
- New kinds of requests need new rules, or fall back to the model.

# Architecture decision records

Short records of the decisions that shape AI PC: the context, the decision, and what follows from it. A new decision
gets the next number; a reversed one is marked superseded, not deleted.

| # | Decision | Status |
|---|---|---|
| [0001](0001-everything-in-the-project-folder.md) | Keep programs, models and data inside the project folder; verify every download | Accepted |
| [0002](0002-drive-programs-by-code.md) | Drive programs through their files and official interfaces, not the screen | Accepted |
| [0003](0003-rules-first-cheap-model.md) | Read requests by rules first; a low-cost model only when the rules cannot tell | Accepted |
| [0004](0004-one-package-one-command.md) | One installable package (`src/ai_pc`) and one command (`ai-pc`) | Accepted |
| [0005](0005-any-openai-compatible-provider.md) | Any OpenAI-compatible model provider, chosen by the user; Nebius stays the default | Accepted |

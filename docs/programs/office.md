# Word, PowerPoint, Excel and PDF

## Office documents: Word, PowerPoint, Excel (programmatic)

The CapCut recipe applied to Office. Code writes the `.docx`, `.pptx` and `.xlsx` files itself (python-docx, python-pptx, openpyxl). The real Office app only renders them, hidden in the background, the way JianYing only exported videos. Every element is then checked on what the app produced.

```
ai-pc office new "a 5 page report on rooftop solar for homes in Lahore with a cost table and a chart, for Green Future Consulting"
ai-pc office new "Assignment: 4 pages on the causes of inflation in Pakistan, ECON-201, submitted to Dr. Sana Malik, by Ahmed Raza"
ai-pc office new "leave application to my principal for 3 days, fever, Fatima Noor class 9-B"
ai-pc office new "invoice for Ali Traders: logo design 1 x Rs 25,000, 10 posts at Rs 2,500, add 18% sales tax"
ai-pc office new "a 10 slide presentation for homeowners on going solar"            (PowerPoint)
ai-pc office new "marks sheet in Excel for 8 students with totals, grades and a class summary"   (Excel)
ai-pc office new "..." --files media\docs\data.xlsx notes.txt   --theme academic   --pages 6
ai-pc office check some.docx                                                        (render and check any Word document)
```

| Step | Video (JianYing) | Documents (Office) |
|---|---|---|
| Write | the director plans the edit | [designer.py](../../src/ai_pc/office/designer.py): an outline, then all sections in parallel (Word); one call for a deck or a workbook |
| Build | pyJianYingDraft writes the draft | [docx_build.py](../../src/ai_pc/office/docx_build.py), [pptx_build.py](../../src/ai_pc/office/pptx_build.py), [xlsx_build.py](../../src/ai_pc/office/xlsx_build.py) |
| Render | JianYing exports in the background | [render.py](../../src/ai_pc/office/render.py): Word, PowerPoint or Excel by COM in a child process, in a new instance of its own (open documents are never touched; a stuck one is stopped) |
| Check | frames at every edit point | [verify.py](../../src/ai_pc/office/verify.py): every element on the rendered pages |
| Fix | fix rounds | length, a heading alone at a page's foot, an almost-empty last page, a table too wide, slide text overflowing |

What code guarantees (never left to the model):
- Invoice and table totals are computed by code.
- Spreadsheet formulas are written by code. The model names columns (`[Qty] * [Price]`) and code writes `=B2*C2`, SUMIFS summaries and totals.
- Table and figure numbering, academic heading numbers (1, 1.1), and restarted numbered lists.
- Words per page come from the theme (Times 12 pt at 1.5 lines holds about 270, Calibri 11 pt about 420).

Professional defaults:
- real Word styles, so the navigation pane and contents page work;
- headings kept with their text;
- table header rows repeated on every page, numbers right-aligned, rows never split;
- native, editable charts in Word as well, by attaching python-pptx's chart XML to the document;
- covers and contents pages for long work, and "Page X of Y" footers;
- letters, applications, CVs, invoices, notices and certificates laid out the way they are expected to look;
- slides drawn on blank 16:9 pages with text sized to fit and message-style titles;
- workbooks with frozen headers, filters, dropdowns, highlights, summaries and charts.

What is checked:

| Format | Checks |
|---|---|
| Word | pages against the length asked (the cover and contents page are not counted); page size; blank pages; every glyph in the theme's fonts, read per character from the PDF; no field errors; contents page numbers equal the headings' real pages; no heading alone at a page's foot; tables inside the margins with the header repeated; charts drawn; every paragraph present; the client's figures on the pages |
| PowerPoint | PowerPoint's own measurement of every text box after layout (overflow); every title and bullet on its slide; charts drawn; fonts |
| Excel | Excel recalculates the workbook; no error cells; every total, metric and group Excel computes equals the same number computed in Python; charts present |
| All | one cheap vision look at the pages or slides, on a time budget, so a slow model never holds up a run |

Measured (2026-10-03, GLM-5.3-Flash for all model calls):

| Run | Result |
|---|---|
| Offline engine tests (`tests/integration/test_docs.py`, no model) | 23/23: totals, a 70-row table repeating its header, contents page numbers, native charts, list numbering, fonts, academic numbering, one-page fitting, deck rendering and overflow, Excel formulas and values |
| 5-page solar report (cover, contents, table, chart) | 5 body pages for 5 asked; 14/14 checks; the vision look found no problems; about 45 s; $0.009 |
| University assignment, leave application, invoice, CV, notice | 63 s, 12 s, 11 s, 13 s, 16 s; $0.0004-0.005 each. The invoice arithmetic was exact. A CV that spilled onto a second page is now tightened onto one |
| 10-slide deck from one request | 22 s; 11/11 slide checks; $0.0018 |
| Excel sales workbook | 15/15 values Excel computed equal Python's; no error cells; 2 charts |

The renders take 6-8 s each, mostly Word or PowerPoint starting. Writing takes 2 s for a letter, about 10 s for a deck and about 20 s for a long report. Model latency spikes happen (one reply took 86 s on 2026-10-03), so the vision look runs on a time budget.

### Editing existing files by conversation

```
ai-pc office talk report.docx                                   (interactive)
ai-pc office talk deck.pptx -m "delete slide 4, move slide 9 to the start and make the titles dark blue"
ai-pc office talk sales.xlsx -m "clean up the data" -m "add a column Amount = Qty x Unit Price and a total row" -m "which customer bought the most?" -m export
ai-pc office talk --chat book_sales_163841                      (continue a saved chat)
```

Each message makes one version; v0 is a copy of the client's file, which is never changed. Undo, redo, "go back to v2", "compare v0 with the current version", "what did you change?" and "export" (the file plus a PDF) work the same way in all three.

| Step | Word | PowerPoint | Excel |
|---|---|---|---|
| Read the file | [docmap.py](../../src/ai_pc/office/docmap.py): sections, headings (also bold lines that only look like headings), tables, contents page, header and footer | [pptx_ops.py](../../src/ai_pc/office/pptx_ops.py): slides, titles, texts, notes, charts, tables, which slide is the cover | [xlsx_map.py](../../src/ai_pc/office/xlsx_map.py): each sheet's table (header row, data rows, totals row, column kinds and formulas), summaries, pivots, charts |
| Understand | [doc_parse.py](../../src/ai_pc/office/doc_parse.py): rules first, including some Roman Urdu | [deckchat.py](../../src/ai_pc/office/deckchat.py) | [book_parse.py](../../src/ai_pc/office/book_parse.py): rules first; data questions become queries that code computes |
| The model | only for what the rules cannot read; it returns the same operations, which are validated against the file | same | same; for a question it may only return a query, never do the arithmetic |
| Edit | python-docx in place (parts it does not know are kept) | python-pptx in place (masters, layouts and animations are kept) | [xlsx_com.py](../../src/ai_pc/office/xlsx_com.py): Excel itself, in the background worker. Charts, pivots, validation and highlights are kept, and references follow moved rows and columns |
| Check | each edit on the document before and after; Word renders it; fonts drawn, contents page filled, page numbers on the pages | PowerPoint measures the changed slides. Text too big for its box is shrunk by that measure and measured again, up to three rounds; a number goes onto one line and is sized by its width rather than breaking. Text contrast is checked against what is behind it | each result against Python: a new column's values, a sort's order, the rows a filter shows, the cells Excel paints (DisplayFormat), totals, summary and pivot groups; no new error cells |

Edits it understands (examples):
- Word (29 operations): styles and themes; page setup and page numbers; header and footer; contents page and cover; heading numbers; lists; find and replace across formatted runs; bolding the key terms; deleting or moving sections; inserting sections the model writes in the document's own style; rewriting, shortening or translating (Urdu is set right to left); summaries; table sort, rows, columns, formulas and totals; native charts; images.
- PowerPoint (15): slides:
  - delete, move, swap or duplicate a slide;
  - add a slide about a topic (the model writes it; it is drawn in the deck's own look).

  Text:
  - set titles;
  - replace words across slides, tables and notes;
  - rewrite, shorten or translate;
  - write speaker notes, also "only for the slides that have none";
  - add or delete bullets.

  Look:
  - styles for titles, body text or table text;
  - backgrounds (text that would no longer read is recoloured; cards and charts follow);
  - shrink text to fit, by PowerPoint's own measurement.
- Excel (32): clean-up:
  - "clean up the data" in one request: dates typed as text in any style, prices written as "Rs 42,000", one city spelled four ways, extra spaces, empty rows, repeated rows.

  Formula columns from words:
  - "Qty times Unit Price", "17% of Amount", "Big if Amount is above 5 lakh else Small", "average of Maths, English, Science and Urdu";
  - running totals, ranks, share of the total;
  - lookups from another sheet (INDEX/MATCH).

  Sorting, filtering and highlights:
  - sort and filter;
  - highlights by value, top N, duplicates, whole rows, or any condition ("overdue and unpaid");
  - data bars and colour scales.

  Summaries and charts:
  - totals rows;
  - live summary sheets (SUMIFS; by month, quarter or year);
  - real pivot tables;
  - charts in the workbook's own colours (a chart of a column whose values repeat totals it first).

  Structure and formats:
  - number formats (Rs, %, dates);
  - freeze panes, dropdowns, hiding, renaming, moving and splitting columns;
  - sheets.

Guard rails:
- Excel will not delete a column or sheet that other formulas use. It names those cells, and deletes only on "… anyway", keeping those cells as their current values.
- Slide numbers in one message mean the deck as the client saw it, even after earlier deletions and moves in the same message.
- A colour request that makes text unreadable is done but flagged ("hard to read: … on slide 7").
- New decks are drawn readable too: a theme colour on a card, a step circle or a section panel is darkened just enough to reach 3:1 contrast, keeping its hue. The deck check now flags any text under 3:1.
- A sheet that an edit made wider than a page is set to print landscape, one page wide.
- "Which customer bought the most?" on a sheet with quantities and unit prices but no amount column is answered from Qty × Unit Price, never from a sum of prices.

Measured (2026-10-03, GLM-5.3-Flash):

| Suite | Turns OK | Requests the model had to read | Time per turn | Model cost |
|---|---|---|---|---|
| Word chats ([tests/integration/doc_conversations.py](../../tests/integration/doc_conversations.py): a report, an assignment, a hand-typed messy essay) | 38/38 | 1 | 2.5 s | $0.0023 |
| PowerPoint chats ([tests/integration/deck_conversations.py](../../tests/integration/deck_conversations.py): the agent's deck, a client deck in PowerPoint's default template) | 36/36 | 1 | 2.1 s | $0.0009 |
| Excel chats ([tests/integration/book_conversations.py](../../tests/integration/book_conversations.py): a messy client sales workbook, the class marks workbook) | 33/33 | 2 | 1.3 s | $0.0006 |
| Excel operations alone on the messy workbook (one Excel job each) | 30/30, every result equal to Python's | none | 0.5-3.6 s | none |

### Projects: several files together, data flowing between them

```
ai-pc office project sales.xlsx -m "clean up the data and add a column Amount = Qty x Unit Price with a total row"
   -m "write a two page report on Q1 sales for the management team from the workbook"
   -m "put the amount by city into the report after the introduction, with a pie chart of it"
   -m "make a 5 slide deck from the report for the board"
   -m "in the workbook, delete the cancelled orders"          (the reply names the copies now out of date)
   -m "refresh everything"
   -m "export the report and the deck as one pdf with a cover called Q1 Sales Pack, page numbers and a DRAFT watermark"
ai-pc office project --load proj_q1sales_172815                   (continue a saved project)
```

[projectchat.py](../../src/ai_pc/office/projectchat.py) keeps a chat per file and adds what spans files:

| Piece | What it does |
|---|---|
| Routing | Each part of a message goes to the file it is about. A file can be named ("in the workbook", "the deck's titles") or recognised by its own words: sheets, columns and the data's values; section titles; slide titles. Otherwise it goes to the file last talked about. "in the workbook," on its own steers the requests after it. |
| Data links | Excel hands over a table or a pivot exactly as it shows it. Pivots are refreshed first, and narrow columns widened so no "####" is read. It goes into Word as a native table or chart, or into PowerPoint as a native chart or table slide, with an invisible link back: a Word bookmark or a PowerPoint shape tag. If no sheet holds the figures asked for ("amount by city and month"), a pivot is made in the workbook first. |
| Out of date | After a workbook edit that changes the data, the reply names each copy that is now out of date. It also names each figure a report or deck quotes in its text ("the text says 5,634,700 for total Amount, now 5,142,700"); a report keeps the list of figures it was written from, and a deck made from it inherits that list. "refresh" writes the tables and charts again in place and replaces the old figures in the text. Caption, numbering and chart type are kept; a slide table with a different number of rows is redrawn with its title and notes. Each cell is checked against Excel. |
| Made from other files | A report written from the workbook's figures: computed by code and quoted exactly, with no model arithmetic. A deck made from a report: its charts are drawn again from the workbook, not retyped. A handout: PowerPoint draws each slide, with its speaker notes under it. |
| PDFs | A pack with a cover (drawn by Word), bookmarks and a watermark (a transparent layer drawn by PowerPoint). "Page i of N" goes where each page has room, never over the page's own footer or slide number. Also compress, split by bookmarks, and select, delete or rotate pages. Every result is checked on the PDF; the watermark is checked by rendering the pages. |
| History | One history for the whole project: undo, redo and "go back to v2" move every file together. Files made later are set aside, not deleted. |

Measured (2026-10-03, GLM-5.3-Flash):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_links.py](../../tests/integration/test_links.py): the Excel grab, linked Word tables and charts, PowerPoint data slides and copies, PDF pack, compress, split and pages (no model) | 24/24 | about a minute | none |
| [tests/integration/project_conversations.py](../../tests/integration/project_conversations.py): a messy workbook, then a report, a deck, links, a change, a refresh, a PDF pack and a handout, with undo and go back (19 turns) | 19/19 | 100 s in all; about 30 s each to write the report and the deck | $0.005 |

Problems these tests found and fixed along the way (all would have hit real clients):
- After a slide was deleted, python-pptx gave a new slide the name of a slide still there. The two parts with one name made files PowerPoint could not open.
- Inserted sections were tracked by recycled object ids, which could leave them at the end of the document.
- Excel reports "####" as the text of a number whose column is too narrow.
- A duplicated chart slide lost its colours and labels.
- Word moves the body font into the document defaults when it refreshes a contents page.

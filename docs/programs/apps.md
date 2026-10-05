# Many programs, a basic setup each

## Many programs, a basic setup each (programmatic)

```
ai-pc apps talk --with receipt.jpg -m "what is the total on receipt.jpg?"
ai-pc apps talk -m "which apps can be updated?" -m "update vlc" -m "yes"
ai-pc apps talk -m "flowchart: Start -> Take order -> In stock? -yes-> Pack -> End; In stock? -no-> Order -> Pack"
ai-pc apps talk -m "cite 10.1038/nature14539 and isbn 9780262035613 in apa"
ai-pc apps list
```

| Program | Driven by | What it does |
|---|---|---|
| Text from pictures (OCR) | Windows' own OCR engine (Windows.Media.Ocr), no install | Pictures and scanned PDFs to text or Word; receipt total, date, NTN, phone picked out |
| PC care | winget, psutil, Defender cmdlets, netsh | Apps to update, install, update, remove (shown first, done on yes); disk space; antivirus status and quick scan; Wi-Fi; battery |
| Diagrams | own layout, SVG, headless Chrome | Flowcharts (decisions, loops, arrows in their own lanes), org charts, mind maps as PNG, PDF, SVG and an editable draw.io file |
| References | Crossref (DOI) and Open Library (ISBN), free | APA 7, MLA 9, Harvard, IEEE, Chicago in Word (hanging indent, italics) plus BibTeX and RIS |
| Quizzes | own writers | Moodle XML, GIFT, Kahoot sheet, printable paper and answer key |
| Ebooks | own EPUB 3 writer | Word, Markdown or text to EPUB with chapters, contents, cover |
| Music and video | ffprobe, VLC | Playlists (.m3u8, .xspf) in natural order or shuffled, with total length; played in VLC |
| Printing | pywin32 (GDI), Office in the background | Printers and queues; PDFs, pictures and Office files printed fitted to the page (shown first) |
| Maps | OpenStreetMap Nominatim, free | Places to KML, GPX, GeoJSON; distances; a Google Maps route link |
| Notes and to-dos | Markdown files (Obsidian-compatible) | Quick notes, to-dos in today's note, tasks across notes ticked off, search |
| Databases | DAO (Access's own engine, no window), SQLite | Excel/CSV to Access .accdb or SQLite, one table per sheet; read-only SQL questions answered to Excel |
| Backups and zips | zipfile + SHA-256 | Dated backups with a manifest, verified file by file; damage caught; safe unzip (no zip-slip) |
| Contact cards | vCard 3.0 | From words or an Excel list, numbers in +92 form, a QR of the card |
| QR codes and barcodes | segno, own Code 128 and EAN-13 | Links, Wi-Fi and text QR codes read back by a QR reader; barcodes decoded back from their bars; A4 label sheets |
| Music | own MIDI and MusicXML writers | Melodies in letters to MIDI (any player) and sheet music (MuseScore), read back note by note |
| Calendar | .ics (Asia/Karachi) | Meetings and reminders from words, with length, place, repeats and an alarm; Outlook and Google Calendar import them |
| Shopify | Admin GraphQL 2026-10; Dev Dashboard app, 24-hour client-credentials token | Products, add (SKU checked first), price and stock by SKU (idempotency key), new orders, fulfil with tracking |
| WooCommerce | REST v3 over HTTPS, consumer key/secret | Same, variations included; shipping = a customer note with the tracking, then completed |
| Daraz | Open Platform, every call signed (HMAC-SHA256) | Products, price and stock by seller SKU, pending orders, pack and ready-to-ship (Daraz gives the tracking) |
| WordPress | REST with an Application Password | Draft posts with a featured picture, list, publish after a yes |
| Odoo | JSON-RPC (Odoo 18 and 19) with an API key | Products, orders to invoice, draft customer invoices (customer and products found or added) |
| Web pages | headless Chrome (the page's scripts run, nothing on screen) | Readable text to Markdown (menus and footers left out), tables to Excel with numbers as numbers, links, PDF, full-page picture |
| Desktop | Pillow, the Windows clipboard, the default programs | Screenshots of every screen, text on and off the clipboard, files and web pages opened |
| Email campaigns | Mailchimp Marketing API 3.0, Brevo API v3 | Audiences, contacts from Excel (bad addresses left out), a campaign shown first with how many it reaches, reports |
| Dropbox | API v2, PKCE code pasted once | Uploads checked with Dropbox's own content hash, folders listed, share links after a yes |
| Discord | a channel's webhook | Messages and pictures posted after a yes, read back, the last post deleted on request |
| Statistics (like SPSS) | numpy plus its own t, F and chi-square distributions | Descriptives, t-test (Student and Welch, Cohen's d), ANOVA, crosstab with chi-square, correlation, regression, Cronbach's alpha; APA sentences and tables in Word |
| Grammar and spelling | LanguageTool's free public service (after a yes: the text leaves the PC) | Issues listed with suggestions; spelling and grammar fixed in a copy, style hints listed |

Store and website changes are shown first and done after a yes, then read back from the shop. `ai-pc apps steps shopify` (or
woocommerce, daraz, wordpress, odoo) shows how to get the keys; `ai-pc apps connect shopify` keeps them encrypted.

Measured (2026-10-04): [tests/integration/test_apps.py](../../tests/integration/test_apps.py) 103/103 in 27 s (29 programs; statistics checked against textbook p-values and hand-worked tests) (each program's main path, by function and by chat;
printing checked through 'Microsoft Print to PDF'; web services are fakes from their documentation in
[tests/integration/stores_fakes.py](../../tests/integration/stores_fakes.py); Daraz's signature checked against Daraz's own test vector).

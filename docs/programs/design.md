# Design

## Design: cards, posts, thumbnails, flyers, certificates (programmatic)

```
ai-pc design talk -m "a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567, ahmed@khan.pk, khanelectronics.pk"
   -m "classic style in maroon" -m "make the name bigger" -m "add a QR code" -m "export the pdf for printing"
ai-pc design talk --with car.jpg -m "an instagram post for Khan Motors 'Eid Sale' 20% off 1-15 June, shop now" -m "use car.jpg" -m "make it a story"
ai-pc design talk --with me.png -m "a youtube thumbnail saying I tried every AI tool, with me.png"
ai-pc design talk --with names.xlsx -m "a certificate of participation from Green Valley School for taking part in the Science Fair"
   -m "certificates for the names in names.xlsx" -m "export the pdf"
ai-pc design make "an invitation for the grand opening of Khan Electronics on Friday 9 October at 6 pm at Shop 12, Hall Road, Lahore"
```

The design is written as HTML and CSS. A hidden Chrome renders it, with a profile of its own inside the project, to
PNG and to a vector print PDF. The PDF is at the exact size with 3 mm bleed. Fonts are the ones every Windows PC has:
Bahnschrift, Segoe UI, Bodoni, Palatino, Rockwell, Impact and Segoe Script. The one new package is `segno`, which
makes QR codes. It is pure Python, was checked by SHA-256 against PyPI, and was scanned before an offline install.

| Area | What it does |
|---|---|
| Kinds | Visiting cards: 3.5 x 2 in, front and back, modern, classic or bold. Square and portrait posts and stories: headline, photo or split. YouTube thumbnails, with a face or centred. Flyers (A5) and posters (A3): sale, with a price list, or event. Certificates (A4 landscape), classic or modern. Invitations (5 x 7 in). Fifteen palettes, seven gradients, any paper size. |
| Layout | Text sits in boxes that shrink it to fit, never below a readable floor. Print designs bleed past the trim and keep words 3 mm inside it. Screen designs keep clear of the apps' own buttons: a story's top 260 px and bottom 360 px. Contact rows carry drawn icons. A monogram stands in for a missing logo. |
| Photos | The photo agent does the photo work. A thumbnail's presenter is cut from a green, blue or plain backdrop and placed with a glow. On a photo post, faces are found and the words go to the other end of the picture. |
| Conversation | "classic style in green", "try another style", "make the name bigger", "change the phone to ...", "remove the address", "add a QR code for ...", "use photo.jpg", "make it a story", "sunset gradient", "export the pdf for printing", "save the png for whatsapp", undo, redo, go back, history. A thinly worded request ("my uncle runs a bakery called ... make him a card") is read by the cheap model, which is told never to invent numbers, prices or names. |
| Certificates for many people | Names come from the chat, a TXT/CSV or an Excel file. They render as one multi-page PDF in a single browser pass. Each name is checked to be printed once, spelled as given, and fitting its line; long names are set smaller and the reply says so. |
| Checks | The page measures itself after rendering: each piece's box, where its letters actually are, type size, colour, outline, and overflow. A second render with the words hidden shows what each word sits on. From these: every detail asked for is on the design; no text runs out of its box; type is at least 5.5 pt in print, or 16 px on screen; everything is inside the safe area; nothing overlaps; WCAG contrast is met against the real background; photos print at 150 dpi or more; the QR code is decoded back to its link with OpenCV; no words cover a face; the fonts are installed; the PDF has one page per side at the exact size; screen designs are their exact pixel size. |
| Speed | All sides go in one document, and four hidden browsers (measure, picture, words hidden, print) run side by side, each with its own profile. A two-sided card takes about 3 s, a post 2-4 s. |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_design.py](../../tests/integration/test_design.py): 16 designs across every kind and style passing every check; 11 designs spoiled on purpose, each tripping its check (an overlong name, text the colour of the ground, a name past the trim, a QR code read as the wrong link, a missing phone, wrong PDF and picture sizes, a missing font, words over a face, a 90 px photo on an A3 poster); certificate batches; 22 phrasings | 52/52 | 51 s | none |
| [tests/integration/design_conversations.py](../../tests/integration/design_conversations.py): 5 conversations, 21 turns (a card, a post that becomes a story, a cut-out thumbnail, certificates for four names, requests only the model can read) | 21/21 | 41 s | $0.0003 |

Building it, the checks and visual reviews caught real faults:
- Tight line heights made Chrome report every headline as overflowing, so all of them shrank to their floor.
- Grey and gold text on light paper failed WCAG contrast. Gold text is now darkened only as much as the background needs, while badges keep the true accent.
- White text on a pale sunset gradient read at 1.5:1. Text colours now follow how light the ground is.
- The photo and split posts silently dropped the dates and the call to action.
- An A3 poster built on a 1280 x 720 video still would have printed at 93 dpi.
- A story's headline spilled into the brand line.
- "Dr." in "signed by Dr. Imran Ali" cut the signer's name.

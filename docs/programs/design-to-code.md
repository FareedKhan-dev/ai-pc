# Designs to code (Figma and Canva)

## Designs to code: Figma and Canva (official APIs) into coding projects

```
ai-pc hub connect figma         a personal access token (ai-pc hub steps figma)
ai-pc hub connect canva         your own Canva integration, signed in once in the browser (ai-pc hub steps canva)
ai-pc code talk -m "make a website from https://www.figma.com/design/KEY/Shop?node-id=1-2" -m "make the call now button green" -m "does it still match the design?"
ai-pc code talk -m "turn my Canva design 'Eid sale' into a web page" -m "make the shop now button say 'Order now'"
ai-pc hub talk -m "what frames are in https://www.figma.com/design/KEY/Shop" -m "export the 'Home' frame from figma as png to my downloads"
ai-pc hub talk -m "list my canva designs" -m "export my canva design \"Eid sale\" as a pdf to my desktop" -m "upload logo.png to canva"
```

Both tools are driven only through their official APIs: Figma's REST API with a personal access token, and Canva's
Connect API through your own integration (PKCE sign-in on 127.0.0.1:3001; Canva's single-use refresh tokens are kept
in the vault). A design becomes a normal coding project, so the coding lane's versions, undo, VS Code setup and model
edits all apply to it.

| Part | What it does |
|---|---|
| Figma frame to code | Figma's own description of the frame becomes HTML and CSS. Auto layout becomes flexbox: direction, gaps, padding, alignment, wrapping, and each child fixed, hugging or filling. Everything else sits exactly where the design puts it, rotations and flips kept. Texts stay real text: fonts, sizes, weights, line heights, letter spacing, colours, mixed styles, links, lists, truncation. Fills cover colours, gradients and pictures; also borders, corners, shadows, blurs, opacity, blend modes, clipping and masks. Icons are SVG drawn from Figma's own outlines. Each layer gets one CSS class named after it. The HTML is indented, with landmarks (nav, header, section, footer), headings by size, and buttons and links where the layers say so. |
| Canva design to code | Canva's Connect API cannot read a design's elements from outside Canva, so the design is exported as PowerPoint and read with python-pptx. Text boxes, pictures (crops applied), shapes, freeforms, groups, bullets and links come out in the same shape as Figma's, and the same converter writes the page. Anything with no web equivalent, such as a chart or table, is cut from Canva's own picture of the page. Several pages become sections of one page. Email designs can come as Canva's own HTML. |
| Fonts | The free Google fonts a design uses are saved into the project (latin subsets, SIL Open Font License or Apache 2.0), so the page looks the same offline. A paid font is named, and a stand-in is used. |
| Checks on every version | The page is opened in headless Chrome at the design's size and measured from inside. Every element's box is compared with the design's box, within 3 px, and the worst misses are named. Every text must be present, and none may spill out of its box. Every font must actually load. A screenshot is compared with the design's own picture (Figma's PNG of the frame, or Canva's PNG pages) for shape similarity (SSIM) and colour, cell by cell, and the least alike part is named with the layers near it. `.out/compare.png` shows the design, the page and their differences side by side. After you ask for changes, the comparison is reported but no longer enforced, because changes are meant to differ. |
| Hub | Figma: a file's frames, its colours and text styles, frames exported in one request (PNG, SVG, PDF, JPG), comments read, and comments posted after your yes, read back and undoable. Canva: designs listed and found by name, new designs (presets or named sizes), files imported as editable designs, exports saved to your folders (PDF, PNG, JPG, GIF, MP4, PowerPoint), and pictures uploaded and undoable. |
| Limits respected | Figma's View and Collab seats allow about 20 file reads a month. A file is read once, kept on this PC, and read again only when Figma's cheap version check says it changed. Pictures are fetched once (their names are content hashes), and all frames export in one request. Canva's export jobs are polled with growing waits, and its download links are fetched at once, never with your key. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/integration/test_design2code.py](../../tests/integration/test_design2code.py): a landing page in Figma's exact JSON with every box worked out by hand (37/37 elements in place, 17/17 texts, the HTML and CSS Figma's rules call for); a spoiled copy caught (a moved title named, a changed text found); the picture comparison finding a changed region; fonts; Canva's route on a PowerPoint file with PowerPoint's own pictures as the reference (page 1 similarity >= 0.9, the chart page >= 0.95, two pages as two sections); both connectors against fake servers (caching, exports, downloads without the key, polled jobs, explained errors, comments and uploads taken back, PKCE sign-in and refresh); the coding chat and the hub end to end | 96/96 | 38 s | none |
| [tests/integration/design2code_conversations.py](../../tests/integration/design2code_conversations.py), GLM-5.3-Flash: a Figma landing page made, its button turned green and its heading reworded by the model, measured again and undone; a Canva sale page whose button text is changed | 7/7 turns (twice) | 39 s | $0.0021 |

Live tests need your Figma token and Canva integration (`ai-pc hub steps figma`, `ai-pc hub steps canva`).

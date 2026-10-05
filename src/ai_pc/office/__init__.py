"""Office documents, programmatically (the CapCut recipe): code writes the .docx / .pptx / .xlsx itself, the real
Office app only renders it in the background (no window, no mouse), and every element is checked on the rendered pages.

  render.py     Word / PowerPoint / Excel by COM in a child process: update fields, save, export PDF, measure text
  themes.py     design systems: fonts, sizes, colours, spacing, table looks
  docplan.py    the document plan (blocks) and its resolution: recipes per document type, defaults, numbering
  docx_build.py the .docx from a plan: real Word styles, tables, native charts, TOC, page numbers
  charts.py     native (editable) charts for Word, made with python-pptx's chart XML
  verify.py     checks at every element on the rendered PDF
  designer.py   the cheap model writes the outline, then every section in parallel
  ai-pc video     request -> plan -> build -> render -> check -> fix -> report
"""

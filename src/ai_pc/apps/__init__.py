"""Many programs, a basic setup each. Every module here is one program (or one kind of work) driven by code:

  NAME, LABEL, EXAMPLES          what it is and what to say
  parse(text, ctx) -> op | None  a request read by rules (ctx: {"files": {name: path}, "out": folder, "now": datetime})
  run(op, ctx) -> str            done and checked; the reply says what was made and what was checked
  OUTWARD = {...}                ops that change the PC or reach outside it (install, print...): shown first, done after a yes
  preview(op, ctx) -> str        what such an op will do

The apps chat (appschat.py) asks each module in turn; ai-pc apps is the command line.
"""
import importlib

MODULES = ["ocr", "autohotkey", "keepassxc", "pccare", "diagrams", "cite", "quiz", "calibre", "ebook", "media", "printing", "maps", "notes", "obsidian", "postgres", "mysql", "mongodb", "powerbi", "database", "backup", "contacts", "codes", "music",
           "shopify", "woocommerce", "daraz", "wordpress", "odoo", "web", "desktop", "mailchimp", "brevo", "dropbox", "discord", "rstats", "stats", "grammar",
           "unity", "godot", "premiere", "photoshop", "illustrator", "aftereffects", "obs", "gworkspace", "github", "spotify", "salesforce", "mstodo", "jupyter", "docker", "postman", "revit", "lightroom", "anki", "arduino", "msproject", "prusaslicer", "freecad", "matlab", "musescore", "lmms", "audacity", "kicad", "krita", "openscad", "libreoffice", "gimp", "rawtherapee", "qgis", "shotcut", "latex", "drawio", "visio", "handbrake", "sevenzip", "vscode", "clion", "goland", "rustrover", "pycharm", "nodejs", "php", "flutter", "visualstudio", "androidstudio", "intellij",
           "calendar"]  # calendar last: its words (call, meeting, class) are the widest


def load(name):
    return importlib.import_module(f".{name}", __name__)


def all_modules():
    out = []
    for n in MODULES:
        try:
            out.append(load(n))
        except ImportError:
            continue
    return out

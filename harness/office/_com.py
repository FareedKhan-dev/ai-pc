"""Office jobs by COM in the background (no window, no mouse), in instances of their own so the user's open documents
are never touched. Two ways to run:

  python -m harness.office._com '{"app": "word", "src": "...docx", "pdf": "...pdf", "update_fields": true, "save": true}'
      one job, then Office quits (prints one '@@RESULT {json}' line)
  python -m harness.office._com serve
      a worker that keeps Word / PowerPoint / Excel open and runs one JSON job per stdin line (render.Server): a render
      takes ~1-2 s instead of ~6-8 s. The parent stops it, and only the Office instances it started, if a job hangs.
"""
import json
import sys
import time
import traceback

XL_ERRORS = {-2146826281: "#DIV/0!", -2146826246: "#N/A", -2146826259: "#NAME?", -2146826288: "#NULL!", -2146826252: "#NUM!",
             -2146826265: "#REF!", -2146826273: "#VALUE!", -2146826245: "#GETTING_DATA", -2146826215: "#SPILL!", -2146826219: "#CALC!"}
PROGID = {"word": "Word.Application", "powerpoint": "PowerPoint.Application", "excel": "Excel.Application"}


def _new_app(name):
    import win32com.client
    app = win32com.client.DispatchEx(PROGID[name])
    if name == "word":
        app.Visible = False
        app.DisplayAlerts = 0  # wdAlertsNone
    elif name == "excel":
        app.Visible = False
        app.DisplayAlerts = False
        app.ScreenUpdating = False
        app.EnableEvents = False
        app.AskToUpdateLinks = False
    return app


def _alive(app):
    try:
        _ = app.Version
        return True
    except Exception:  # noqa: BLE001
        return False


def _word(job, app):
    out = {}
    doc = app.Documents.Open(FileName=job["src"], ConfirmConversions=False, ReadOnly=not job.get("save"), AddToRecentFiles=False,
                             Visible=False, NoEncodingDialog=True)
    try:
        out["compat"] = int(doc.CompatibilityMode)
        if job.get("save") and out["compat"] < 15:  # python-docx's template is older: lay out as current Word does
            doc.SetCompatibilityMode(15)
        if job.get("update_fields"):
            n = doc.TablesOfContents.Count
            for i in range(1, n + 1):
                doc.TablesOfContents(i).Update()
            doc.Fields.Update()
            out["tocs"] = n
        if job.get("save"):
            doc.Save()
        if job.get("pdf"):
            doc.ExportAsFixedFormat(OutputFileName=job["pdf"], ExportFormat=17, OpenAfterExport=False, OptimizeFor=0,
                                    CreateBookmarks=1, DocStructureTags=True, BitmapMissingFonts=True)
        out["pages"] = int(doc.ComputeStatistics(2))  # wdStatisticPages
        out["words"] = int(doc.ComputeStatistics(0))
    finally:
        doc.Close(SaveChanges=0)
    return out


def _powerpoint(job, app):
    out = {}
    pres = app.Presentations.Open(FileName=job["src"], ReadOnly=0 if job.get("save") else -1, Untitled=0, WithWindow=0)
    try:
        out["slides"] = int(pres.Slides.Count)
        out["size"] = [float(pres.PageSetup.SlideWidth), float(pres.PageSetup.SlideHeight)]
        if job.get("measure"):  # where PowerPoint's own layout puts each text (overflow is text taller than its box)
            shapes = []
            only = set(job.get("measure_slides") or [])  # measuring every shape is slow: only the slides that changed
            for s in pres.Slides:
                if only and int(s.SlideIndex) not in only:
                    continue
                for sh in s.Shapes:
                    try:
                        if not (sh.HasTextFrame and sh.TextFrame2.HasText):
                            continue
                        tr = sh.TextFrame2.TextRange
                        shapes.append({"slide": int(s.SlideIndex), "name": str(sh.Name), "left": float(sh.Left), "top": float(sh.Top),
                                       "width": float(sh.Width), "height": float(sh.Height), "text_left": float(tr.BoundLeft),
                                       "text_top": float(tr.BoundTop), "text_width": float(tr.BoundWidth), "text_height": float(tr.BoundHeight),
                                       "font_size": float(tr.Font.Size) if tr.Font.Size else None, "text": str(tr.Text)[:200]})
                    except Exception:  # noqa: BLE001  (charts, tables: no text frame of their own)
                        continue
            out["shapes"] = shapes
        if job.get("save"):
            pres.Save()
        if job.get("pdf"):
            pres.SaveAs(job["pdf"], 32)  # ppSaveAsPDF
        if job.get("png_dir"):
            w = int(job.get("png_width") or 1280)
            h = int(round(w * out["size"][1] / out["size"][0]))
            for s in pres.Slides:
                s.Export(f"{job['png_dir']}\\slide{int(s.SlideIndex):03d}.png", "PNG", w, h)
    finally:
        pres.Close()
    return out


def _right_edges(wb):
    out = {}
    for ws in wb.Worksheets:
        try:
            ur = ws.UsedRange
            right = float(ur.Left) + float(ur.Width)
            for co in ws.ChartObjects():
                right = max(right, float(co.Left) + float(co.Width))
            out[str(ws.Name)] = right
        except Exception:  # noqa: BLE001
            continue
    return out


def _fit_print(app, wb, before):
    """A sheet the edits made wider than a portrait page prints landscape, one page wide (never one the edits left alone)."""
    fixed = []
    for name, right in _right_edges(wb).items():
        if right <= 540 or right <= before.get(name, 0) + 1:
            continue
        try:
            app.PrintCommunication = False
        except Exception:  # noqa: BLE001
            pass
        try:
            ps = wb.Worksheets(name).PageSetup
            ps.Orientation = 2
            if right > 760:
                ps.Zoom = False
                ps.FitToPagesWide = 1
                ps.FitToPagesTall = False
            fixed.append(name)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                app.PrintCommunication = True
            except Exception:  # noqa: BLE001
                pass
    return fixed


def _excel(job, app):
    out = {}
    wb = app.Workbooks.Open(job["src"], UpdateLinks=0, ReadOnly=not job.get("save"), IgnoreReadOnlyRecommended=True, AddToMru=False)
    try:
        if job.get("ops"):  # edits done by Excel itself (it keeps charts, pivots and formats a file library would drop)
            from .xlsx_com import run_ops
            before = _right_edges(wb)
            out["ops"] = run_ops(app, wb, job["ops"])
            out["print_fit"] = _fit_print(app, wb, before)
        app.CalculateFull()
        errors, sheets = [], []
        for ws in wb.Worksheets:
            used = ws.UsedRange
            r0, c0 = int(used.Row), int(used.Column)
            vals = used.Value
            rows = vals if isinstance(vals, tuple) else ((vals,),)
            for i, row in enumerate(rows):
                for j, v in enumerate(row if isinstance(row, tuple) else (row,)):
                    if isinstance(v, int) and v in XL_ERRORS:
                        errors.append({"sheet": str(ws.Name), "row": r0 + i, "col": c0 + j, "error": XL_ERRORS[v]})
            sheets.append({"name": str(ws.Name), "rows": int(used.Rows.Count), "cols": int(used.Columns.Count)})
            if job.get("autofit"):
                used.Columns.AutoFit()
        out["errors"] = errors[:200]
        out["sheets"] = sheets
        vals = {}
        for rd in job.get("read") or []:  # what Excel itself computed in chosen cells
            try:
                v = wb.Worksheets(rd["sheet"]).Range(rd["cell"]).Value
                vals[f"{rd['sheet']}!{rd['cell']}"] = XL_ERRORS.get(v, v) if isinstance(v, int) else (float(v) if isinstance(v, (int, float)) else str(v))
            except Exception as e:  # noqa: BLE001
                vals[f"{rd['sheet']}!{rd['cell']}"] = f"read failed: {type(e).__name__}"
        out["values"] = vals
        if job.get("grab"):  # tables and pivots as Excel shows them, for a report or a deck
            from .xlsx_com import OpError, grab
            got = []
            for spec in job["grab"]:
                try:
                    got.append(grab(app, wb, spec))
                except OpError as e:
                    got.append({"error": str(e)})
                except Exception as e:  # noqa: BLE001
                    got.append({"error": f"Excel said: {type(e).__name__}: {str(e)[:160]}"})
            out["grab"] = got
        charts = 0
        for ws in wb.Worksheets:
            try:
                charts += int(ws.ChartObjects().Count)
            except Exception:  # noqa: BLE001
                pass
        out["charts"] = charts
        if job.get("save"):
            wb.Save()
        if job.get("pdf"):
            wb.ExportAsFixedFormat(0, job["pdf"])  # xlTypePDF
    finally:
        wb.Close(SaveChanges=bool(job.get("save")))
    return out


RUN = {"word": _word, "powerpoint": _powerpoint, "excel": _excel}


def run_job(job, apps=None):
    """One job; with `apps` (a dict) the Office instances stay open for the next job."""
    name = job["app"]
    keep = apps is not None
    app = (apps or {}).get(name)
    if app is None or not _alive(app):
        app = _new_app(name)
        if keep:
            apps[name] = app
    try:
        return RUN[name](job, app)
    finally:
        if not keep:
            try:
                app.Quit()
            except Exception:  # noqa: BLE001
                pass


def _serve():
    import pythoncom
    pythoncom.CoInitialize()
    apps = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        job = json.loads(line)
        if job.get("quit"):
            break
        t0 = time.perf_counter()
        try:
            res = run_job(job, apps)
            res["ok"] = True
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
            app = apps.get(job.get("app"))
            if app is not None and not _alive(app):
                apps.pop(job["app"], None)
        res["seconds"] = round(time.perf_counter() - t0, 2)
        print("@@RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    for app in apps.values():
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _serve()
        sys.exit(0)
    t0 = time.perf_counter()
    try:
        import pythoncom
        pythoncom.CoInitialize()
        res = run_job(json.loads(sys.argv[1]))
        res["ok"] = True
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    res["seconds"] = round(time.perf_counter() - t0, 2)
    print("@@RESULT " + json.dumps(res, ensure_ascii=False), flush=True)

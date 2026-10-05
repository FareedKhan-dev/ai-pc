"""Canva through its Connect API (an integration made in Canva's Developer Portal; sign-in once with PKCE, the refresh token
kept in the vault): your designs found by name, a new design, a file imported as an editable design (PowerPoint, Word, PDF,
Photoshop, Illustrator ...), any design exported (PDF, PNG, JPG, GIF, MP4, PowerPoint; email designs also as HTML) and
saved on this PC, and pictures or videos uploaded to your Canva uploads (and deleted again for undo).

Everything Canva does with a file is a job: start it, then ask until it is done. Canva allows about 20 imports and 20
exports a minute per person (and 500 exports a day); download links last 24 hours, so files are fetched at once.
"""
import base64
import json
import mimetypes
import re
import time
from pathlib import Path

from ai_pc.core.config import STATE
from ai_pc.hub import oauth
from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base, norm, pick

API = "https://api.canva.com/rest/v1"
EXPORTS = STATE / "hub" / "canva" / "exports"
PRESETS = {"presentation": "presentation", "slides": "presentation", "deck": "presentation", "doc": "doc", "document": "doc", "whiteboard": "whiteboard"}
SIZES = {"instagram post": (1080, 1080), "instagram story": (1080, 1920), "facebook post": (1200, 630), "youtube thumbnail": (1280, 720),
         "a4": (2480, 3508), "poster": (2480, 3508), "flyer": (2480, 3508), "business card": (1050, 600), "logo": (500, 500), "banner": (1500, 500)}
FORMATS = {"pdf", "png", "jpg", "gif", "pptx", "mp4", "html_bundle", "csv"}
MIME = {".pdf": "application/pdf", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".psd": "image/vnd.adobe.photoshop",
        ".ai": "application/postscript", ".key": "application/vnd.apple.keynote", ".odp": "application/vnd.oasis.opendocument.presentation"}


def _b64(s):
    return base64.b64encode(str(s).encode("utf-8")).decode()


def _safe(s):
    return re.sub(r"[^\w -]+", "", str(s or "design")).strip().replace(" ", "_")[:60] or "design"


class Canva(Base):
    name = "canva"
    pause = staticmethod(time.sleep)  # tests replace it, so polling does not wait

    def api(self):
        tok = self.creds.get("access_token") if self.transport else oauth.access_token("canva")
        return Api(API, headers={"Authorization": f"Bearer {tok}"}, service="canva", transport=self.transport)

    def whoami(self):
        a = self.api()
        me = a.get("users/me").get("team_user") or {}
        try:
            name = (a.get("users/me/profile").get("profile") or {}).get("display_name")
        except HubError:
            name = None
        return {"who": name or me.get("user_id"), "where": "Canva"}

    # ---------------------------------------------------------------- designs
    def designs(self, query=None, limit=50):
        out, cont = [], None
        while len(out) < limit:
            js = self.api().get("designs", params={"query": query or None, "ownership": "any", "limit": min(100, limit - len(out)),
                                                   "sort_by": "relevance" if query else "modified_descending", "continuation": cont})
            for d in js.get("items", []):
                out.append(self._design(d))
            cont = js.get("continuation")
            if not cont:
                break
        return out[:limit]

    @staticmethod
    def _design(d):
        th = d.get("thumbnail") or {}
        return {"id": d["id"], "name": d.get("title") or "(untitled)", "link": (d.get("urls") or {}).get("edit_url"),
                "view": (d.get("urls") or {}).get("view_url"), "pages": d.get("page_count"), "updated": d.get("updated_at"),
                "w": th.get("width"), "h": th.get("height")}

    def find(self, name):
        """A design by its name (Canva's search first, then the names themselves)."""
        if re.fullmatch(r"D[A-Za-z0-9_-]{9,}", str(name or "")):
            return self.design(name)
        hits = self.designs(name, 30)
        d = pick(hits, name) or (hits[0] if hits and norm(name) in norm(hits[0]["name"]) else None)
        if not d:
            raise HubError(f"canva: no design called '{name}'" + (f" (closest: {', '.join(h['name'] for h in hits[:5])})" if hits else ""))
        return d

    def design(self, id):  # noqa: A002
        return self._design(self.api().get(f"designs/{id}")["design"])

    def create(self, title, kind=None, width=None, height=None, asset_id=None):
        """A new design: a preset (presentation, doc, whiteboard), a named size ('instagram post'), or width x height in px."""
        k = norm(kind)
        if k in PRESETS:
            dtype = {"type": "preset", "name": PRESETS[k]}
        else:
            w, h = (width, height) if width and height else SIZES.get(k, (1080, 1080))
            dtype = {"type": "custom", "width": int(w), "height": int(h)}
        body = {"design_type": dtype, "title": title[:255]}
        if asset_id:
            body["asset_id"] = asset_id
        d = self._design(self.api().post("designs", json=body)["design"])
        back = self.design(d["id"])
        return dict(d, where="Canva", verified=back["name"] == title[:255], undo=None)

    # ---------------------------------------------------------------- jobs
    def _job(self, path, start, what, timeout=300):
        job = start.get("job") or start
        jid, t0, wait = job.get("id"), time.time(), 1.0
        while job.get("status") == "in_progress":
            if time.time() - t0 > timeout:
                raise HubError(f"canva: the {what} did not finish in {timeout} s")
            self.pause(wait)
            wait = min(wait * 1.5, 8)
            job = self.api().get(f"{path}/{jid}").get("job") or {}
        if job.get("status") != "success":
            err = job.get("error") or {}
            hint = {"license_required": " (the design uses paid Canva elements your plan does not include)",
                    "approval_required": " (the design needs approval in Canva first)"}.get(err.get("code"), "")
            raise HubError(f"canva: the {what} failed: {err.get('message') or err.get('code') or job.get('status')}{hint}")
        return job

    def import_file(self, path, title=None):
        """A file on this PC becomes an editable Canva design."""
        p = Path(path)
        if not p.is_file():
            raise HubError(f"canva: no file {p}")
        meta = {"title_base64": _b64(title or p.stem)}
        if p.suffix.lower() in MIME:
            meta["mime_type"] = MIME[p.suffix.lower()]
        start = self.api().request("POST", "imports", data=p.read_bytes(), headers={"Content-Type": "application/octet-stream",
                                                                                     "Import-Metadata": json.dumps(meta)})
        job = self._job("imports", start, "import")
        ds = ((job.get("result") or {}).get("designs")) or []
        if not ds:
            raise HubError("canva: the import finished without a design")
        d = self._design(ds[0])
        return dict(d, where="Canva", verified=bool(self.design(d["id"])["id"]), undo=None)

    def export(self, design, fmt="pdf", folder=None, pages=None, quality=None, name=None):
        """A design saved on this PC as PDF / PNG / JPG / GIF / PPTX / MP4 (email designs: html_bundle, a zip of HTML and pictures)."""
        fmt = {"jpeg": "jpg", "powerpoint": "pptx", "ppt": "pptx", "video": "mp4", "html": "html_bundle"}.get(norm(fmt), norm(fmt))
        if fmt not in FORMATS:
            raise HubError(f"canva: Canva cannot export {fmt} (it can do {', '.join(sorted(FORMATS))})")
        d = design if isinstance(design, dict) else self.find(design)
        f = {"type": fmt}
        if pages:
            f["pages"] = [int(x) for x in pages]
        if fmt == "jpg":
            f["quality"] = int(quality or 90)
        if fmt == "mp4":
            tall = (d.get("h") or 0) > (d.get("w") or 1)
            f["quality"] = quality or ("vertical_1080p" if tall else "horizontal_1080p")
        if fmt == "png":
            f["lossless"] = True
        start = self.api().post("exports", json={"design_id": d["id"], "format": f})
        job = self._job("exports", start, f"{fmt.upper()} export")
        urls = job.get("urls") or []
        if not urls:
            raise HubError("canva: the export finished without a file")
        folder = Path(folder or EXPORTS)
        folder.mkdir(parents=True, exist_ok=True)
        ext = {"html_bundle": "zip"}.get(fmt, fmt)
        dl = Api("https://export-download.canva.com", service="canva download", transport=self.transport, timeout=120)  # no key sent to the download
        files = []
        nums = [int(x) for x in pages] if pages and len(pages) == len(urls) else list(range(1, len(urls) + 1))
        for i, u in enumerate(urls):
            status, _, content = dl.request("GET", u, raw=True)
            if status >= 400 or not content:
                raise HubError(f"canva: the exported file could not be downloaded ({status})")
            stem = _safe(name or d["name"]) + (f"_p{nums[i]}" if len(urls) > 1 or pages else "")
            out = folder / f"{stem}.{ext}"
            out.write_bytes(content)
            files.append(str(out))
        return {"design": d["name"], "id": d["id"], "format": fmt, "files": files, "where": str(folder)}

    # ---------------------------------------------------------------- uploads
    def upload(self, path, name=None):
        """A picture or video into your Canva uploads."""
        p = Path(path)
        if not p.is_file():
            raise HubError(f"canva: no file {p}")
        start = self.api().request("POST", "asset-uploads", data=p.read_bytes(),
                                   headers={"Content-Type": "application/octet-stream", "Asset-Upload-Metadata": json.dumps({"name_base64": _b64(name or p.stem)})})
        job = self._job("asset-uploads", start, "upload")
        a = job.get("asset") or {}
        if not a.get("id"):
            raise HubError("canva: the upload finished without an asset")
        back = self.api().get(f"assets/{a['id']}").get("asset") or {}
        return {"id": a["id"], "name": a.get("name"), "where": "your Canva uploads", "verified": back.get("id") == a["id"],
                "undo": {"service": "canva", "op": "delete_asset", "id": a["id"]}, "type": mimetypes.guess_type(p.name)[0]}

    def delete_asset(self, id):  # noqa: A002
        self.api().delete(f"assets/{id}")
        return {"deleted": id}

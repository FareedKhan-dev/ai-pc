"""Figma through its REST API with a personal access token: a file's pages and frames, frames exported as PNG, SVG or
PDF, the image fills, the design's colours and text styles (design tokens), comments read and posted (and taken back).

Figma rations its API by plan and seat (2025-11-17): reading a file or exporting images is 'Tier 1' - 10-20 a minute on
Full and Dev seats, but only up to 20 a MONTH on View and Collab seats. So a file read is cached until Figma says the
file changed (its metadata is a cheap Tier 3 call), and every export takes all the frames in one request.
"""
import json
import re
from pathlib import Path

from ai_pc.core.config import STATE
from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base, pick

API = "https://api.figma.com"
CACHE = STATE / "hub" / "figma"


def key_of(link):
    """A Figma link or key -> (file key, node id or None). '...figma.com/design/AbC123/Name?node-id=12-34' -> ('AbC123', '12:34')."""
    s = str(link or "").strip()
    m = re.search(r"figma\.com/(?:file|design|proto|board|make)/([A-Za-z0-9]{10,})", s)
    key = m.group(1) if m else (s if re.fullmatch(r"[A-Za-z0-9]{10,}", s) else None)
    if not key:
        raise HubError("figma: that is not a Figma link (it looks like https://www.figma.com/design/<key>/...)")
    n = re.search(r"node-id=(\d+)(?:-|:|%3A)(\d+)", s, re.I)
    return key, (f"{n.group(1)}:{n.group(2)}" if n else None)


class Figma(Base):
    name = "figma"

    def api(self):
        self.need("token")
        return Api(API, headers={"X-Figma-Token": self.creds["token"]}, service="figma", transport=self.transport)

    def _get(self, path, tier=1, **params):
        try:
            return self.api().get(path, params=params or None, retries=1 if tier == 1 else 3)
        except HubError as e:
            if e.status == 429:
                raise HubError("figma: Figma's API limit is reached for now (on a View or Collab seat it is 20 file reads a month; on a Full "
                               "seat, about 10 a minute). Try again later.", e.status, e.body)
            if e.status == 403:
                raise HubError("figma: the token cannot open that file (is it shared with you, and does the token have 'File content: read'?)",
                               e.status, e.body)
            if e.status == 404:
                raise HubError("figma: no such file (check the link)", e.status, e.body)
            raise

    def whoami(self):
        me = self._get("v1/me", tier=3)
        return {"who": me.get("handle"), "where": me.get("email")}

    # ---------------------------------------------------------------- files, cached
    def meta(self, key):
        js = self._get(f"v1/files/{key}/meta", tier=3)
        f = js.get("file") or js
        return {"name": f.get("name"), "version": str(f.get("version") or f.get("last_touched_at") or ""), "last_touched": f.get("last_touched_at"),
                "editor": f.get("editorType")}

    def file(self, key, fresh=False):
        """The whole file (its node tree), from the cache while Figma's version of it is unchanged."""
        CACHE.mkdir(parents=True, exist_ok=True)
        cached = CACHE / f"{key}.json"
        version = None
        if cached.exists() and not fresh:
            data = json.loads(cached.read_text(encoding="utf-8"))
            try:
                version = self.meta(key)["version"]
            except HubError:  # Figma cannot be asked now: the copy on this PC, marked as maybe old
                return dict(data, _stale=True)
            if version and data.get("_version") == version:
                return data
        data = self._get(f"v1/files/{key}", tier=1, geometry="paths")
        data["_version"] = version or str(data.get("version") or data.get("lastModified") or "")
        data["_key"] = key
        cached.write_text(json.dumps(data), encoding="utf-8")
        return data

    def frames(self, key, data=None):
        """The top-level frames on every page: [{"id", "name", "page", "type", "w", "h"}]."""
        data = data or self.file(key)
        out = []

        def add(nodes, where):
            for n in nodes:
                if n.get("type") == "SECTION":  # a section holds frames on the canvas: its frames count, not the section
                    add(n.get("children", []), f"{where} / {n.get('name', '')}")
                elif n.get("type") in ("FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE", "GROUP") and n.get("visible", True):
                    bb = n.get("absoluteBoundingBox") or {}
                    out.append({"id": n["id"], "name": n.get("name", ""), "page": where, "type": n["type"],
                                "w": round(bb.get("width", 0)), "h": round(bb.get("height", 0))})
        for page in (data.get("document") or {}).get("children", []):
            add(page.get("children", []), page.get("name", ""))
        return out

    def node(self, key, node_id, data=None):
        data = data or self.file(key)
        stack = [data.get("document") or {}]
        while stack:
            n = stack.pop()
            if n.get("id") == node_id:
                return n
            stack += n.get("children", [])
        raise HubError(f"figma: no frame {node_id} in the file")

    def find_frame(self, key, name, data=None):
        fr = self.frames(key, data)
        if not fr:
            raise HubError("figma: the file has no frames")
        if not name:
            return fr[0]
        hit = pick(fr, name)
        if not hit:
            raise HubError(f"figma: no frame called '{name}' (there are: {', '.join(f['name'] for f in fr[:8])})")
        return hit

    # ---------------------------------------------------------------- pictures
    def export(self, key, ids, fmt="png", scale=2, folder=None, names=None):
        """Frames (or any nodes) as pictures, all in ONE request; the files saved to folder. -> [{"id", "path"}]."""
        if not ids:
            return []
        js = self._get(f"v1/images/{key}", tier=1, ids=",".join(ids), format=fmt, scale=scale if fmt in ("png", "jpg") else None)
        if js.get("err"):
            raise HubError(f"figma: the export failed ({js['err']})")
        folder = Path(folder or (STATE / "hub" / "figma" / "exports"))
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        dl = Api("https://figma-alpha-api.s3.us-west-2.amazonaws.com", service="figma download", transport=self.transport)
        for i, url in (js.get("images") or {}).items():
            if not url:
                out.append({"id": i, "path": None, "error": "Figma could not draw it"})
                continue
            status, _, content = dl.request("GET", url, raw=True)
            if status >= 400 or not content:
                out.append({"id": i, "path": None, "error": f"download {status}"})
                continue
            stem = re.sub(r"[^A-Za-z0-9_-]+", "_", (names or {}).get(i) or i.replace(":", "-")).strip("_")[:60] or "frame"
            p = folder / f"{stem}.{fmt}"
            p.write_bytes(content)
            out.append({"id": i, "path": str(p)})
        return out

    def image_fills(self, key):
        """imageRef -> download URL for every image used as a fill (Tier 2)."""
        js = self._get(f"v1/files/{key}/images", tier=2)
        return ((js.get("meta") or {}).get("images")) or {}

    def download_images(self, key, refs, folder=None):
        """The pictures a frame uses, saved on this PC: {imageRef: file}. A ref names its picture's content, so a saved one is kept."""
        refs = set(refs or [])
        folder = Path(folder or (CACHE / "images"))
        folder.mkdir(parents=True, exist_ok=True)
        out = {r: str(p) for r in refs for p in folder.glob(f"{r}.*")}
        need = refs - set(out)
        if not need:
            return out
        urls = self.image_fills(key)
        dl = Api("https://s3-alpha.figma.com", service="figma download", transport=self.transport, timeout=120)
        for ref in need:
            if not urls.get(ref):
                continue
            status, _, content = dl.request("GET", urls[ref], raw=True)
            if status >= 400 or not content:
                continue
            head = content[:12]
            ext = "png" if head.startswith(b"\x89PNG") else "jpg" if head[:2] == b"\xff\xd8" else "gif" if head.startswith(b"GIF8") else \
                "webp" if head[8:12] == b"WEBP" else "png"
            p = folder / f"{ref}.{ext}"
            p.write_bytes(content)
            out[ref] = str(p)
        return out

    # ---------------------------------------------------------------- design tokens
    def tokens(self, key, data=None):
        """The colours and text styles the design uses, most used first: {"colors": [{"hex", "uses", "name"}], "text": [...]}."""
        data = data or self.file(key)
        styles = data.get("styles") or {}
        colors, texts = {}, {}
        stack = [data.get("document") or {}]
        while stack:
            n = stack.pop()
            stack += n.get("children", [])
            for f in n.get("fills") or []:
                if f.get("type") == "SOLID" and f.get("visible", True) and f.get("color"):
                    hx = hex_of(f["color"], f.get("opacity", 1))
                    sid = (n.get("styles") or {}).get("fill")
                    c = colors.setdefault(hx, {"hex": hx, "uses": 0, "name": (styles.get(sid) or {}).get("name") if sid else None})
                    c["uses"] += 1
            if n.get("type") == "TEXT" and n.get("style"):
                st = n["style"]
                k = (st.get("fontFamily"), st.get("fontWeight"), round(st.get("fontSize", 0)))
                sid = (n.get("styles") or {}).get("text")
                t = texts.setdefault(k, {"family": st.get("fontFamily"), "weight": st.get("fontWeight"), "size": round(st.get("fontSize", 0)),
                                         "line": round(st.get("lineHeightPx", 0)), "uses": 0, "name": (styles.get(sid) or {}).get("name") if sid else None})
                t["uses"] += 1
        return {"colors": sorted(colors.values(), key=lambda c: -c["uses"]), "text": sorted(texts.values(), key=lambda t: (-t["size"], -t["uses"]))}

    # ---------------------------------------------------------------- comments
    def comments(self, key):
        js = self._get(f"v1/files/{key}/comments", tier=2)
        return [{"id": c["id"], "who": (c.get("user") or {}).get("handle"), "text": c.get("message", ""), "when": c.get("created_at"),
                 "resolved": bool(c.get("resolved_at"))} for c in js.get("comments", [])]

    def comment(self, key, message, node_id=None):
        body = {"message": message}
        if node_id:
            body["client_meta"] = {"node_id": node_id, "node_offset": {"x": 0, "y": 0}}
        js = self.api().post(f"v1/files/{key}/comments", json=body)
        cid = js.get("id")
        back = [c for c in self.comments(key) if c["id"] == cid]
        return {"id": cid, "where": f"Figma file {key}", "verified": bool(back) and back[0]["text"] == message,
                "undo": {"service": "figma", "op": "uncomment", "key": key, "id": cid}}

    def uncomment(self, key, id):  # noqa: A002
        self.api().delete(f"v1/files/{key}/comments/{id}")
        return {"deleted": id}


def hex_of(c, opacity=1.0):
    r, g, b = (max(0, min(255, round(c.get(k, 0) * 255))) for k in ("r", "g", "b"))
    a = c.get("a", 1) * (opacity if opacity is not None else 1)
    return f"#{r:02x}{g:02x}{b:02x}" + (f"{round(a * 255):02x}" if a < 0.999 else "")


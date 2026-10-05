"""Cloudflare's tunnel tool (cloudflared) installed inside the project, only when the person asks ('ai-pc social setup-tunnel'):
the latest release's Windows build downloaded from GitHub (github.com/cloudflare/cloudflared), its SHA-256 compared with
the checksum Cloudflare publishes in the release notes, its Windows signature checked (valid, signed by Cloudflare),
then kept as tools/cloudflared/cloudflared.exe. Nothing is installed in Windows; deleting the folder removes it.
"""
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

from ai_pc.core.config import ROOT

DEST = ROOT / "tools" / "cloudflared" / "cloudflared.exe"
RELEASES = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
ASSET = "cloudflared-windows-amd64.exe"
NO_WINDOW = 0x08000000


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "AI-PC/1.0", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def checksum_from_notes(body, name=ASSET):
    """The SHA-256 Cloudflare lists for a file in a release's notes ('name: <64 hex>' or '<64 hex>  name')."""
    for line in (body or "").splitlines():
        if name in line:
            m = re.search(r"\b([0-9a-f]{64})\b", line, re.I)
            if m:
                return m.group(1).lower()
    return None


def signature(path):
    """Windows' own check of the file's signature -> (status, signer)."""
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
          "[pscustomobject]@{status=$s.Status.ToString(); signer=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    try:
        d = json.loads(r.stdout.strip() or "{}")
    except ValueError:
        d = {}
    return d.get("status"), d.get("signer") or ""


def install(fetch=_get, check_signature=signature, dest=DEST, say=print):
    rel = json.loads(fetch(RELEASES).decode("utf-8"))
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == ASSET), None)
    if not asset:
        raise RuntimeError(f"the latest cloudflared release ({rel.get('tag_name')}) has no {ASSET}")
    want = checksum_from_notes(rel.get("body"))
    if not want:
        raise RuntimeError("Cloudflare's release notes list no checksum for the Windows build; not installing it")
    say(f"Downloading cloudflared {rel.get('tag_name')} ({asset.get('size', 0) / 1e6:.0f} MB) from GitHub...")
    data = fetch(asset["browser_download_url"])
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise RuntimeError(f"the download does not match Cloudflare's checksum (got {got[:12]}..., expected {want[:12]}...); not installed")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".download")
    tmp.write_bytes(data)
    status, signer = check_signature(str(tmp))
    if status != "Valid" or "cloudflare" not in signer.lower():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"the file's Windows signature is not a valid Cloudflare one ({status}, {signer or 'no signer'}); not installed")
    tmp.replace(dest)
    (dest.parent / "SOURCE.txt").write_text(f"{asset['browser_download_url']}\nversion {rel.get('tag_name')}\nsha256 {got}\nsigner {signer}\n", encoding="utf-8")
    return {"path": str(dest), "version": rel.get("tag_name"), "sha256": got, "signer": signer}

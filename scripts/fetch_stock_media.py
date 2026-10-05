"""Download free stock clips (Mixkit, free licence) per genre into media/stock/<genre>/ for testing the video agent.

  .venv\\Scripts\\python.exe scripts/fetch_stock_media.py [genre ...]

Every file is checked with ffprobe (a real video stream, at least 4 s) before it is kept; a manifest records where each
clip came from (media/stock/manifest.json). Nothing is executed; only .mp4 files are written, inside the project.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "media" / "stock"
UA = {"User-Agent": "Mozilla/5.0"}
GENRES = {
    "travel": (["travel", "city", "beach", "landscape"], ["city", "beach", "travel", "street", "sunset", "mountain", "aerial", "tourist", "market", "ocean", "boat", "temple"]),
    "gym": (["gym", "fitness", "workout"], ["gym", "workout", "weight", "boxing", "training", "exercis", "running", "push", "rope", "athlete", "muscular"]),
    "cooking": (["cooking", "food", "kitchen"], ["cook", "chopping", "cutting", "frying", "pan", "kitchen", "salad", "pizza", "pasta", "chef", "vegetable", "dough", "plate", "sauce"]),
    "realestate": (["house", "interior", "home"], ["house", "living", "kitchen", "bedroom", "pool", "interior", "apartment", "home", "room", "villa", "modern"]),
    "car": (["car", "driving", "road"], ["car", "driving", "road", "wheel", "highway", "drive", "vehicle", "sports-car", "night"]),
    "wedding": (["wedding", "couple", "love"], ["wedding", "bride", "groom", "ring", "couple", "bouquet", "kiss", "dance", "love"]),
    "tech": (["technology", "smartphone", "laptop"], ["smartphone", "phone", "laptop", "tablet", "typing", "device", "screen", "computer", "headphones", "watch"]),
    "sports": (["sports", "soccer", "basketball", "skateboard"], ["soccer", "football", "basketball", "skate", "surf", "tennis", "ball", "player", "goal", "dunk", "kick"]),
    "nature": (["nature", "animals", "forest", "waterfall"], ["forest", "waterfall", "mountain", "animal", "bird", "deer", "ocean", "river", "lake", "wild", "fox", "eagle", "flowers"]),
    "party": (["party", "dance", "concert"], ["party", "dance", "dancing", "club", "concert", "lights", "crowd", "dj", "celebrat", "confetti"]),
}


def get(url, timeout=40):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def listing(cat, page=1):
    url = f"https://mixkit.co/free-stock-video/{cat}/" + (f"?page={page}" if page > 1 else "")
    try:
        html = get(url).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    seen, out = set(), []
    for slug, vid in re.findall(r"/free-stock-video/([a-z0-9-]+)-(\d+)/", html):
        if vid not in seen:
            seen.add(vid)
            out.append((vid, slug))
    return out


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(p)],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return None
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    dur = float(d.get("format", {}).get("duration") or 0)
    return {"seconds": round(dur, 2), "size": f"{v['width']}x{v['height']}"} if v and dur >= 4 else None


def fetch(genre, n=7):
    cats, words = GENRES[genre]
    d = OUT / genre
    d.mkdir(parents=True, exist_ok=True)
    have = sorted(d.glob("*.mp4"))
    if len(have) >= n:
        return [], have
    picked, seen = [], {p.stem.rsplit("-", 1)[-1] for p in have}
    for cat in cats:
        for page in (1, 2):
            for vid, slug in listing(cat, page):
                if vid in seen or not any(w in slug for w in words):
                    continue
                seen.add(vid)
                picked.append((vid, slug))
        if len(picked) >= 3 * n:
            break
    got, log = list(have), []
    for vid, slug in picked:
        if len(got) >= n:
            break
        dest = d / f"{slug[:50]}-{vid}.mp4"
        for q in ("720", "1080", "360"):
            try:
                data = get(f"https://assets.mixkit.co/videos/{vid}/{vid}-{q}.mp4", timeout=120)
            except Exception:  # noqa: BLE001
                continue
            if data[4:8] != b"ftyp":  # not an mp4
                continue
            dest.write_bytes(data)
            info = probe(dest)
            if info:
                got.append(dest)
                log.append({"genre": genre, "file": str(dest.relative_to(ROOT)), "source": f"https://mixkit.co/free-stock-video/{slug}-{vid}/",
                            "quality": q, "licence": "Mixkit Stock Video Free License", **info})
                break
            dest.unlink(missing_ok=True)
    return log, got


if __name__ == "__main__":
    genres = sys.argv[1:] or list(GENRES)
    man_p = OUT / "manifest.json"
    manifest = json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else []
    t0 = time.perf_counter()
    total_mb = 0.0
    for g in genres:
        log, got = fetch(g)
        manifest += log
        mb = sum(p.stat().st_size for p in got) / 1e6
        total_mb += mb
        print(f"{g:11} {len(got)} clips ({mb:.0f} MB): " + ", ".join(p.stem[:28] for p in got), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    man_p.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"done in {time.perf_counter() - t0:.0f} s, {total_mb:.0f} MB")

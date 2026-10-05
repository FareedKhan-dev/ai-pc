"""KeePassXC 2.7.12 (tools/keepassxc, portable; SHA-256 = GitHub's and its .DIGEST, GPG-signed by the KeePassXC release key,
Authenticode-signed): password vaults (.kdbx, encrypted with AES-256) made by keepassxc-cli: a vault with a master password,
optionally filled from a browser's password export (CSV: name, url, username, password; empty passwords get strong
generated ones), and strong passwords generated. Passwords only ever travel through a pipe to keepassxc-cli: never on a
command line, never in a file of ours, never in a reply. Checked by KeePassXC itself: every entry is in the vault with
its user name and password (compared in memory), and a wrong master password cannot open it.

  'keepassxc vault called Work with password <your master password>'   'keepassxc vault called Home from passwords.csv with password <...>'
  'keepassxc generate a password of 24 characters'
"""
import csv
import re
import subprocess
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "keepassxc", "KeePassXC: encrypted password vaults (.kdbx) with entries from a browser export, strong passwords; checked by KeePassXC"
EXAMPLES = ["keepassxc vault called Work with password <master password>", "keepassxc vault called Home from passwords.csv with password <...>",
            "keepassxc generate a password of 24 characters"]
CLI = ROOT / "tools" / "keepassxc" / "keepassxc-cli.exe"


def kp(args, secret_lines=()):
    """keepassxc-cli with its prompts answered through a pipe."""
    r = subprocess.run([str(CLI), *map(str, args)], input="".join(f"{s}\n" for s in secret_lines), capture_output=True, text=True,
                       encoding="utf-8", creationflags=0x08000000, timeout=120)
    return r.returncode == 0, r.stdout, r.stderr


def generate(length=20):
    ok, out, _ = kp(["generate", "-L", length, "-l", "-U", "-n", "-s", "--every-group"])
    return out.strip() if ok else None


def kdbx_version(path):
    """'3.1' / '4.0' for a KeePass database file, None for anything else."""
    head = Path(path).read_bytes()[:12]
    if head[:8] != bytes.fromhex("03d9a29a67fb4bb5"):
        return None
    return f"{int.from_bytes(head[10:12], 'little')}.{int.from_bytes(head[8:10], 'little')}"


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bkeepass(?:xc)?\b", c):
        return None
    if re.search(r"\bgenerate\b|\bnew password\b|\bstrong password\b", c) and not re.search(r"\bvault\b|\bdatabase\b", c):
        m = re.search(r"\b(\d{1,3})\s*(?:characters|chars|letters)?\b", c)
        return {"op": "generate", "length": max(8, min(128, int(m.group(1)))) if m else 20}
    pw = re.search(r"\b(?:master\s+)?password\s*(?:is\s*)?[:=]?\s*(\S+)", text, re.I)
    name = re.search(r"\b(?:vault|database)\s+(?:called|named)\s+['\"]?([\w -]+?)['\"]?(?:\s+(?:from|with)\b|$)", text, re.I)
    f = find_file(text, ctx, {".csv"})
    return {"op": "vault", "name": (name.group(1).strip() if name else "Passwords"), "master": pw.group(1).strip("'\"") if pw else None, "csv": f}


def run(op, ctx):
    if not CLI.exists():
        return "KeePassXC is not in tools/keepassxc."
    if op["op"] == "generate":
        p = generate(op["length"])
        if not p:
            return "KeePassXC could not generate a password."
        ok, out, _ = kp(["estimate", "-a"], [p])
        bits = re.search(r"Entropy\s+([\d.]+)", out)
        classes = [bool(re.search(r"[a-z]", p)), bool(re.search(r"[A-Z]", p)), bool(re.search(r"\d", p)), bool(re.search(r"[^A-Za-z0-9]", p))]
        return (f"Password from KeePassXC: {p}  (Checked: {len(p)} characters with lower case, upper case, digits and symbols" +
                (f"; KeePassXC estimates {float(bits.group(1)):.0f} bits of entropy" if bits else "") + ")." if all(classes) and len(p) == op["length"]
                else f"NOT right: {len(p)} characters, groups {classes}.")
    master = op.get("master")
    if not master or len(master) < 8:
        return "A vault needs a master password of at least 8 characters: say 'keepassxc vault called Work with password <your master password>'."
    out = (Path(ctx["out"]) / "keepassxc").resolve()
    out.mkdir(parents=True, exist_ok=True)
    db = out / f"{re.sub(r'[^A-Za-z0-9_-]+', '_', op['name'])}.kdbx"
    if db.exists():
        return f"{db.name} already exists in {out}: give the new vault another name (an existing vault is never overwritten)."
    ok, so, se = kp(["db-create", "--set-password", "-t", "1000", db], [master, master])  # unlocking tuned to ~1 s of work
    if not ok or not db.exists():
        return f"KeePassXC could not make the vault: {(se or so).strip()[-200:]}"
    rows = []
    if op.get("csv"):
        with open(op["csv"], encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                low = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
                title = low.get("name") or low.get("title") or low.get("url") or "Entry"
                rows.append({"title": re.sub(r"[/\\]", "-", title), "user": low.get("username") or low.get("user") or low.get("login") or "",
                             "url": low.get("url") or low.get("website") or "", "password": low.get("password") or ""})
    titles, generated = set(), 0
    for r in rows:
        base, n = r["title"], 2
        while r["title"] in titles:
            r["title"] = f"{base} ({n})"
            n += 1
        titles.add(r["title"])
        if not r["password"]:
            r["password"] = generate(20)
            generated += 1
        args = ["add", "-p"] + (["-u", r["user"]] if r["user"] else []) + (["--url", r["url"]] if r["url"] else []) + [db, r["title"]]
        kp(args, [master, r["password"]])
    ok_ls, listing, _ = kp(["ls", "-R", "-f", db], [master])
    stored = {ln.strip() for ln in listing.splitlines() if ln.strip() and not ln.strip().endswith("/")}
    same = 0
    for r in rows:
        ok_u, user, _ = kp(["show", "-q", "-a", "UserName", db, r["title"]], [master])
        ok_p, pw, _ = kp(["show", "-q", "-s", "-a", "Password", db, r["title"]], [master])
        same += int(ok_u and ok_p and user.strip() == r["user"] and pw.rstrip("\r\n") == r["password"])
    wrong, _, _ = kp(["ls", db], ["not-" + master])
    checks = [(f"KeePassXC made an encrypted KeePass vault (KDBX {kdbx_version(db)}, AES-256, unlocking tuned to about 1 second of work)",
               bool(kdbx_version(db))),
              (f"all {len(rows)} entries are in it with their user names and passwords (compared in memory)" if rows else "it opens with the master password",
               ok_ls and (same == len(rows) and {r["title"] for r in rows} <= stored)),
              ("a wrong master password cannot open it", not wrong)]
    bad = [w for w, good in checks if not good]
    return (f"KeePassXC vault {db} (open it in KeePassXC, KeePass or a phone app such as KeePassDX/Strongbox with your master password)" +
            (f" with {len(rows)} entries from {Path(op['csv']).name}" + (f", {generated} given new strong passwords" if generated else "") if rows else "") + ". " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ".") +
            (f" {Path(op['csv']).name} still holds the passwords as plain text: delete it once you are happy with the vault." if rows else ""))

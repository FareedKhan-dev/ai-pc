"""The AI PC chat as a page in your browser, on this PC only (127.0.0.1): type, attach files, or hold the microphone
button for a voice note; replies and the files made (open or download them) appear in the conversation.

Safe by design: the server answers only on 127.0.0.1 (no firewall question, nothing reachable from the network); each
run has a secret that the page sends with every request, so another web page open in the browser cannot drive the
chat; only files that belong to the chat (sent or made) can be opened through it.

  serve(AIPCChat.start(), port=8770)        (ai-pc web)
"""

import html
import json
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI PC</title><style>
:root{--bg:#f6f7f9;--fg:#15181d;--muted:#5d6673;--me:#dbeafe;--bot:#ffffff;--line:#d9dde3;--accent:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e8ebef;--muted:#9aa4b2;--me:#1e3a5f;--bot:#1b2026;--line:#2a313a;--accent:#60a5fa}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,Segoe UI,sans-serif;height:100vh;display:flex;flex-direction:column}
header{padding:12px 16px;border-bottom:1px solid var(--line);font-weight:600}header span{color:var(--muted);font-weight:400;font-size:14px;margin-left:8px}
#log{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.m{max-width:820px;padding:10px 14px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word;border:1px solid var(--line)}
.me{align-self:flex-end;background:var(--me)}.bot{align-self:flex-start;background:var(--bot)}
.files a{display:inline-block;margin:6px 8px 0 0;color:var(--accent)}.files img{max-width:320px;max-height:220px;display:block;margin-top:6px;border-radius:8px}
.files video{max-width:420px;display:block;margin-top:6px;border-radius:8px}.heard{color:var(--muted);font-size:14px}
form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line);align-items:center;flex-wrap:wrap}
#t{flex:1;min-width:200px;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bot);color:var(--fg);font:inherit}
button,label.b{padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--bot);color:var(--fg);font:inherit;cursor:pointer}
button.go{background:var(--accent);color:#fff;border-color:var(--accent)}#mic.rec{background:#dc2626;color:#fff}#att{color:var(--muted);font-size:14px}
</style></head><body><header>AI PC<span>one chat for everything on this PC: type, attach, or hold the mic</span></header>
<div id="log"></div>
<form id="f"><label class="b">Attach<input id="file" type="file" multiple hidden></label><span id="att"></span>
<input id="t" autocomplete="off" placeholder="e.g. add a glow effect to my video, then send it to slack #team"><button id="mic" type="button" title="hold to talk">Hold to talk</button>
<button class="go" type="submit">Send</button></form>
<script>
const TOKEN="__TOKEN__";const log=document.getElementById('log');let files=[];
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function add(cls,text,made,heard){const d=document.createElement('div');d.className='m '+cls;
 d.innerHTML=(heard?'<div class="heard">heard: "'+esc(heard)+'"</div>':'')+esc(text);
 if(made&&made.length){const f=document.createElement('div');f.className='files';
  for(const p of made){const u='/file?token='+TOKEN+'&path='+encodeURIComponent(p);const n=p.split(/[\\\\/]/).pop();
   if(/\\.(png|jpe?g|gif|webp)$/i.test(n))f.innerHTML+='<img src="'+u+'" alt="">';
   else if(/\\.(mp4|webm|mov)$/i.test(n))f.innerHTML+='<video src="'+u+'" controls></video>';
   f.innerHTML+='<a href="'+u+'" download="'+esc(n)+'">'+esc(n)+'</a>'}d.appendChild(f)}
 log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
async function send(text,voiceBlob){const fd=new FormData();fd.append('message',text||'');for(const f of files)fd.append('files',f,f.name);
 if(voiceBlob)fd.append('voice',voiceBlob,'voice.webm');
 add('me',(text||(voiceBlob?'(voice note)':''))+(files.length?'\\n['+files.map(f=>f.name).join(', ')+']':''));files=[];document.getElementById('att').textContent='';
 const w=add('bot','working...');
 try{const r=await fetch('/say',{method:'POST',headers:{'X-AIPC-Token':TOKEN},body:fd});const j=await r.json();w.remove();add('bot',j.reply,j.files,j.heard)}
 catch(e){w.textContent='Could not reach the AI PC: '+e}}
document.getElementById('f').onsubmit=e=>{e.preventDefault();const t=document.getElementById('t');if(!t.value.trim()&&!files.length)return;send(t.value.trim());t.value=''};
document.getElementById('file').onchange=e=>{files=[...e.target.files];document.getElementById('att').textContent=files.map(f=>f.name).join(', ')};
let rec,chunks=[];const mic=document.getElementById('mic');
async function startRec(){try{const s=await navigator.mediaDevices.getUserMedia({audio:true});rec=new MediaRecorder(s);chunks=[];
 rec.ondataavailable=e=>chunks.push(e.data);rec.onstop=()=>{s.getTracks().forEach(t=>t.stop());send(document.getElementById('t').value.trim(),new Blob(chunks,{type:'audio/webm'}));
 document.getElementById('t').value=''};rec.start();mic.classList.add('rec');mic.textContent='Listening... release to send'}catch(e){add('bot','The microphone is not available: '+e)}}
function stopRec(){if(rec&&rec.state==='recording'){rec.stop();mic.classList.remove('rec');mic.textContent='Hold to talk'}}
mic.onmousedown=startRec;mic.onmouseup=stopRec;mic.onmouseleave=stopRec;mic.ontouchstart=e=>{e.preventDefault();startRec()};mic.ontouchend=stopRec;
</script></body></html>"""


def parse_multipart(body, ctype):
    """{"fields": {name: str}, "files": [(field, filename, bytes)]} from a multipart/form-data body (standard library only)."""
    boundary = None
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
    out = {"fields": {}, "files": []}
    if not boundary:
        return out
    for chunk in body.split(b"--" + boundary.encode()):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head, _, data = chunk.partition(b"\r\n\r\n")
        disp = next((ln for ln in head.decode("utf-8", "replace").split("\r\n") if ln.lower().startswith("content-disposition")), "")
        name = (disp.split('name="', 1)[1].split('"', 1)[0]) if 'name="' in disp else ""
        if 'filename="' in disp:
            fname = disp.split('filename="', 1)[1].split('"', 1)[0]
            out["files"].append((name, Path(fname).name or "file", data))
        else:
            out["fields"][name] = data.decode("utf-8", "replace")
    return out


def serve(chat, port=8770, open_browser=False, ready=None):
    token = secrets.token_urlsafe(24)
    inbox = Path(chat.folder) / "inbox"
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/":
                data = PAGE.replace("__TOKEN__", token).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if u.path == "/file":
                if (q.get("token") or [""])[0] != token:
                    return self._json(403, {"error": "not allowed"})
                want = (q.get("path") or [""])[0]
                allowed = {a["path"].lower(): a["path"] for a in chat.arts.items}
                p = allowed.get(want.lower())
                if not p or not Path(p).is_file():
                    return self._json(404, {"error": "not a file of this chat"})
                data = Path(p).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'inline; filename="{html.escape(Path(p).name)}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._json(404, {"error": "no such page"})

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/say" or self.headers.get("X-AIPC-Token") != token:
                return self._json(403, {"error": "not allowed"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 500 * 1024 * 1024:
                return self._json(413, {"error": "too big"})
            form = parse_multipart(self.rfile.read(n), self.headers.get("Content-Type", ""))
            inbox.mkdir(parents=True, exist_ok=True)
            files, voice = [], None
            for field, fname, data in form["files"]:
                dst = inbox / fname
                k = 2
                while dst.exists() and dst.stat().st_size != len(data):
                    dst = inbox / f"{Path(fname).stem}_{k}{Path(fname).suffix}"
                    k += 1
                dst.write_bytes(data)
                if field == "voice":
                    voice = str(dst)
                else:
                    files.append(str(dst))
            with lock:  # one request at a time: the programs keep one conversation each
                r = chat.say(form["fields"].get("message", ""), files=files, voice=voice)
            self._json(200, {"reply": str(r), "files": list(r.files), "heard": r.heard})

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    if ready:
        ready(url, token, srv)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()

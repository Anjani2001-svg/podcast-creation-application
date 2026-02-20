#!/usr/bin/env python3
"""
app.py  –  Podcast Video Creator  (Flask web UI)

Windows:
  1) Run ngrok:         ngrok http 5000
  2) Set env + run:     $env:PUBLIC_BASE_URL="https://xxxx.ngrok-free.app"; python app.py
  3) Open locally:      http://localhost:5000

Shotstack Cloud MUST be able to fetch audio/image via PUBLIC_BASE_URL.
"""

import os, uuid, threading, time, json, urllib.request, urllib.error
from pathlib import Path
from flask import Flask, request, render_template_string, jsonify, send_file, abort

from podcast_creator import create_thumbnail, create_video

BASE    = Path(__file__).parent
UPLOADS = BASE / "uploads";  UPLOADS.mkdir(exist_ok=True)
OUTPUTS = BASE / "outputs";  OUTPUTS.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

jobs: dict[str, dict] = {}

# Example: https://abcd-1234.ngrok-free.app
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def public_url(path: str) -> str:
    """Build a public URL for Shotstack to fetch assets from your Flask server."""
    if not PUBLIC_BASE_URL:
        raise RuntimeError(
            "PUBLIC_BASE_URL is not set.\n"
            "On Windows PowerShell run:\n"
            '  $env:PUBLIC_BASE_URL="https://YOUR-NGROK-URL"\n'
            "then: python app.py\n"
        )
    if not path.startswith("/"):
        path = "/" + path
    return PUBLIC_BASE_URL + path


# ─────────────────────────────────────────────────────────────────
# SHOTSTACK  RENDERER (Sandbox)
# Base URL: https://api.shotstack.io/stage
# ─────────────────────────────────────────────────────────────────
def render_via_shotstack(image_path: Path, audio_path: Path,
                         api_key: str, job_id: str) -> Path:

    BASE_URL = "https://api.shotstack.io/stage"
    HEADERS  = {
        "Content-Type": "application/json",
        "Accept":        "application/json",
        "x-api-key":     api_key,
    }

    def ss_post(endpoint, payload):
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            BASE_URL + endpoint, data=data,
            headers=HEADERS, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Shotstack {e.code} on {endpoint}: {body}") from e

    def ss_get(endpoint):
        req = urllib.request.Request(BASE_URL + endpoint, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Shotstack {e.code} on {endpoint}: {body}") from e

    # Public URLs served by THIS Flask app (via ngrok)
    image_url = public_url(f"/asset/{job_id}/{image_path.name}")
    audio_url = public_url(f"/asset/{job_id}/{audio_path.name}")

    jobs[job_id]["message"] = "Submitting render to Shotstack…"

    render_payload = {
        "timeline": {
            "tracks": [
                {
                    # Track 0: audio
                    "clips": [{
                        "asset": {"type": "audio", "src": audio_url, "volume": 1},
                        "start": 0,
                        "length": "auto"
                    }]
                },
                {
                    # Track 1: static image
                    "clips": [{
                        "asset": {"type": "image", "src": image_url},
                        "start": 0,
                        "length": 7200,
                        "fit": "cover"
                    }]
                }
            ]
        },
        "output": {
            "format": "mp4",
            "resolution": "hd",
            "fps": 25,
            "size": {"width": 1920, "height": 1080}
        }
    }

    resp      = ss_post("/render", render_payload)
    render_id = resp["response"]["id"]

    # Poll until done
    for _ in range(150):   # ~12.5 min max
        time.sleep(5)
        status_resp = ss_get(f"/render/{render_id}")
        status      = status_resp["response"]["status"]
        jobs[job_id]["message"] = f"Shotstack: {status}…"

        if status == "done":
            video_url = status_resp["response"]["url"]
            break
        if status == "failed":
            err = status_resp["response"].get("error", "unknown error")
            raise RuntimeError(f"Shotstack render failed: {err}")
    else:
        raise RuntimeError("Shotstack timed out after ~12 minutes.")

    # Download MP4
    jobs[job_id]["message"] = "Downloading video from Shotstack…"
    out_path = OUTPUTS / f"{job_id}.mp4"
    urllib.request.urlretrieve(video_url, str(out_path))
    return out_path


# ─────────────────────────────────────────────────────────────────
# BACKGROUND JOB
# ─────────────────────────────────────────────────────────────────
def run_job(job_id, template_path, audio_path,
            course, unit_name, unit_number, backend, shotstack_key):
    try:
        jobs[job_id]["message"] = "Generating thumbnail…"
        thumb = OUTPUTS / f"{job_id}_thumb.jpg"
        create_thumbnail(str(template_path), course, unit_name,
                         unit_number, str(thumb))

        video_file = f"{job_id}.mp4"

        if backend == "shotstack":
            # Fail early with a clear message if ngrok url isn't set
            _ = public_url("/health")
            render_via_shotstack(thumb, audio_path, shotstack_key, job_id)
        else:
            jobs[job_id]["message"] = "Rendering video with ffmpeg…"
            create_video(str(thumb), str(audio_path),
                         str(OUTPUTS / video_file))

        jobs[job_id] = {
            "status":  "done",
            "message": "Done!",
            "thumb":   thumb.name,
            "video":   video_file,
        }

    except Exception as e:
        jobs[job_id] = {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return "ok"

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/create", methods=["POST"])
def create():
    course      = request.form.get("course",      "").strip()
    unit_name   = request.form.get("unit_name",   "").strip()
    unit_number = request.form.get("unit_number", "").strip()
    backend     = request.form.get("backend",     "local")
    ss_key      = request.form.get("shotstack_key","").strip()

    if not all([course, unit_name, unit_number]):
        return jsonify(error="Please fill in all text fields."), 400
    if backend == "shotstack" and not ss_key:
        return jsonify(error="Please enter your Shotstack API key."), 400

    tmpl_file  = request.files.get("template")
    audio_file = request.files.get("audio")
    if not tmpl_file  or not tmpl_file.filename:
        return jsonify(error="Please upload a thumbnail template."), 400
    if not audio_file or not audio_file.filename:
        return jsonify(error="Please upload an audio file."), 400

    job_id = uuid.uuid4().hex[:10]
    tmpl  = UPLOADS / f"{job_id}_tmpl{Path(tmpl_file.filename).suffix}"
    audio = UPLOADS / f"{job_id}_audio{Path(audio_file.filename).suffix}"
    tmpl_file.save(tmpl)
    audio_file.save(audio)

    jobs[job_id] = {"status": "running", "message": "Starting…"}
    threading.Thread(
        target=run_job,
        args=(job_id, tmpl, audio, course, unit_name,
              unit_number, backend, ss_key),
        daemon=True
    ).start()
    return jsonify(job_id=job_id)

@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {"status": "unknown"}))

@app.route("/download/<filename>")
def download(filename):
    p = OUTPUTS / filename
    if not p.exists():
        return "File not found", 404
    return send_file(str(p), as_attachment=True)

# Public asset endpoint so Shotstack can download your thumbnail/audio
@app.route("/asset/<job_id>/<filename>")
def asset(job_id, filename):
    safe = filename.replace("..", "").replace("/", "").replace("\\", "")

    # Allow only assets that start with this job_id prefix
    if not safe.startswith(job_id + "_"):
        abort(404)

    p_out = OUTPUTS / safe
    p_up  = UPLOADS / safe

    if p_out.exists():
        return send_file(str(p_out), as_attachment=False)
    if p_up.exists():
        return send_file(str(p_up), as_attachment=False)

    abort(404)


# ─────────────────────────────────────────────────────────────────
# HTML / CSS / JS (your original)
# ─────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Podcast Video Creator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --teal:#00939a;--dark:#071e22;--mid:#0e3338;--card:#122a2e;
  --border:rgba(0,147,154,.25);--text:#d4eff1;--sub:#7bb8bc;--white:#fff;--r:14px
}
html,body{min-height:100vh;background:var(--dark);color:var(--text);
  font-family:'DM Sans',sans-serif;font-size:15px}
body::before{content:'';position:fixed;inset:0;z-index:0;
  background:radial-gradient(ellipse 80% 60% at 10% 0%,rgba(0,147,154,.18),transparent 60%),
             radial-gradient(ellipse 60% 50% at 90% 100%,rgba(0,147,154,.12),transparent 55%);
  pointer-events:none}
.wrap{position:relative;z-index:1;max-width:760px;margin:0 auto;padding:48px 24px 80px}
header{text-align:center;margin-bottom:40px}
.logo{display:inline-flex;align-items:center;gap:12px;
  background:linear-gradient(135deg,var(--teal),#00c2cb);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  font-family:'Space Grotesk',sans-serif;font-size:2rem;font-weight:700;letter-spacing:-.5px}
header p{margin-top:8px;color:var(--sub);font-size:.9rem}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:32px 36px;box-shadow:0 8px 32px rgba(0,0,0,.45)}
.sec{font-family:'Space Grotesk',sans-serif;font-size:.7rem;font-weight:500;
  letter-spacing:.12em;text-transform:uppercase;color:var(--teal);
  margin-bottom:16px;display:flex;align-items:center;gap:8px}
.sec::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--border),transparent)}
.uploads{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:26px}
.dz{border:2px dashed var(--border);border-radius:var(--r);padding:24px 14px;
  text-align:center;cursor:pointer;transition:.2s;position:relative}
.dz:hover{border-color:var(--teal);background:rgba(0,147,154,.07)}
.dz.filled{border-style:solid;border-color:var(--teal)}
.dz input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.dz-icon{font-size:1.8rem;margin-bottom:6px}
.dz-title{font-weight:600;font-size:.9rem;color:var(--white);margin-bottom:3px}
.dz-hint{font-size:.78rem;color:var(--sub)}
.dz-name{font-size:.78rem;color:var(--teal);margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fields{display:flex;flex-direction:column;gap:14px;margin-bottom:22px}
.field label{display:block;font-size:.78rem;font-weight:500;color:var(--sub);margin-bottom:5px}
.field .hint{font-size:.7rem;color:#4a8a8e;margin-top:3px}
.field input{width:100%;background:var(--mid);border:1px solid var(--border);
  border-radius:8px;padding:10px 14px;color:var(--white);
  font-family:'DM Sans',sans-serif;font-size:.93rem;outline:none;transition:.2s}
.field input:focus{border-color:var(--teal);box-shadow:0 0 0 3px rgba(0,147,154,.15)}
.field input::placeholder{color:#3a6e73}
.bk-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:22px}
.bk{border:1px solid var(--border);border-radius:10px;padding:14px;
  background:var(--mid);cursor:pointer;text-align:center;transition:.2s}
.bk:hover{border-color:var(--teal)}
.bk.active{border-color:var(--teal);background:rgba(0,147,154,.1)}
.bk-icon{font-size:1.5rem;margin-bottom:5px}
.bk-label{font-weight:600;font-size:.88rem;color:var(--white)}
.bk.active .bk-label{color:var(--teal)}
.bk-desc{font-size:.74rem;color:var(--sub);margin-top:2px}
#ss-row{display:none;margin-bottom:20px}
#ss-row.show{display:block}
.ss-note{font-size:.78rem;color:var(--sub);margin-top:6px;line-height:1.5}
.ss-note a{color:var(--teal);text-decoration:none}
.ss-note a:hover{text-decoration:underline}
.btn{width:100%;padding:14px;background:linear-gradient(135deg,var(--teal),#00b0b8);
  color:#fff;font-family:'Space Grotesk',sans-serif;font-size:.98rem;font-weight:700;
  border:none;border-radius:10px;cursor:pointer;
  box-shadow:0 4px 18px rgba(0,147,154,.35);
  display:flex;align-items:center;justify-content:center;gap:9px;transition:.2s}
.btn:hover:not(:disabled){opacity:.9;transform:translateY(-1px)}
.btn:disabled{opacity:.5;cursor:not-allowed}
#status-box{margin-top:24px;display:none}
.s-inner{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:22px 26px}
.pbar-w{height:4px;background:var(--mid);border-radius:2px;margin-bottom:14px;overflow:hidden}
.pbar{height:100%;background:linear-gradient(90deg,var(--teal),#00d4de);
  width:40%;animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-150%)}100%{transform:translateX(400%)}}
.s-row{display:flex;align-items:center;gap:10px}
.spinner{width:18px;height:18px;border:2.5px solid rgba(0,147,154,.3);
  border-top-color:var(--teal);border-radius:50%;animation:spin .7s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}
.s-msg{font-weight:500;color:var(--white);font-size:.93rem}
#result{display:none}
.r-title{font-family:'Space Grotesk',sans-serif;font-size:1rem;font-weight:700;
  color:#4ee8c4;margin-bottom:16px;display:flex;align-items:center;gap:7px}
.r-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.dl{display:flex;align-items:center;gap:9px;padding:12px 16px;
  background:var(--mid);border:1px solid var(--border);border-radius:10px;
  color:var(--white);text-decoration:none;font-weight:500;font-size:.88rem;transition:.2s}
.dl:hover{background:rgba(0,147,154,.15);border-color:var(--teal)}
.dl svg{color:var(--teal);flex-shrink:0}
.err{color:#ff8a80;font-weight:500;display:flex;align-items:center;gap:8px;font-size:.9rem}
@media(max-width:540px){.card{padding:22px 18px}.uploads,.bk-row,.r-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="logo">
    <svg width="30" height="30" viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="15" stroke="url(#g)" stroke-width="2"/>
      <path d="M11 10v12M16 7v18M21 10v12" stroke="url(#g)" stroke-width="2.2" stroke-linecap="round"/>
      <defs><linearGradient id="g" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
        <stop stop-color="#00939a"/><stop offset="1" stop-color="#00d4de"/>
      </linearGradient></defs>
    </svg>
    Podcast Video Creator
  </div>
  <p>Upload thumbnail + audio → branded MP4 in minutes</p>
</header>

<div class="card">

  <div class="sec">Media files</div>
  <div class="uploads">
    <div class="dz" id="dz-thumb">
      <input type="file" id="inp-thumb" accept="image/*" onchange="fileChosen('thumb',this)">
      <div class="dz-icon">🖼️</div>
      <div class="dz-title">Thumbnail</div>
      <div class="dz-hint">JPG or PNG — no text</div>
      <div class="dz-name" id="name-thumb"></div>
    </div>
    <div class="dz" id="dz-audio">
      <input type="file" id="inp-audio" accept="audio/*" onchange="fileChosen('audio',this)">
      <div class="dz-icon">🎙️</div>
      <div class="dz-title">Audio</div>
      <div class="dz-hint">MP3 · WAV · M4A · AAC</div>
      <div class="dz-name" id="name-audio"></div>
    </div>
  </div>

  <div class="sec">Episode details</div>
  <div class="fields">
    <div class="field">
      <label>Course Name</label>
      <input type="text" id="course" placeholder="Level 7 Extended Diploma in Computing Technologies (Networking) - RQF">
      <div class="hint">Montserrat ExtraBold · 50 pt</div>
    </div>
    <div class="field">
      <label>Unit Name</label>
      <input type="text" id="unit-name" placeholder="Managing Innovation and Change in Computing">
      <div class="hint">Montserrat ExtraBold · 50 pt</div>
    </div>
    <div class="field">
      <label>Unit Number / Code</label>
      <input type="text" id="unit-num" placeholder="D/618/7843">
      <div class="hint">Montserrat Medium · 36 pt</div>
    </div>
  </div>

  <div class="sec">Video rendering</div>
  <div class="bk-row">
    <div class="bk active" id="bk-local" onclick="setBk('local')">
      <div class="bk-icon">💻</div>
      <div class="bk-label">Local (ffmpeg)</div>
      <div class="bk-desc">Free · runs on your PC</div>
    </div>
    <div class="bk" id="bk-ss" onclick="setBk('shotstack')">
      <div class="bk-icon">☁️</div>
      <div class="bk-label">Shotstack Cloud</div>
      <div class="bk-desc">No ffmpeg · free tier</div>
    </div>
  </div>

  <div id="ss-row">
    <div class="field">
      <label>Shotstack API Key (Sandbox)</label>
      <input type="text" id="ss-key" placeholder="aYhBH0b6qmgUBK2t…">
      <div class="ss-note">
        Get free key → <a href="https://shotstack.io" target="_blank">shotstack.io</a>
        → Dashboard → API Keys → copy the <strong>Sandbox</strong> key
      </div>
    </div>
  </div>

  <button class="btn" id="submit-btn" onclick="go()">
    <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
    Create Video
  </button>

  <div id="status-box">
    <div class="s-inner">
      <div id="working">
        <div class="pbar-w"><div class="pbar"></div></div>
        <div class="s-row">
          <div class="spinner"></div>
          <span class="s-msg" id="s-msg">Processing…</span>
        </div>
      </div>
      <div id="result">
        <div class="r-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          Your video is ready!
        </div>
        <div class="r-grid">
          <a class="dl" id="dl-vid" href="#" download>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            Download Video (.mp4)
          </a>
          <a class="dl" id="dl-th" href="#" download>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            Download Thumbnail
          </a>
        </div>
      </div>
      <div class="err" id="err" style="display:none">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
        <span id="err-txt"></span>
      </div>
    </div>
  </div>

</div>
</div>

<script>
let bk = 'local', timer = null;

function setBk(v) {
  bk = v;
  document.getElementById('bk-local').classList.toggle('active', v==='local');
  document.getElementById('bk-ss').classList.toggle('active', v==='shotstack');
  document.getElementById('ss-row').classList.toggle('show', v==='shotstack');
}

function fileChosen(t, inp) {
  const n = inp.files[0]?.name||'';
  document.getElementById('name-'+t).textContent = n;
  document.getElementById('dz-'+t).classList.toggle('filled',!!n);
}

async function go() {
  const course = document.getElementById('course').value.trim();
  const uname  = document.getElementById('unit-name').value.trim();
  const unum   = document.getElementById('unit-num').value.trim();
  const thumb  = document.getElementById('inp-thumb').files[0];
  const audio  = document.getElementById('inp-audio').files[0];
  const ssKey  = document.getElementById('ss-key').value.trim();

  if (!course||!uname||!unum) return alert('Please fill in all text fields.');
  if (!thumb)  return alert('Please upload a thumbnail.');
  if (!audio)  return alert('Please upload an audio file.');
  if (bk==='shotstack'&&!ssKey) return alert('Please enter your Shotstack API key.');

  const btn = document.getElementById('submit-btn');
  btn.disabled = true;

  const fd = new FormData();
  fd.append('course',course); fd.append('unit_name',uname);
  fd.append('unit_number',unum); fd.append('template',thumb);
  fd.append('audio',audio); fd.append('backend',bk);
  fd.append('shotstack_key',ssKey);

  document.getElementById('working').style.display='block';
  document.getElementById('result').style.display='none';
  document.getElementById('err').style.display='none';
  document.getElementById('status-box').style.display='block';
  msg('Uploading…');

  try {
    const r = await fetch('/create',{method:'POST',body:fd});
    const d = await r.json();
    if(!r.ok) throw new Error(d.error||'Server error');
    poll(d.job_id);
  } catch(e) { showErr(e.message); btn.disabled=false; }
}

function msg(t){document.getElementById('s-msg').textContent=t}

function poll(id){
  if(timer)clearInterval(timer);
  timer=setInterval(async()=>{
    const r=await fetch('/status/'+id);
    const d=await r.json();
    msg(d.message||'…');
    if(d.status==='done'){clearInterval(timer);done(d.video,d.thumb);document.getElementById('submit-btn').disabled=false;}
    else if(d.status==='error'){clearInterval(timer);showErr(d.message);document.getElementById('submit-btn').disabled=false;}
  },2000);
}

function done(vid,th){
  document.getElementById('working').style.display='none';
  document.getElementById('dl-vid').href='/download/'+vid;
  document.getElementById('dl-th').href='/download/'+th;
  document.getElementById('result').style.display='block';
}

function showErr(m){
  document.getElementById('working').style.display='none';
  document.getElementById('err-txt').textContent=m;
  document.getElementById('err').style.display='flex';
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    print("🎙  Podcast Video Creator  →  http://localhost:5000")
    if not PUBLIC_BASE_URL:
        print("⚠️  For Shotstack Cloud: run ngrok and set PUBLIC_BASE_URL to the https URL.")
        print('   PowerShell example:')
        print('     $env:PUBLIC_BASE_URL="https://xxxx.ngrok-free.app"')
        print("     python app.py")
    app.run(debug=False, host="0.0.0.0", port=5000)
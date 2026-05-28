#!/usr/bin/env python3
"""Luna Voice status dashboard.

A tiny stdlib-only HTTP server that aggregates systemd service state and the
voice service's Prometheus /metrics endpoint into a single same-origin JSON
feed, and serves a full-screen kiosk dashboard that polls it.

Run:  python3 server.py            (defaults: dashboard :8090, metrics :8001)
"""

import json
import re
import subprocess
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

DASH_PORT = 8090
METRICS_URL = "http://localhost:8001/metrics"
SERVICE = "luna-voice.service"


def _systemd_state():
    """Return active/sub state, main PID, and uptime (s) for the service."""
    try:
        out = subprocess.run(
            ["systemctl", "show", SERVICE,
             "--property=ActiveState,SubState,ExecMainPID"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    except Exception:
        props = {}

    pid = props.get("ExecMainPID", "0")
    uptime = None
    if pid and pid != "0":
        try:
            etimes = subprocess.run(
                ["ps", "-o", "etimes=", "-p", pid],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            uptime = int(etimes) if etimes else None
        except Exception:
            uptime = None

    return {
        "active": props.get("ActiveState", "unknown"),
        "sub": props.get("SubState", "unknown"),
        "pid": int(pid) if pid.isdigit() else 0,
        "uptime_seconds": uptime,
    }


# Pull a single un-labelled metric value, e.g. voice_conversations_total
_PLAIN = lambda text, name: _grab(text, rf"^{name}\s+([0-9.e+-]+)")
# Pull a labelled metric value, e.g. voice_stt_requests_total{{status="ok"}}
_LABELLED = lambda text, name, lbl: _grab(
    text, rf'^{name}\{{[^}}]*{lbl}[^}}]*\}}\s+([0-9.e+-]+)'
)


def _grab(text, pattern):
    m = re.search(pattern, text, re.MULTILINE)
    return float(m.group(1)) if m else None


def _metrics():
    """Fetch and parse the key voice metrics. Returns (data, reachable)."""
    try:
        with urllib.request.urlopen(METRICS_URL, timeout=3) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        return {}, False

    return {
        "listening": _PLAIN(text, "voice_listening"),
        "wakeword_detections": _PLAIN(text, "voice_wakeword_detections_total"),
        "false_triggers": _PLAIN(text, "voice_wakeword_false_triggers_total"),
        "conversations": _PLAIN(text, "voice_conversations_total"),
        "tts_requests": _PLAIN(text, "voice_tts_requests_total"),
        "stream_recoveries": _PLAIN(text, "voice_stream_dead_recoveries_total"),
        "stt_ok": _LABELLED(text, "voice_stt_requests_total", 'status="ok"'),
        "stt_error": _LABELLED(text, "voice_stt_requests_total", 'status="error"'),
        "brain_ok": _LABELLED(text, "voice_brain_requests_total", 'status="ok"'),
        "brain_error": _LABELLED(text, "voice_brain_requests_total", 'status="error"'),
    }, True


def build_status():
    svc = _systemd_state()
    metrics, reachable = _metrics()

    if svc["active"] != "active":
        state = "offline"
    elif not reachable:
        state = "starting"
    elif metrics.get("listening") == 1.0:
        state = "listening"
    else:
        state = "processing"

    return {
        "state": state,
        "service": svc,
        "metrics": metrics,
        "metrics_reachable": reachable,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(build_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/" or self.path == "/index.html":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Luna Voice</title>
<style>
  :root { --bg:#0b0f17; --fg:#e8eef7; --muted:#7d8aa0; --card:#141b29; }
  * { box-sizing:border-box; margin:0; padding:0; }
  html,body { height:100%; }
  /* All sizes use vmin so the layout scales to any resolution or zoom and
     never overflows — content stays in normal flow, so nothing overlaps. */
  body {
    background:var(--bg); color:var(--fg); cursor:none;
    font-family:-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap:3vmin; height:100vh; overflow:hidden; transition:background .6s ease;
    padding:9vmin 4vmin 4vmin; -webkit-user-select:none; user-select:none;
  }
  body.listening   { background:radial-gradient(circle at 50% 38%, #0d2c1e, #0b0f17 70%); }
  body.processing  { background:radial-gradient(circle at 50% 38%, #102036, #0b0f17 70%); }
  body.starting    { background:radial-gradient(circle at 50% 38%, #2e2710, #0b0f17 70%); }
  body.offline     { background:radial-gradient(circle at 50% 38%, #2e1014, #0b0f17 70%); }
  .orb {
    width:26vmin; height:26vmin; border-radius:50%; flex:0 0 auto;
    display:flex; align-items:center; justify-content:center; transition:all .5s ease;
  }
  .orb .core { width:13vmin; height:13vmin; border-radius:50%; transition:all .5s ease; }
  .listening  .orb .core { background:#27c281; box-shadow:0 0 6vmin 1vmin #27c28188; animation:pulse 2s ease-in-out infinite; }
  .processing .orb .core { background:#3b82f6; box-shadow:0 0 6vmin 1vmin #3b82f688; animation:spin 1.1s linear infinite; border:1.4vmin solid #3b82f6; border-top:1.4vmin solid #0b0f1733; }
  .starting   .orb .core { background:#d4a017; box-shadow:0 0 6vmin 1vmin #d4a01788; animation:pulse 1.2s ease-in-out infinite; }
  .offline    .orb .core { background:#b3303c; box-shadow:0 0 6vmin 1vmin #b3303c88; }
  @keyframes pulse { 0%,100%{ transform:scale(1); opacity:1; } 50%{ transform:scale(1.18); opacity:.75; } }
  @keyframes spin  { to { transform:rotate(360deg); } }
  .label { font-size:8vmin; font-weight:700; letter-spacing:.04em; text-transform:uppercase; line-height:1; text-align:center; }
  .sub   { font-size:2.6vmin; color:var(--muted); text-align:center; }
  .stats {
    display:flex; justify-content:center; gap:1.6vmin; flex-wrap:wrap;
    margin-top:1vmin; max-width:96vw;
  }
  .stat {
    background:var(--card); border-radius:1.6vmin; padding:1.8vmin 2.6vmin;
    min-width:16vmin; text-align:center;
  }
  .stat .v { font-size:3.8vmin; font-weight:700; line-height:1; }
  .stat .k { font-size:1.5vmin; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; margin-top:.8vmin; }
  .err .v { color:#ff6b6b; }
  .stale { position:fixed; top:2vmin; right:2.5vmin; font-size:1.8vmin; color:#ff6b6b; opacity:0; transition:opacity .3s; }
  .stale.on { opacity:1; }
  .title { position:fixed; top:2vmin; left:2.5vmin; font-size:1.9vmin; color:var(--muted); letter-spacing:.2em; text-transform:uppercase; }
</style>
</head>
<body class="starting">
  <div class="title">Luna Voice</div>
  <div class="stale" id="stale">⚠ no update</div>
  <div class="orb"><div class="core"></div></div>
  <div class="label" id="label">Connecting…</div>
  <div class="sub" id="sub">&nbsp;</div>
  <div class="stats" id="stats"></div>

<script>
const LABELS = {
  listening:  ["Listening",  "Waiting for “hey luna”"],
  processing: ["Processing", "Working on a request"],
  starting:   ["Starting",   "Service up, metrics not ready"],
  offline:    ["Offline",    "luna-voice.service is not running"],
};
function fmtUptime(s){
  if(s==null) return "—";
  const d=Math.floor(s/86400), h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60);
  if(d) return `${d}d ${h}h`;
  if(h) return `${h}h ${m}m`;
  return `${m}m`;
}
function n(x){ return (x==null)?"—":Math.round(x); }
async function tick(){
  try {
    const r = await fetch("/api/status", {cache:"no-store"});
    const s = await r.json();
    document.getElementById("stale").classList.remove("on");
    document.body.className = s.state;
    const [lab, sub] = LABELS[s.state] || ["—",""];
    document.getElementById("label").textContent = lab;
    const up = fmtUptime(s.service && s.service.uptime_seconds);
    document.getElementById("sub").textContent =
      s.state==="offline" ? sub : `${sub} · up ${up}`;
    const m = s.metrics || {};
    const cards = [
      ["Conversations", n(m.conversations)],
      ["Wake words",    n(m.wakeword_detections)],
      ["STT ok",        n(m.stt_ok)],
      ["Brain ok",      n(m.brain_ok)],
      ["TTS",           n(m.tts_requests)],
      ["Stream recov.", n(m.stream_recoveries)],
    ];
    document.getElementById("stats").innerHTML = cards.map(
      ([k,v]) => `<div class="stat"><div class="v">${v}</div><div class="k">${k}</div></div>`
    ).join("");
  } catch(e) {
    document.getElementById("stale").classList.add("on");
  }
}
tick();
setInterval(tick, 1500);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print(f"Luna status dashboard on http://localhost:{DASH_PORT}")
    HTTPServer(("0.0.0.0", DASH_PORT), Handler).serve_forever()

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path(__file__).parent
HISTORY_FILE = BASE_DIR / "run_history.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
ALLOWED_SCRIPTS = {
    "run_pipeline":    "run_pipeline.py",
    "image_generator": "image_generator.py",
    "assembler":       "assembler.py",
}

# In-memory store for active runs: run_id -> {"proc": Popen, "queue": Queue, "done": bool}
active_runs: dict = {}
active_runs_lock = threading.Lock()

# Track which script is currently running (only one at a time)
running_script: dict = {"script": None, "run_id": None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "changeme")


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def append_run(entry: dict) -> None:
    history = load_history()
    history.insert(0, entry)
    save_history(history[:200])  # keep at most 200 entries


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"max_videos_per_day": 4}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == get_password():
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/run/<script>", methods=["POST"])
@login_required
def run_script(script: str):
    if script not in ALLOWED_SCRIPTS:
        return jsonify({"error": "Unknown script."}), 400

    with active_runs_lock:
        if running_script["script"] is not None:
            return jsonify({"error": f"'{running_script['script']}' is already running."}), 409

        run_id = str(uuid.uuid4())
        script_file = ALLOWED_SCRIPTS[script]
        q: queue.Queue = queue.Queue()

        active_runs[run_id] = {"queue": q, "done": False}
        running_script["script"] = script
        running_script["run_id"] = run_id

    started_at = datetime.utcnow().isoformat() + "Z"

    def worker():
        log_lines = []
        status = "success"
        try:
            proc = subprocess.Popen(
                ["python", script_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(BASE_DIR),
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip("\n")
                q.put(line)
                log_lines.append(line)
            proc.wait()
            if proc.returncode != 0:
                status = "error"
        except Exception as exc:
            q.put(f"[DASHBOARD ERROR] {exc}")
            status = "error"
        finally:
            ended_at = datetime.utcnow().isoformat() + "Z"
            started_dt = datetime.fromisoformat(started_at.rstrip("Z"))
            ended_dt = datetime.fromisoformat(ended_at.rstrip("Z"))
            duration_s = round((ended_dt - started_dt).total_seconds(), 1)

            snippet = "\n".join(log_lines[-10:])
            append_run({
                "id": run_id,
                "script": script,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_s": duration_s,
                "status": status,
                "log_snippet": snippet,
            })

            with active_runs_lock:
                active_runs[run_id]["done"] = True
                q.put(None)  # sentinel
                running_script["script"] = None
                running_script["run_id"] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return jsonify({"run_id": run_id, "script": script})


@app.route("/stream/<run_id>")
@login_required
def stream(run_id: str):
    run = active_runs.get(run_id)
    if run is None:
        return Response("data: [run not found]\n\n", mimetype="text/event-stream")

    def generate():
        q = run["queue"]
        while True:
            try:
                line = q.get(timeout=30)
            except queue.Empty:
                # heartbeat
                yield "event: heartbeat\ndata: \n\n"
                if run.get("done"):
                    break
                continue

            if line is None:
                yield "event: done\ndata: [run complete]\n\n"
                break
            # Escape data for SSE
            safe = line.replace("\n", " ")
            yield f"data: {safe}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/history")
@login_required
def history():
    return jsonify(load_history()[:20])


@app.route("/status")
@login_required
def status():
    with active_runs_lock:
        return jsonify({
            "running_script": running_script["script"],
            "run_id": running_script["run_id"],
        })


@app.route("/api/schedule")
@login_required
def get_schedule():
    try:
        from analytics import get_best_hours_for_day, get_psychology_peaks_today, get_hour_confidence
        now     = datetime.utcnow()  # noqa — datetime imported at top
        weekday = datetime.now().weekday()

        settings = load_settings()
        max_vids = settings.get("max_videos_per_day", 4)

        learned = get_best_hours_for_day(weekday, n=max_vids)
        psych   = get_psychology_peaks_today()
        conf    = get_hour_confidence(weekday)

        # Build combined schedule (same logic as scheduler.py)
        seen, combined = set(), []
        for h in (learned + psych):
            if h not in seen:
                seen.add(h)
                combined.append(h)
        chosen = sorted(h for h in combined if 6 <= h < 23)[:max_vids]

        from datetime import datetime as _dt
        today_name = _dt.now().strftime("%A")

        return jsonify({
            "today":           today_name,
            "schedule":        [f"{h:02d}:00" for h in chosen],
            "learned_hours":   [f"{h:02d}:00" for h in learned],
            "psych_hours":     [f"{h:02d}:00" for h in sorted(set(psych))[:6]],
            "tier":            conf.get("tier", "psychology"),
            "day_videos":      conf.get("day_videos", 0),
            "any_videos":      conf.get("any_videos", 0),
            "data_driven":     conf.get("data_driven", False),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
@login_required
def post_settings():
    data = request.get_json(silent=True) or {}
    val = data.get("max_videos_per_day")
    if not isinstance(val, int) or not (1 <= val <= 20):
        return jsonify({"error": "Value must be an integer between 1 and 20"}), 400
    settings = load_settings()
    settings["max_videos_per_day"] = val
    save_settings(settings)
    return jsonify({"ok": True, "max_videos_per_day": val})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, threaded=True, host="0.0.0.0", port=port)

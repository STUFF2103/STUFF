"""
Dark Mind — Local Launcher
Starts scheduler + dashboard + ngrok tunnel in one command.

Usage:
    python start_local.py

Then open the printed URL on your phone from anywhere.
Password is whatever DASHBOARD_PASSWORD is in your .env (default: changeme)
"""
import os
import sys
import time
import socket
import subprocess
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
PORT     = int(os.getenv("PORT", 5000))


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def start_ngrok_tunnel():
    """Start ngrok tunnel, return public URL or None."""
    try:
        from pyngrok import ngrok
    except ImportError:
        print("   ⚠️  pyngrok not installed — run: pip install pyngrok")
        return None

    auth_token = os.getenv("NGROK_AUTH_TOKEN")
    if auth_token:
        ngrok.set_auth_token(auth_token)
    else:
        print("   ⚠️  No NGROK_AUTH_TOKEN in .env — tunnel may expire after 2hrs")
        print("      Get a free token at: https://ngrok.com (takes 30 seconds)")

    try:
        tunnel = ngrok.connect(PORT, "http")
        url = tunnel.public_url
        if url.startswith("http://"):
            url = "https://" + url[7:]
        return url
    except Exception as e:
        print(f"   ❌ ngrok failed: {e}")
        return None


def main():
    print()
    print("=" * 62)
    print("   🎬  DARK MIND — Local Launcher")
    print("=" * 62)

    # ── 1. ngrok tunnel ──────────────────────────────────────────
    print("\n🌐 Starting ngrok tunnel...")
    public_url = start_ngrok_tunnel()
    local_ip   = get_local_ip()

    print()
    print("=" * 62)
    if public_url:
        print(f"  📱 PHONE (anywhere):  {public_url}")
        # Save URL so you can find it later
        (BASE_DIR / "dashboard_url.txt").write_text(public_url, encoding="utf-8")
        print(f"     (also saved to dashboard_url.txt)")
    else:
        print(f"  📱 PHONE (WiFi only): http://{local_ip}:{PORT}")
    print(f"  💻 Laptop:            http://localhost:{PORT}")
    pw = os.getenv("DASHBOARD_PASSWORD", "changeme")
    print(f"  🔑 Password:          {pw}")
    print("=" * 62)
    print()

    # ── 2. Scheduler (auto-posts 2–3x per day) ───────────────────
    print("📅 Starting scheduler...")
    scheduler_proc = subprocess.Popen(
        [sys.executable, "scheduler.py"],
        cwd=str(BASE_DIR),
    )
    print("   ✅ Scheduler running")

    # ── 3. Flask dashboard ───────────────────────────────────────
    print(f"🖥️  Dashboard starting on port {PORT}...")
    print("   Press Ctrl+C to stop everything.\n")

    try:
        from app import app as flask_app
        flask_app.run(debug=False, threaded=True, host="0.0.0.0", port=PORT)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🛑 Stopping scheduler...")
        scheduler_proc.terminate()
        try:
            scheduler_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            scheduler_proc.kill()
        print("✅ All stopped.")


if __name__ == "__main__":
    main()

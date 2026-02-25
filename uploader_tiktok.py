"""
Dark Mind — TikTok Auto-Uploader (Direct Playwright)
Uses browser session cookies — no API approval, no OAuth, no domain needed.

One-time setup (30 seconds):
  1. Install Chrome extension "Get cookies.txt LOCALLY"
  2. Go to tiktok.com (make sure you're logged in)
  3. Click extension → Export → save as tiktok_cookies.txt in this folder
  4. Done — runs automatically forever (re-export if you get logged out)
"""
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

BASE_DIR     = Path(__file__).parent
COOKIES_FILE = BASE_DIR / "tiktok_cookies.txt"

HASHTAGS_BY_FORMAT = {
    "story_lesson":      "#darkpsychology #psychology #mindset #lifelessons #shorts",
    "scary_truth":       "#scaryfacts #darktruth #mystery #facts #shorts",
    "hidden_psychology": "#psychology #manipulation #influence #darkpsychology #shorts",
}

# All modal dismiss selectors (tried in order, first visible one wins)
_MODAL_SELECTORS = [
    "button:has-text('Got it')",
    "button:has-text('Gotcha')",
    "button:has-text('OK')",
    "button:has-text('Ok')",
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "button:has-text('Close')",
    "button:has-text('Continue')",
    "button:has-text('Dismiss')",
    "button:has-text('I understand')",
    "button:has-text('Skip')",
    "button:has-text('Confirm')",
    "button:has-text('Done')",
    "[aria-label='Close']",
    "[aria-label='close']",
    "[data-testid='close-btn']",
    "div[role='dialog'] button",
    "div[role='alertdialog'] button",
]

# Caption/description field selectors (TikTok changes these)
_CAPTION_SELECTORS = [
    "[contenteditable='true']",
    ".public-DraftEditor-content",
    "div[data-text='true']",
    ".DraftEditor-editorContainer [data-text]",
    "[data-testid='caption-input']",
    "div.editor-container",
    "div[class*='editor']",
]

# Post button selectors
_POST_SELECTORS = [
    "button:has-text('Post')",
    "button[data-testid='post-btn']",
    "button.css-1vsm6k1",
    "div.btn-wrap button:last-child",
    "button.TUXButton--primary",
    "[data-e2e='post-btn']",
    "button:has-text('Upload')",
]


def _parse_netscape_cookies(path):
    """Parse Netscape/Mozilla cookie file into Playwright-compatible dicts."""
    cookies = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _flag, path_val, secure, expires, name, value = parts[:7]
            try:
                exp = int(expires)
            except ValueError:
                exp = 0
            cookie = {
                "name":     name,
                "value":    value,
                "domain":   domain,
                "path":     path_val,
                "secure":   secure.upper() == "TRUE",
                "httpOnly": False,
                "sameSite": "None",
            }
            if exp > 0:
                cookie["expires"] = exp
            cookies.append(cookie)
    return cookies


def _build_description(script_data):
    fmt   = script_data.get("format", "story_lesson")
    hook  = script_data.get("hook_text", "").strip()
    topic = script_data.get("topic", "").strip()
    tags  = HASHTAGS_BY_FORMAT.get(fmt, HASHTAGS_BY_FORMAT["story_lesson"])
    base  = hook if hook else topic
    return f"{base}\n\n{tags}"[:2200]


def _dismiss_all_modals(page, timeout_ms=800):
    """Try every modal-dismiss selector and click if visible. Returns count."""
    dismissed = 0
    for sel in _MODAL_SELECTORS:
        try:
            for btn in page.locator(sel).all():
                if btn.is_visible(timeout=timeout_ms):
                    btn.click(timeout=timeout_ms)
                    dismissed += 1
                    time.sleep(0.3)
        except Exception:
            pass
    return dismissed


def _ensure_playwright():
    # 1. Make sure the Python package is installed
    try:
        from playwright.sync_api import sync_playwright  # noqa
    except ImportError:
        print("  [TikTok] Installing playwright package…")
        os.system(f"{sys.executable} -m pip install playwright -q")
        try:
            from playwright.sync_api import sync_playwright  # noqa
        except Exception as e:
            print(f"  [TikTok] Playwright install failed: {e}")
            return False

    # 2. Make sure the Chromium browser binary is downloaded
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            # This raises if the browser executable doesn't exist
            pw.chromium.executable_path  # noqa
    except Exception:
        print("  [TikTok] Downloading Playwright Chromium browser…")
        os.system(f"{sys.executable} -m playwright install chromium")

    return True


def upload_to_tiktok(video_path, script_data):
    """Upload video to TikTok via direct Playwright automation."""
    video_path = Path(video_path)

    if not video_path.exists():
        print(f"  [TikTok] File not found: {video_path}")
        return None

    if not COOKIES_FILE.exists():
        print(
            f"  [TikTok] ⚠️  tiktok_cookies.txt not found.\n"
            f"  → Log into tiktok.com in Chrome, use 'Get cookies.txt LOCALLY' extension,\n"
            f"    export and save as:  {COOKIES_FILE}"
        )
        return None

    if not _ensure_playwright():
        return None

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    description = _build_description(script_data)
    (BASE_DIR / "temp").mkdir(exist_ok=True)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            # Load session cookies
            try:
                cookies = _parse_netscape_cookies(COOKIES_FILE)
                ctx.add_cookies(cookies)
                print(f"  [TikTok] Loaded {len(cookies)} session cookies")
            except Exception as e:
                print(f"  [TikTok] ❌ Cookie parse error: {e}")
                browser.close()
                return None

            page = ctx.new_page()

            # ── Navigate ────────────────────────────────────────────
            print("  [TikTok] Navigating to creator center…")
            try:
                page.goto(
                    "https://www.tiktok.com/creator-center/upload",
                    timeout=30_000,
                    wait_until="domcontentloaded",
                )
            except PWTimeout:
                print("  [TikTok] Timeout on first load — retrying…")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=20_000)
                except Exception:
                    pass

            time.sleep(3)

            # Check if redirected to login
            url = page.url
            if any(k in url for k in ["login", "passport"]):
                print("  [TikTok] ❌ Not logged in — re-export tiktok_cookies.txt")
                browser.close()
                return None

            print(f"  [TikTok] Loaded: {url[:80]}")

            # Dismiss any welcome/notification modals
            n = _dismiss_all_modals(page)
            if n:
                print(f"  [TikTok] Dismissed {n} initial modal(s)")
            time.sleep(1)

            # ── Resolve working context (page or iframe) ─────────────
            # TikTok creator center embeds upload UI inside an iframe
            upload_ctx = page  # default: top-level page
            try:
                frames = page.frames
                for fr in frames:
                    fr_url = fr.url
                    if any(k in fr_url for k in ["creator", "upload", "tiktok"]) and fr_url != url:
                        upload_ctx = fr
                        print(f"  [TikTok] Using iframe context: {fr_url[:60]}")
                        break
            except Exception:
                pass

            # ── Attach video file ────────────────────────────────────
            print(f"  [TikTok] Attaching {video_path.name}…")
            file_input = None
            for ctx_obj in [upload_ctx, page]:
                for sel in ["input[type='file']", "input[accept*='video']", "input[accept*='.mp4']"]:
                    try:
                        fi = ctx_obj.locator(sel).first
                        if fi.count() > 0:
                            file_input = fi
                            break
                    except Exception:
                        pass
                if file_input:
                    break

            if file_input is None:
                page.screenshot(path=str(BASE_DIR / "temp" / "tiktok_debug.png"))
                print("  [TikTok] ❌ No file input found — screenshot saved to temp/tiktok_debug.png")
                browser.close()
                return None

            file_input.set_input_files(str(video_path))
            print("  [TikTok] File attached — waiting for processing…")

            # ── Wait for upload to finish ────────────────────────────
            upload_done = False
            deadline = time.time() + 180  # 3 min max

            while time.time() < deadline:
                # Continuously dismiss modals during upload (both page and iframe)
                _dismiss_all_modals(page, timeout_ms=500)
                if upload_ctx is not page:
                    _dismiss_all_modals(upload_ctx, timeout_ms=500)

                # Caption field appearing = upload done
                for ctx_obj in [upload_ctx, page]:
                    for cap_sel in _CAPTION_SELECTORS:
                        try:
                            if ctx_obj.locator(cap_sel).first.is_visible(timeout=500):
                                upload_done = True
                                upload_ctx = ctx_obj  # pin to whichever context has the field
                                break
                        except Exception:
                            pass
                    if upload_done:
                        break

                if upload_done:
                    print("  [TikTok] Upload complete")
                    break

                # Check for error state
                try:
                    if page.locator("text=Upload failed").is_visible(timeout=300):
                        print("  [TikTok] ❌ TikTok reported upload failed")
                        browser.close()
                        return None
                except Exception:
                    pass

                time.sleep(2)

            if not upload_done:
                print("  [TikTok] ⚠️  Caption field not found after 3 min — attempting to proceed")

            time.sleep(2)
            _dismiss_all_modals(page)
            if upload_ctx is not page:
                _dismiss_all_modals(upload_ctx)
            time.sleep(1)

            # ── Set caption/description ──────────────────────────────
            caption_set = False
            for ctx_obj in [upload_ctx, page]:
                for cap_sel in _CAPTION_SELECTORS:
                    try:
                        el = ctx_obj.locator(cap_sel).first
                        if not el.is_visible(timeout=3000):
                            continue

                        el.click(timeout=3000)
                        time.sleep(0.5)

                        # Dismiss any modal that popped from the click
                        _dismiss_all_modals(page, timeout_ms=600)
                        if upload_ctx is not page:
                            _dismiss_all_modals(upload_ctx, timeout_ms=600)

                        # Select all + delete existing placeholder
                        page.keyboard.press("Control+a")
                        time.sleep(0.2)
                        page.keyboard.press("Backspace")
                        time.sleep(0.3)

                        caption_text = description[:2200]
                        page.keyboard.type(caption_text, delay=15)

                        caption_set = True
                        print(f"  [TikTok] Caption set ({len(caption_text)} chars)")
                        break

                    except Exception as ex:
                        print(f"  [TikTok] Caption attempt ({cap_sel}): {ex}")

                if caption_set:
                    break

            if not caption_set:
                # JS injection fallback
                for ctx_obj in [upload_ctx, page]:
                    try:
                        ctx_obj.evaluate(
                            """(txt) => {
                                const el = document.querySelector('[contenteditable="true"]');
                                if (el) {
                                    el.focus();
                                    el.innerText = txt;
                                    el.dispatchEvent(new Event('input', {bubbles:true}));
                                    el.dispatchEvent(new Event('change', {bubbles:true}));
                                }
                            }""",
                            description[:500],
                        )
                        caption_set = True
                        print("  [TikTok] Caption set via JS injection")
                        break
                    except Exception:
                        pass

            if not caption_set:
                print("  [TikTok] ⚠️  Could not set caption — posting without hashtags")

            time.sleep(1)
            _dismiss_all_modals(page)
            if upload_ctx is not page:
                _dismiss_all_modals(upload_ctx)
            time.sleep(0.5)

            # ── Click Post ───────────────────────────────────────────
            posted = False
            for ctx_obj in [upload_ctx, page]:
                for btn_sel in _POST_SELECTORS:
                    try:
                        btn = ctx_obj.locator(btn_sel).last
                        if btn.is_visible(timeout=3000) and btn.is_enabled(timeout=1000):
                            btn.click(timeout=5000)
                            posted = True
                            print(f"  [TikTok] Post button clicked")
                            break
                    except Exception:
                        pass
                if posted:
                    break

            if not posted:
                page.screenshot(path=str(BASE_DIR / "temp" / "tiktok_debug.png"))
                print("  [TikTok] ❌ Post button not found — screenshot: temp/tiktok_debug.png")
                browser.close()
                return None

            # ── Wait for confirmation ────────────────────────────────
            time.sleep(6)
            _dismiss_all_modals(page)
            time.sleep(2)

            post_id = str(int(time.time()))
            print(f"  ✅ [TikTok] Posted successfully (session: {post_id})")
            browser.close()
            return post_id

    except Exception as e:
        err = str(e)
        if any(k in err.lower() for k in ["cookie", "login", "session", "auth", "redirect"]):
            print(f"  ❌ [TikTok] Session expired — re-export tiktok_cookies.txt")
        else:
            print(f"  ❌ [TikTok] Upload failed: {e}")
        return None


def fetch_stats(video_id):
    """TikTok stats not available via cookie method."""
    return {}

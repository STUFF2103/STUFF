#!/bin/bash
# Dark Mind — Railway startup script
# Handles persistent volume links then starts scheduler + dashboard

set -e

DATA_DIR=${DATA_DIR:-/data}
mkdir -p "$DATA_DIR"

echo "🔗 Linking persistent files from $DATA_DIR ..."

# Reconstruct auth files from env vars if not already on volume
if [ -n "$YOUTUBE_TOKEN_JSON" ] && [ ! -f "$DATA_DIR/token.json" ]; then
    echo "$YOUTUBE_TOKEN_JSON" | base64 -d > "$DATA_DIR/token.json"
    echo "  Wrote token.json from env var"
fi
if [ -n "$TIKTOK_COOKIES" ] && [ ! -f "$DATA_DIR/tiktok_cookies.txt" ]; then
    echo "$TIKTOK_COOKIES" | base64 -d > "$DATA_DIR/tiktok_cookies.txt"
    echo "  Wrote tiktok_cookies.txt from env var"
fi

# Single files: copy to volume on first deploy, then symlink every time
for f in token.json tiktok_cookies.txt analytics.db voice_history.json client_secrets.json settings.json; do
    SRC="/app/$f"
    DST="$DATA_DIR/$f"
    # First deploy: push bundled file to volume
    if [ -f "$SRC" ] && [ ! -L "$SRC" ] && [ ! -f "$DST" ]; then
        cp "$SRC" "$DST"
        echo "  Seeded $f to volume"
    fi
    # Always symlink to volume version (if it exists)
    if [ -f "$DST" ]; then
        rm -f "$SRC"
        ln -s "$DST" "$SRC"
        echo "  Linked $f"
    fi
done

# Directories: link to volume so output/audio/fonts survive redeploys
for d in fonts output audio; do
    mkdir -p "$DATA_DIR/$d"
    if [ ! -L "/app/$d" ]; then
        # Copy any seed files then replace with symlink
        cp -rn "/app/$d/." "$DATA_DIR/$d/" 2>/dev/null || true
        rm -rf "/app/$d"
        ln -s "$DATA_DIR/$d" "/app/$d"
        echo "  Linked $d/"
    fi
done

echo "✅ Persistent data ready"

# Start scheduler as background process
echo "📅 Starting scheduler..."
python scheduler.py &
SCHEDULER_PID=$!
echo "   Scheduler PID: $SCHEDULER_PID"

# Start Flask dashboard (foreground — Railway healthcheck watches this)
echo "🌐 Starting dashboard on port ${PORT:-5000}..."
exec python app.py

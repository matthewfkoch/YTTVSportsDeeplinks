#!/bin/sh
set -u

export DISPLAY="${DISPLAY:-:99}"
export ENABLE_CHROME="${ENABLE_CHROME:-1}"
CHROME_PROFILE="${CHROME_PROFILE:-${YTTV_EPG_DATA_DIR:-/data}/chrome-profile}"
CDP_PORT="${CDP_PORT:-9222}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-7900}"
NOVNC_WEB="${NOVNC_WEB:-/usr/share/novnc}"

mkdir -p "${YTTV_EPG_DATA_DIR:-/data}" "$CHROME_PROFILE"

chrome_bin() {
  if [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" >/dev/null 2>&1; then
    printf '%s\n' "$CHROME_BIN"
    return
  fi
  for candidate in chromium chromium-browser google-chrome-stable google-chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  return 1
}

start_desktop() {
  if [ "$ENABLE_CHROME" = "0" ] || [ "$ENABLE_CHROME" = "false" ]; then
    return 0
  fi
  if ! command -v Xvfb >/dev/null 2>&1; then
    echo "Xvfb not installed; cookie paste import still works."
    return 0
  fi

  CHROME_BIN="$(chrome_bin || true)"
  if [ -z "$CHROME_BIN" ]; then
    echo "Chromium not installed; cookie paste import still works."
    return 0
  fi

  Xvfb "$DISPLAY" -screen 0 1280x800x24 -ac +extension RANDR -noreset >/tmp/xvfb.log 2>&1 &
  sleep 0.4
  if command -v openbox >/dev/null 2>&1; then
    openbox >/tmp/openbox.log 2>&1 &
  fi
  x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 127.0.0.1 -rfbport "$VNC_PORT" -xkb -noxdamage >/tmp/x11vnc.log 2>&1 &
  if [ -d "$NOVNC_WEB" ] && command -v websockify >/dev/null 2>&1; then
    websockify --web "$NOVNC_WEB" "0.0.0.0:$NOVNC_PORT" "127.0.0.1:$VNC_PORT" >/tmp/novnc.log 2>&1 &
  fi

  (
    delay=30
    while true; do
      rm -f "$CHROME_PROFILE/SingletonLock" "$CHROME_PROFILE/SingletonSocket" "$CHROME_PROFILE/SingletonCookie"
      started=$(date +%s)
      "$CHROME_BIN" \
        --no-sandbox \
        --test-type \
        --disable-gpu \
        --disable-dev-shm-usage \
        --disable-software-rasterizer \
        --no-first-run \
        --no-default-browser-check \
        --disable-session-crashed-bubble \
        --hide-crash-restore-bubble \
        --disable-infobars \
        --disable-sync \
        --disable-translate \
        --disable-background-networking \
        --disable-client-side-phishing-detection \
        --disable-component-update \
        --disable-features=TranslateUI \
        --disable-hang-monitor \
        --disable-popup-blocking \
        --disable-prompt-on-repost \
        --metrics-recording-only \
        --mute-audio \
        --password-store=basic \
        --use-mock-keychain \
        --remote-debugging-address=127.0.0.1 \
        --remote-debugging-port="$CDP_PORT" \
        --remote-allow-origins=* \
        --ozone-platform=x11 \
        --user-data-dir="$CHROME_PROFILE" \
        --window-size=1280,800 \
        --window-position=0,0 \
        --start-maximized \
        https://tv.youtube.com >/tmp/chromium.log 2>&1 || true
      ran=$(($(date +%s) - started))
      if [ "$ran" -ge 120 ]; then
        delay=30
      elif [ "$delay" -lt 300 ]; then
        delay=$((delay * 2))
        if [ "$delay" -gt 300 ]; then
          delay=300
        fi
      fi
      echo "Chromium exited after ${ran}s; restarting in ${delay}s"
      sleep "$delay"
    done
  ) &
}

start_desktop

exec uvicorn yttv_epg.app:app --host 0.0.0.0 --port "${YTTV_EPG_PORT:-8095}"

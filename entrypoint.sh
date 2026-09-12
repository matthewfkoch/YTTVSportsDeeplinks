#!/bin/sh
set -u

export DISPLAY="${DISPLAY:-:99}"
export ENABLE_CHROME="${ENABLE_CHROME:-1}"
CHROME_PROFILE="${CHROME_PROFILE:-${YTTV_EPG_DATA_DIR:-/data}/chrome-profile}"
CDP_PORT="${CDP_PORT:-9222}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-7900}"
NOVNC_WEB="${NOVNC_WEB:-/usr/share/novnc}"
STOP_FILE="${STOP_FILE:-/tmp/yttv-stop-chrome}"
CHROME_PID_FILE="${CHROME_PID_FILE:-/tmp/yttv-chromium.pid}"
rm -f "$STOP_FILE" "$CHROME_PID_FILE"

mkdir -p "${YTTV_EPG_DATA_DIR:-/data}" "$CHROME_PROFILE"

prune_chrome_profile() {
  [ -d "$CHROME_PROFILE" ] || return 0
  rm -rf \
    "$CHROME_PROFILE/BrowserMetrics" \
    "$CHROME_PROFILE/Crashpad" \
    "$CHROME_PROFILE/Crash Reports"
  find "$CHROME_PROFILE" -type f -name '*.pma' -delete 2>/dev/null || true
}

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

  prune_chrome_profile
  (
    while true; do
      prune_chrome_profile
      sleep 60
    done
  ) &

  (
    delay=30
    while true; do
      [ -f "$STOP_FILE" ] && break
      prune_chrome_profile
      rm -f "$CHROME_PROFILE/SingletonLock" "$CHROME_PROFILE/SingletonSocket" "$CHROME_PROFILE/SingletonCookie"
      started=$(date +%s)
      "$CHROME_BIN" \
        --no-sandbox \
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
        --disable-client-side-phishing-detection \
        --disable-component-update \
        --disable-breakpad \
        --disable-crash-reporter \
        --disable-metrics \
        --disable-features=TranslateUI,PersistentHistograms,DeviceBoundSessionCredentials,BoundSessionCredentials \
        --disable-hang-monitor \
        --disable-popup-blocking \
        --disable-prompt-on-repost \
        --disable-backgrounding-occluded-windows \
        --disable-renderer-backgrounding \
        --memory-pressure-off \
        --disk-cache-size=268435456 \
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
        https://tv.youtube.com >/tmp/chromium.log 2>&1 &
      chrome_pid=$!
      echo "$chrome_pid" > "$CHROME_PID_FILE"
      wait "$chrome_pid" || true
      rm -f "$CHROME_PID_FILE"
      [ -f "$STOP_FILE" ] && break
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

shutdown() {
  touch "$STOP_FILE"
  if [ -f "$CHROME_PID_FILE" ]; then
    chrome_pid=$(cat "$CHROME_PID_FILE")
    kill -TERM "$chrome_pid" >/dev/null 2>&1 || true
    i=0
    while [ "$i" -lt 10 ]; do
      kill -0 "$chrome_pid" >/dev/null 2>&1 || break
      i=$((i + 1))
      sleep 0.5
    done
  fi
  if [ -n "${APP_PID:-}" ]; then
    kill -TERM "$APP_PID" >/dev/null 2>&1 || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  exit 0
}

trap shutdown TERM INT
start_desktop

uvicorn yttv_epg.app:app --host 0.0.0.0 --port "${YTTV_EPG_PORT:-8095}" &
APP_PID=$!
wait "$APP_PID"

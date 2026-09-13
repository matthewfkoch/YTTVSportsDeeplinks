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
XVFB_PID_FILE="${XVFB_PID_FILE:-/tmp/yttv-xvfb.pid}"
X11VNC_PID_FILE="${X11VNC_PID_FILE:-/tmp/yttv-x11vnc.pid}"
OPENBOX_PID_FILE="${OPENBOX_PID_FILE:-/tmp/yttv-openbox.pid}"
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

process_alive() {
  pid_file="$1"
  [ -s "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

stop_process() {
  pid_file="$1"
  if process_alive "$pid_file"; then
    kill -TERM "$(cat "$pid_file")" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
}

wait_for_display() {
  display_number="${DISPLAY#:}"
  display_number="${display_number%%.*}"
  socket="/tmp/.X11-unix/X${display_number}"
  attempts=0
  while [ "$attempts" -lt 100 ]; do
    process_alive "$XVFB_PID_FILE" || return 1
    [ -S "$socket" ] && return 0
    attempts=$((attempts + 1))
    sleep 0.1
  done
  return 1
}

ensure_display() {
  display_number="${DISPLAY#:}"
  display_number="${display_number%%.*}"
  socket="/tmp/.X11-unix/X${display_number}"
  if process_alive "$XVFB_PID_FILE" && [ -S "$socket" ]; then
    return 0
  fi

  stop_process "$OPENBOX_PID_FILE"
  stop_process "$X11VNC_PID_FILE"
  stop_process "$XVFB_PID_FILE"
  rm -f "/tmp/.X${display_number}-lock" "$socket"

  Xvfb "$DISPLAY" -screen 0 1280x800x24 -ac +extension RANDR -noreset >>/tmp/xvfb.log 2>&1 &
  echo "$!" > "$XVFB_PID_FILE"
  if ! wait_for_display; then
    echo "Xvfb failed to become ready; retrying desktop startup"
    return 1
  fi

  if command -v openbox >/dev/null 2>&1; then
    openbox >>/tmp/openbox.log 2>&1 &
    echo "$!" > "$OPENBOX_PID_FILE"
  fi
  x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 127.0.0.1 -rfbport "$VNC_PORT" -xkb -noxdamage >>/tmp/x11vnc.log 2>&1 &
  echo "$!" > "$X11VNC_PID_FILE"
  return 0
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

  if [ -d "$NOVNC_WEB" ] && command -v websockify >/dev/null 2>&1; then
    websockify --web "$NOVNC_WEB" "0.0.0.0:$NOVNC_PORT" "127.0.0.1:$VNC_PORT" >>/tmp/novnc.log 2>&1 &
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
      if ! ensure_display; then
        sleep 2
        continue
      fi
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
        --disable-features=TranslateUI,PersistentHistograms \
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
        --restore-last-session \
        https://tv.youtube.com >>/tmp/chromium.log 2>&1 &
      chrome_pid=$!
      echo "$chrome_pid" > "$CHROME_PID_FILE"
      chrome_status=0
      wait "$chrome_pid" || chrome_status=$?
      rm -f "$CHROME_PID_FILE"
      [ -f "$STOP_FILE" ] && break
      ran=$(($(date +%s) - started))
      if ! process_alive "$XVFB_PID_FILE"; then
        delay=2
      elif [ "$ran" -ge 120 ]; then
        delay=30
      elif [ "$delay" -lt 300 ]; then
        delay=$((delay * 2))
        if [ "$delay" -gt 300 ]; then
          delay=300
        fi
      fi
      echo "Chromium exited with status ${chrome_status} after ${ran}s; restarting in ${delay}s"
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
  stop_process "$OPENBOX_PID_FILE"
  stop_process "$X11VNC_PID_FILE"
  stop_process "$XVFB_PID_FILE"
  exit 0
}

trap shutdown TERM INT
start_desktop

uvicorn yttv_epg.app:app --host 0.0.0.0 --port "${YTTV_EPG_PORT:-8095}" &
APP_PID=$!
wait "$APP_PID"

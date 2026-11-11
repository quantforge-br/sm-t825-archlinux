#!/usr/bin/env bash
# Run a bounded real Chromium/WebGL workload on the installed graphical session.
# The test never changes boot files and does not require a reboot.
set -euo pipefail

HERE=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$HERE"
target=${T825_SSH_TARGET:-tabs3}
out=${T825_CHROMIUM_REPORT_DIR:-artifacts/roadmap-7.3/chromium-gpu-$(date -u +%Y%m%dT%H%M%SZ)}
seconds=${T825_CHROMIUM_SECONDS:-45}
umask 077
mkdir -p "$out"

case "$seconds" in
  ''|*[!0-9]*) echo 'T825_CHROMIUM_SECONDS must be an integer' >&2; exit 2 ;;
esac
[ "$seconds" -ge 10 ] && [ "$seconds" -le 120 ] || {
  echo 'T825_CHROMIUM_SECONDS must be between 10 and 120' >&2
  exit 2
}

if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
  mkdir -p "$out/runner"
  cp "$HERE/tools/t825-chromium-gpu-test.sh" "$out/runner/t825-chromium-gpu-test.sh"
  sha256sum "$out/runner/t825-chromium-gpu-test.sh" > "$out/runner.sha256"
  exec env T825_SOURCE_ROOT="$HERE" T825_RUNNER_SNAPSHOT=1 \
    T825_SSH_TARGET="$target" T825_CHROMIUM_SECONDS="$seconds" \
    T825_CHROMIUM_REPORT_DIR="$out" bash "$out/runner/t825-chromium-gpu-test.sh"
fi

exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }
printf '%s\n' "target=$target" "seconds=$seconds" "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$out/identity.txt"
printf '%s\n' "$$" > "$out/host.pid"

remote=''
read -r -d '' remote <<'REMOTE' || true
set -eu
profile=/tmp/t825-chromium-gpu-$$
page=/tmp/t825-chromium-gpu-$$.html
cleanup() {
  for pid in $(pgrep -f -- "$profile" 2>/dev/null || true); do
    [ "$pid" = "$$" ] || kill -TERM "$pid" 2>/dev/null || true
  done
  rm -rf "$profile" "$page" /tmp/t825-chromium-browser
}
trap cleanup EXIT
if command -v chromium >/dev/null 2>&1; then
  browser=chromium
elif [ -x /opt/brave-origin-bin/brave ]; then
  browser=/opt/brave-origin-bin/brave
else
  printf '%s\n' 'CHROMIUM_COMPATIBLE_BROWSER_UNAVAILABLE'
  exit 77
fi
printf 'browser=%s\n' "$browser" > /tmp/t825-chromium-browser
cat >"$page" <<'HTML'
<!doctype html><meta charset=utf-8><title>T825 GPU workload</title>
<canvas id=c width=1024 height=768></canvas><script>
const c=document.getElementById('c'), gl=c.getContext('webgl2')||c.getContext('webgl');
if (!gl) { document.title='no-webgl'; throw new Error('WebGL unavailable'); }
const vs=gl.createShader(gl.VERTEX_SHADER); gl.shaderSource(vs,
 'attribute vec2 p; void main(){gl_Position=vec4(p,0.,1.);}'); gl.compileShader(vs);
const fs=gl.createShader(gl.FRAGMENT_SHADER); gl.shaderSource(fs,
 'precision highp float; uniform float t; void main(){vec2 p=gl_FragCoord.xy/768.;' +
 'float v=0.; for(int i=0;i<80;i++){p=abs(p)/dot(p,p)-.7; v+=sin(dot(p,p)*20.+t);}' +
 'gl_FragColor=vec4(.5+.5*sin(v+t),.5+.5*cos(v),.6+.4*sin(v),1.);}'); gl.compileShader(fs);
const pr=gl.createProgram(); gl.attachShader(pr,vs); gl.attachShader(pr,fs); gl.bindAttribLocation(pr,0,'p'); gl.linkProgram(pr);
const b=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.bufferData(gl.ARRAY_BUFFER,
 new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW); gl.useProgram(pr);
gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);
let n=0, start=performance.now(); function frame(t){gl.uniform1f(gl.getUniformLocation(pr,'t'),t/1000); gl.drawArrays(gl.TRIANGLE_STRIP,0,4); gl.finish(); n++; if(t-start<40000) requestAnimationFrame(frame); else document.title='frames-'+n;} requestAnimationFrame(frame);
</script>
HTML
before=$(sudo -n dmesg)
printf '%s\n' "$before" > /tmp/t825-chromium-dmesg-before
if [ -r /sys/kernel/debug/dri/0/state ]; then sudo -n cat /sys/kernel/debug/dri/0/state > /tmp/t825-chromium-drm-before; else printf '%s\n' unavailable > /tmp/t825-chromium-drm-before; fi
hyprland_pid=$(pgrep -xo Hyprland || true)
printf '%s\n' "$hyprland_pid" > /tmp/t825-chromium-hyprland-before
set +e
XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 timeout --kill-after=5s "$T825_CHROMIUM_SECONDS" \
  "$browser" --no-sandbox --user-data-dir="$profile" --ozone-platform=wayland \
  --enable-gpu --disable-gpu-rasterization --disable-first-run-ui \
  --no-default-browser-check --app="file://$page" >/tmp/t825-chromium-stdout 2>/tmp/t825-chromium-stderr
chromium_status=$?
set -e
printf '%s\n' "$chromium_status" > /tmp/t825-chromium-status
after=$(sudo -n dmesg)
printf '%s\n' "$after" > /tmp/t825-chromium-dmesg-after
if [ -r /sys/kernel/debug/dri/0/state ]; then sudo -n cat /sys/kernel/debug/dri/0/state > /tmp/t825-chromium-drm-after; else printf '%s\n' unavailable > /tmp/t825-chromium-drm-after; fi
pgrep -xo Hyprland > /tmp/t825-chromium-hyprland-after || true
cat /tmp/t825-chromium-dmesg-before
printf '\n--- Chromium stderr ---\n'; cat /tmp/t825-chromium-stderr
printf '\n--- Chromium stdout ---\n'; cat /tmp/t825-chromium-stdout
printf '\n--- DRM before ---\n'; cat /tmp/t825-chromium-drm-before
printf '\n--- DRM after ---\n'; cat /tmp/t825-chromium-drm-after
printf '\n--- Hyprland ---\n'; printf 'before='; cat /tmp/t825-chromium-hyprland-before; printf 'after='; cat /tmp/t825-chromium-hyprland-after
printf '\n--- Chromium status ---\n'; cat /tmp/t825-chromium-status
printf '\n--- Browser ---\n'; cat /tmp/t825-chromium-browser
printf '\n--- New kernel GPU lines ---\n'
diff -u /tmp/t825-chromium-dmesg-before /tmp/t825-chromium-dmesg-after | grep -E '^\+.*(msm|gpu|drm|hang|adreno|fault|reset)' || true
REMOTE

if timeout --kill-after=10s "$((seconds + 30))" ssh -o BatchMode=yes -o ConnectTimeout=5 "$target" \
  "T825_CHROMIUM_SECONDS=$seconds sh -s" <<<"$remote" > "$out/remote.txt" 2>&1; then
  result=0
else
  result=$?
fi
printf '%s\n' "$result" > "$out/ssh-status.txt"
if [ "$result" -ne 0 ]; then
  if [ "$result" -eq 77 ]; then
    printf '%s\n' 'BLOCKED: Chromium is not installed on the tablet.' > "$out/result.txt"
  else
    printf '%s\n' 'SSH/Chromium collection failed or timed out.' > "$out/result.txt"
  fi
else
  printf '%s\n' 'Chromium workload completed; inspect remote.txt for GPU and compositor evidence.' > "$out/result.txt"
fi
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + | sort > .SHA256SUMS.new && mv .SHA256SUMS.new SHA256SUMS)
printf 'Report: %s\n' "$out"
exit "$result"

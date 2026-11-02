#!/bin/bash
# Hyprland + Dux Shell (DankMaterialShell) session for the Galaxy Tab S3, as tested on an SM-T825.
# Run on the tablet as the desktop user (sudo needed), from a checkout of this repository:
#   desktop/install.sh [--no-autologin] [--no-tuning]
# Steps: packages, "dms setup", tablet.lua (touch/S-Pen/Home/Power), auto-rotation, autologin on tty1,
# low-RAM tuning (zram, sysctl, THP, MGLRU, earlyoom), browser flags. Existing files are kept as *.orig once.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
H=$HOME/.config/hypr
autologin=1; tuning=1
for a in "$@"; do
	case "$a" in --no-autologin) autologin=0 ;; --no-tuning) tuning=0 ;; *) echo "unknown option $a" >&2; exit 2 ;; esac
done
backup() { if [ -e "$1" ] && [ ! -e "$1.orig" ]; then sudo cp -a "$1" "$1.orig"; fi; }

echo "### packages"
sudo pacman -S --needed --noconfirm hyprland hyprland-guiutils jq dux-shell matugen accountsservice \
	xdg-desktop-portal-hyprland xdg-desktop-portal-gtk foot grim wl-clipboard cliphist ttf-dejavu \
	noto-fonts-emoji python libnotify

echo "### Dux Shell"
if [ ! -e "$H/hyprland.lua" ]; then
	echo "Run 'dms setup' first (compositor: Hyprland, systemd: yes), then run this script again." >&2
	exit 1
fi
[ -e "$H/hyprland.lua.orig" ] || cp -a "$H/hyprland.lua" "$H/hyprland.lua.orig"

echo "### tablet.lua and rotation.lua"
install -m644 "$HERE/hyprland/tablet.lua" "$HERE/hyprland/rotation.lua" "$H/"
python3 - "$H/hyprland.lua" <<'EOF'
import sys
p = sys.argv[1]; s = open(p).read()
if 'require("rotation")' not in s:
    old = 'require("dms.outputs")\n'
    assert s.count(old) == 1, "hyprland.lua has no require(\"dms.outputs\") line"
    s = s.replace(old, '-- Auto-rotation (t825-autorotate): wraps hl.monitor before DMS writes the DSI-1 rule.\nrequire("rotation")\n' + old)
if 'require("tablet")' not in s:
    s = s.rstrip("\n") + '\n\n-- Galaxy Tab S3: touch, S-Pen, Home and Power keys (loaded last).\nrequire("tablet")\n'
open(p, "w").write(s)
EOF
grep -n 'require("rotation")\|require("dms.outputs")\|require("tablet")' "$H/hyprland.lua"

echo "### power key: short press toggles the panel, long press powers off"
sudo install -m755 "$HERE/hyprland/t825-screen-toggle" /usr/local/bin/t825-screen-toggle
sudo install -Dm644 "$HERE/hyprland/50-t825-power-key.conf" /etc/systemd/logind.conf.d/50-t825-power-key.conf

echo "### auto-rotation"
sudo install -m755 "$HERE/autorotate/t825-autorotate" "$HERE/autorotate/t825-rotation-lock" /usr/local/bin/
sed "s/@USER@/$USER/" "$HERE/autorotate/50-t825-sensor-claim.rules" | sudo install -Dm644 /dev/stdin /etc/polkit-1/rules.d/50-t825-sensor-claim.rules
install -Dm644 "$HERE/autorotate/t825-autorotate.service" "$HOME/.config/systemd/user/t825-autorotate.service"
systemctl --user daemon-reload
systemctl --user enable t825-autorotate.service

echo "### Chromium-based browsers: rasterize on the CPU (GPU raster hangs the A530)"
for f in brave-origin-flags.conf brave-flags.conf chromium-flags.conf; do
	conf=$HOME/.config/$f
	if [ ! -e "$conf" ]; then
		install -m644 "$HERE/browser/chromium-flags.conf" "$conf"
	elif ! grep -qx -- '--disable-gpu-rasterization' "$conf"; then
		echo '--disable-gpu-rasterization' >> "$conf"
	fi
done

if [ $autologin = 1 ]; then
	echo "### autologin on tty1, Hyprland started from the login shell"
	sed "s/@USER@/$USER/" "$HERE/hyprland/autologin.conf" | sudo install -Dm644 /dev/stdin /etc/systemd/system/getty@tty1.service.d/autologin.conf
	case "$(basename "$SHELL")" in zsh) prof=$HOME/.zprofile ;; *) prof=$HOME/.bash_profile ;; esac
	grep -q 'exec start-hyprland' "$prof" 2>/dev/null || cat "$HERE/hyprland/profile-snippet.sh" >> "$prof"
fi

if [ $tuning = 1 ]; then
	echo "### low-RAM tuning"
	sudo pacman -S --needed --noconfirm earlyoom
	backup /etc/systemd/zram-generator.conf
	backup /etc/default/earlyoom
	sudo install -m644 "$HERE/tuning/zram-generator.conf" /etc/systemd/zram-generator.conf
	sudo install -m644 "$HERE/tuning/99-t825-memory.conf" /etc/sysctl.d/99-t825-memory.conf
	sudo install -m644 "$HERE/tuning/t825-thp.conf" "$HERE/tuning/t825-mglru.conf" /etc/tmpfiles.d/
	sudo install -m644 "$HERE/tuning/earlyoom" /etc/default/earlyoom
	sudo systemctl enable earlyoom.service
fi

sudo systemctl daemon-reload
echo "done: reboot (or log in on tty1)"

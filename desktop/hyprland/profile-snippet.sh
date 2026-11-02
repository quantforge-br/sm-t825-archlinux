# Appended to ~/.bash_profile or ~/.zprofile by desktop/install.sh.
# Start Hyprland on tty1 (autologin); SSH and the other ttys keep a plain shell.
if [ -z "$WAYLAND_DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
	exec start-hyprland
fi

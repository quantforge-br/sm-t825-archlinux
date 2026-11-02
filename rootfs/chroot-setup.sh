#!/bin/bash
# Runs inside the image (arch-chroot, qemu-user) from build-arch-rootfs.sh.
# Environment: PWHASH USERNAME HOSTNAME_ LOCALE KEYMAP TIMEZONE ROOT_UUID BOOT_UUID KVER [SUDO_NOPASSWD=1]
set -euo pipefail
export LANG=C

echo "### pacman: disable the download sandbox while running under qemu-user (no Landlock)"
cp /etc/pacman.conf /var/tmp/pacman.conf.orig
sed -i "s/^DownloadUser/#DownloadUser/" /etc/pacman.conf
grep -q "^DisableSandbox" /etc/pacman.conf || sed -i "/^\[options\]/a DisableSandbox" /etc/pacman.conf
grep -nE "DownloadUser|DisableSandbox" /etc/pacman.conf

echo "### pacman keyring"
pacman-key --init
pacman-key --populate archlinuxarm

echo "### drop the generic Arch Linux ARM kernel and firmware packages"
pacman -Qq | grep -E "^(linux|mkinitcpio|firmware)" || true
rm_pkgs=$(pacman -Qq | grep -E "^(linux-aarch64|linux-firmware.*)$" || true)
if [ -n "$rm_pkgs" ]; then pacman -Rns --noconfirm $rm_pkgs; fi

echo "### upgrade"
pacman -Syu --noconfirm

echo "### install packages"
pacman -S --needed --noconfirm sudo networkmanager bluez bluez-utils alsa-utils alsa-ucm-conf pipewire \
  pipewire-alsa pipewire-pulse wireplumber iw wireless-regdb iio-sensor-proxy mesa zram-generator vim htop \
  rsync usbutils pciutils

echo "### locale, time, hostname"
sed -i -e "s/^#$LOCALE /$LOCALE /" -e "s/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/" /etc/locale.gen
locale-gen
echo "LANG=$LOCALE" > /etc/locale.conf
echo "KEYMAP=$KEYMAP" > /etc/vconsole.conf
ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
echo "$HOSTNAME_" > /etc/hostname
cat > /etc/hosts <<EOF
127.0.0.1 localhost
::1 localhost
127.0.1.1 $HOSTNAME_.localdomain $HOSTNAME_
EOF

echo "### users"
if id alarm >/dev/null 2>&1; then userdel -r alarm; fi
if ! id "$USERNAME" >/dev/null 2>&1; then useradd -m -G wheel,audio,video,input -s /bin/bash "$USERNAME"; fi
echo "$USERNAME:$PWHASH" | chpasswd -e
passwd -l root
install -d -m 750 /etc/sudoers.d
echo "%wheel ALL=(ALL:ALL) ALL" > /etc/sudoers.d/10-wheel
chmod 440 /etc/sudoers.d/10-wheel
visudo -cf /etc/sudoers.d/10-wheel
if [ "${SUDO_NOPASSWD:-0}" = 1 ]; then
  echo "$USERNAME ALL=(ALL:ALL) NOPASSWD: ALL" > "/etc/sudoers.d/20-$USERNAME-nopasswd"
  chmod 440 "/etc/sudoers.d/20-$USERNAME-nopasswd"
  visudo -cf "/etc/sudoers.d/20-$USERNAME-nopasswd"
fi
install -d -m 700 -o "$USERNAME" -g "$USERNAME" "/home/$USERNAME/.ssh"
install -m 600 -o "$USERNAME" -g "$USERNAME" /var/tmp/authorized_keys "/home/$USERNAME/.ssh/authorized_keys"

echo "### filesystem table"
cat > /etc/fstab <<EOF
# <file system> <dir> <type> <options> <dump> <pass>
UUID=$ROOT_UUID / ext4 defaults,noatime 0 1
# lk2nd boot file system: Android "cache" as plain ext2 (install/make-boot-partition.sh)
UUID=$BOOT_UUID /boot ext2 defaults,noatime,nofail,x-systemd.device-timeout=10s 0 2
EOF

echo "### network: systemd-networkd for the USB gadget, NetworkManager for the rest"
rm -f /etc/systemd/network/en.network /etc/systemd/network/eth.network
cat > /etc/systemd/network/10-usb-gadget.link <<'EOF'
[Match]
OriginalName=usb0

[Link]
NamePolicy=keep
Name=usb0
EOF
cat > /etc/systemd/network/20-usb-gadget.network <<'EOF'
[Match]
Name=usb0

[Network]
Address=172.16.42.1/24
DHCPServer=yes
ConfigureWithoutCarrier=yes

[DHCPServer]
PoolOffset=10
PoolSize=20
EmitDNS=no
EmitRouter=no
EOF
install -d /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/10-usb-gadget.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:usb0
EOF
cat > /etc/systemd/zram-generator.conf <<'EOF'
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
EOF

echo "### kernel module dependencies"
depmod -a "$KVER"

echo "### services"
systemctl enable sshd.service NetworkManager.service systemd-networkd.service systemd-resolved.service \
  systemd-timesyncd.service bluetooth.service t825-usb-gadget.service t825-extlinux-restore.service
systemctl mask systemd-networkd-wait-online.service
# Keep the user manager (PipeWire) running without a login session, e.g. over SSH.
install -d /var/lib/systemd/linger
touch "/var/lib/systemd/linger/$USERNAME"

echo "### cleanup"
cp /var/tmp/pacman.conf.orig /etc/pacman.conf
rm -f /var/tmp/pacman.conf.orig
# The device kernel has Landlock, so pacman keeps its download sandbox on the tablet.
ls /etc/pacman.conf.pacnew 2>/dev/null || true
rm -rf /var/cache/pacman/pkg/*
pacman -Q | wc -l
echo CHROOT_OK

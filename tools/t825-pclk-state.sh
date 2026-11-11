#!/bin/sh
# Read-only snapshot of the MDSS pixel/byte RCG state on the running tablet.
# Run as: ssh tabs3 sh -s < tools/t825-pclk-state.sh
# Reads single 32-bit registers from the MMCC regmap debugfs file with pread,
# plus common-clock debugfs state and this boot's RCG warnings. Writes nothing.
set -eu
R=/sys/kernel/debug/regmap/8c0000.clock-controller/registers
C=/sys/kernel/debug/clk
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
echo "kernel=$(uname -r) $(uname -v)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
sudo -n head -c 15 "$R" | grep -q '^0000: ' || { echo "error=unexpected regmap format"; exit 2; }
[ "$(sudo -n cat /sys/kernel/debug/regmap/8c0000.clock-controller/range)" = "0-b008" ] || { echo "error=unexpected regmap range"; exit 2; }
echo "warnings=$(sudo -n journalctl -k -b 0 --no-pager -q -o cat | grep -c "rcg didn't update its configuration" || true)"
sudo -n journalctl -k -b 0 --no-pager -q -o short-monotonic | grep -E "(pclk|byte)[01]_clk_src: rcg didn't update" | sed 's/^/warning_line=/' || true
for c in pclk0_clk_src pclk1_clk_src byte0_clk_src byte1_clk_src mdss_pclk0_clk mdss_pclk1_clk mdss_byte0_clk mdss_byte1_clk dsi0pll dsi0pllbyte dsi1pll dsi1pllbyte; do
  d=$C/$c
  echo "clk $c rate=$(sudo -n cat $d/clk_rate) enable=$(sudo -n cat $d/clk_enable_count) prepare=$(sudo -n cat $d/clk_prepare_count) parent=$(sudo -n cat $d/clk_parent 2>/dev/null || echo none)"
done
for base in 0x2000 0x2020 0x2120 0x2140; do
  for o in 0 4 8 12 16; do
    r=$((base + o))
    printf 'reg '; sudo -n dd if="$R" bs=15 skip=$((r / 4)) count=1 status=none
  done
done

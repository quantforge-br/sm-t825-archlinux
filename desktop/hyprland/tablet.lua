-- Galaxy Tab S3 (SM-T825) specifics, loaded after the DMS fragments.

hl.config({
	input = {
		-- Touch and S-Pen report the landscape panel frame: turn them like DSI-1
		-- (rotation.lua records its transform, from DMS or t825-autorotate).
		touchdevice = { transform = T825_DSI_TRANSFORM or 1, output = "DSI-1" },
		tablet = { transform = T825_DSI_TRANSFORM or 1, output = "DSI-1" },
	},
	-- Adreno 530 driving 2048x1536: keep the effects cheap.
	decoration = {
		shadow = { enabled = false },
		blur = { enabled = false },
	},
	-- Measured here in interleaved A/B runs: new render scheduling cuts the frames
	-- missed during a workspace switch by a third to a half and the browser-scroll
	-- p99 frame time from 33 to 27 ms, with no extra first-frame latency.
	render = { new_render_scheduling = true },
})

-- Home key (KEY_HOMEPAGE) opens the launcher.
hl.bind("XF86HomePage", hl.dsp.exec_cmd("dms ipc call spotlight toggle"))

-- Power key (KEY_POWER): panel off/on with t825-screen-toggle; logind ignores the
-- short press (/etc/systemd/logind.conf.d/50-t825-power-key.conf).
hl.bind("XF86PowerOff", hl.dsp.exec_cmd("t825-screen-toggle"), { locked = true })

-- t825-screen-toggle leaves this flag while the panel is off. It lives in this
-- instance's runtime directory, so a restarted Hyprland starts with input enabled.
local panel_off_flag = (os.getenv("XDG_RUNTIME_DIR") or "") .. "/hypr/"
	.. (os.getenv("HYPRLAND_INSTANCE_SIGNATURE") or "") .. "/t825-panel-off"
local flag_file = io.open(panel_off_flag, "r")
local input_enabled = flag_file == nil
if flag_file then
	flag_file:close()
end
hl.device({ name = "synaptics-s5807", enabled = input_enabled })
hl.device({ name = "wacom-w9019-digitizer", enabled = input_enabled })

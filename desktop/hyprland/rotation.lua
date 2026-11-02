-- Galaxy Tab S3 auto-rotation, loaded before dms.outputs.
-- t825-autorotate writes DSI-1's transform to <instance dir>/t825-transform and
-- runs "hyprctl reload"; this file puts it into the DSI-1 rule that DMS writes
-- (dms/outputs.lua keeps mode, position and scale). Without the file the
-- transform from dms/outputs.lua stands. tablet.lua reads T825_DSI_TRANSFORM.
local state = (os.getenv("XDG_RUNTIME_DIR") or "") .. "/hypr/"
	.. (os.getenv("HYPRLAND_INSTANCE_SIGNATURE") or "") .. "/t825-transform"
local forced = nil
local state_file = io.open(state, "r")
if state_file then
	forced = tonumber(state_file:read("l"))
	state_file:close()
end
T825_DSI_TRANSFORM = forced or 0

-- Wrap hl.monitor once per Lua state: a reload must not wrap the wrapper.
local monitor = rawget(_G, "T825_ORIG_MONITOR")
if monitor == nil or hl.monitor ~= rawget(_G, "T825_MONITOR_WRAPPER") then
	monitor = hl.monitor
end
T825_ORIG_MONITOR = monitor
T825_MONITOR_WRAPPER = function(rule)
	if rule.output == "DSI-1" then
		if forced then
			rule.transform = forced
		end
		T825_DSI_TRANSFORM = rule.transform or 0
	end
	return monitor(rule)
end
hl.monitor = T825_MONITOR_WRAPPER

# Desktop fluidity: what was measured

Hyprland on this tablet composites a 2048x1536 panel on an Adreno 530, so the GPU sets
the limit. These numbers come from frame traces on an SM-T825 running the desktop from
this repository: Hyprland 0.57, DMS, kitty and Brave, with window rounding 12 and border 2
kept as they are.

## Method

- Frames were counted from the `drm_msm_atomic` and `drm` tracepoints. A *missed* frame
  is a refresh that went by without a commit while the screen was animating.
- Scenarios:
  - **ws:** ten round trips between a workspace with a terminal and one with a browser
    window.
  - **web:** a page scrolls in Brave for 12 s.
  - **term:** a full-screen kitty receives text at 60 Hz.
  - **launch:** time from `exec` to the window mapping.
- The configurations ran interleaved (A B C, then B C A, ...) for four rounds, starting
  below 46 °C each time, so thermal and session drift is spread over all of them.

## Results

| Change | Effect | Kept |
|---|---|---|
| `render.new_render_scheduling = true` | ws missed frames −34% to −54%, browser-scroll p99 33 → 27 ms, same first-frame latency | yes (`desktop/hyprland/tablet.lua`) |
| `kitty --single-instance` | new terminal window in ~30 ms instead of 0.6–0.9 s | yes (tablet.lua bind, launcher entry from `desktop/install.sh`) |
| `render.cm_enabled = false` | no difference (switched while running) | no |
| GPU `min_freq` 315 / 401.8 MHz | no difference | no |
| GPU governor `performance` | about −10% missed frames, at a constant 624 MHz | no (heat, power) |
| DMS `reduceMotion` | no difference | no |
| No border color animation | no difference | no |
| Workspace animation speed 5 → 3 | same frame pacing, switch finishes 135 ms sooner | a matter of taste |
| Rounding 0, border 0 | large gain | no: changes the look |

Limits that remain:

- A kitty window full of scrolling text runs at 30–37 fps whatever the settings, with
  the GPU at 624 MHz nearly all the time.
- The DMS bar and wallpaper still take a visible share of each workspace switch.
  Stopping DMS, as a diagnostic, removed most of the remaining jank.

Without new frames there is no rendering to save: the browser already scrolls at
58–59 fps, and an idle desktop commits almost nothing.

## Undoing

- Remove the `render` line from `~/.config/hypr/tablet.lua` and run `hyprctl reload`.
- Delete `~/.local/share/applications/kitty.desktop` and the two kitty lines in
  `tablet.lua`.

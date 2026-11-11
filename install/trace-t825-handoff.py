#!/usr/bin/env python3
"""Add bounded, repeatable stage tracing to the transient pmOS stage-2 init."""
from __future__ import annotations

import pathlib
import re
import sys


TRACE_FUNCTION = '''trace_handoff_stage() {
\tlocal stage="$1" directory=/run/t825-recovery
\t[ -d "$directory" ] || directory=/sysroot/run/t825-recovery
\techo "$stage" > "$directory/handoff-stage"
\t# Keep each report bounded even if the host or network is unavailable.
\tprintf '%s\\n' "$stage" | busybox timeout 2 busybox nc -w 1 172.16.42.2 2324 >/dev/null 2>&1 || true
}

'''


def instrument(text: str) -> str:
    if 'trace_handoff_stage()' in text and 'hook-pre-${handoff_hook##*/}' in text:
        return text
    # Normalize both older echo-only traces and a previously instrumented
    # source. Remove only our own standalone statements, never pmOS logic.
    text = re.sub(r'^trace_handoff_stage\(\) \{\n.*?^\}\n\n?', '', text,
                  flags=re.MULTILINE | re.DOTALL)
    text = re.sub(r'^(?:echo [\w-]+ > /run/t825-recovery/handoff-stage|'
                  r'trace_handoff_stage [\w-]+)\n', '', text, flags=re.MULTILINE)
    anchors = {
        'if [ "$debug_shell" = "y" ]; then\n\tdebug_shell\nfi\n':
            ('pre-debug', 'post-debug'),
        'mount_subpartitions\n': ('pre-mount-subpartitions', 'post-mount-subpartitions'),
        'run_hooks /hooks-extra\n': ('pre-hooks-extra', 'post-hooks-extra'),
        'wait_root_partition\n': ('pre-wait-root', 'post-wait-root'),
        'delete_old_install_partition\n': ('pre-delete-old-root', 'post-delete-old-root'),
        'resize_root_partition\n': ('pre-resize-root-partition', 'post-resize-root-partition'),
        'unlock_root_partition\n': ('pre-unlock-root', 'post-unlock-root'),
        'resize_root_filesystem\n': ('pre-resize-root-fs', 'post-resize-root-fs'),
        'mount_root_partition\n': ('pre-mount-root', 'post-mount-root'),
        'resize_filesystem_after_mount /sysroot\n': ('pre-resize-mounted-root', 'post-resize-mounted-root'),
        'run_hooks /hooks-cleanup\n': ('pre-cleanup', 'post-cleanup'),
        'exec switch_root /sysroot "$init"\n': ('pre-switch-root', None),
    }
    for anchor, (before, after) in anchors.items():
        if anchor == 'run_hooks /hooks-cleanup\n' and 'hook-pre-${handoff_hook##*/}' in text:
            continue
        if text.count(anchor) != 1:
            raise ValueError(f'handoff trace anchor changed: {anchor!r}')
        replacement = f'trace_handoff_stage {before}\n' + anchor
        if after:
            replacement += f'trace_handoff_stage {after}\n'
        if anchor == 'run_hooks /hooks-cleanup\n':
            # The generic helper aborts stage 2 on a hook error, hiding which
            # cleanup script failed. Wrap each transient hook with markers and
            # preserve the original fail-fast behavior.
            replacement = (
                'trace_handoff_stage pre-cleanup\n'
                'for handoff_hook in /hooks-cleanup/*.sh; do\n'
                '\t[ -e "$handoff_hook" ] || continue\n'
                '\ttrace_handoff_stage "hook-pre-${handoff_hook##*/}"\n'
                '\tsh "$handoff_hook" || { trace_handoff_stage "hook-fail-${handoff_hook##*/}"; exit 1; }\n'
                '\ttrace_handoff_stage "hook-post-${handoff_hook##*/}"\n'
                'done\n'
                'trace_handoff_stage post-cleanup\n'
            )
        if before == 'pre-debug':
            replacement = TRACE_FUNCTION + replacement
        text = text.replace(anchor, replacement, 1)
    return text


if __name__ == '__main__':
    path = pathlib.Path(sys.argv[1])
    path.write_text(instrument(path.read_text()))

# -*- coding: utf-8 -*-
"""探测微信 4.x (Qt) 主窗口的 UIA 控件树，判断可读性。"""
import sys
import uiautomation as auto

auto.SetGlobalSearchTimeout(5)

TARGET_PID = int(sys.argv[1]) if len(sys.argv) > 1 else 2960
MAX_DEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 6


def dump(ctrl, depth=0, max_depth=MAX_DEPTH, out=None):
    if out is None:
        out = []
    if depth > max_depth:
        return out
    try:
        r = ctrl.BoundingRectangle
        rect = f"({r.left},{r.top},{r.right},{r.bottom})" if r else "()"
        name = (ctrl.Name or "").replace("\n", "\\n")[:60]
        out.append(
            "  " * depth
            + f"{ctrl.ControlTypeName} cls=[{ctrl.ClassName}] name=[{name}] "
            + f"aid=[{ctrl.AutomationId}] offscreen={ctrl.IsOffscreen} {rect}"
        )
    except Exception as e:
        out.append("  " * depth + f"<err {e}>")
        return out
    try:
        children = ctrl.GetChildren()
    except Exception:
        children = []
    for c in children:
        dump(c, depth + 1, max_depth, out)
    return out


root = auto.GetRootControl()
candidates = []
for w in root.GetChildren():
    try:
        if w.ProcessId == TARGET_PID:
            candidates.append(w)
    except Exception:
        pass

print(f"found {len(candidates)} top-level windows for pid {TARGET_PID}")
for i, w in enumerate(candidates):
    print(f"\n===== window #{i} class=[{w.ClassName}] name=[{w.Name}] =====")
    lines = dump(w, 0, MAX_DEPTH)
    print("\n".join(lines[:120]))
    print(f"... total nodes shown {min(len(lines),120)} / {len(lines)}")

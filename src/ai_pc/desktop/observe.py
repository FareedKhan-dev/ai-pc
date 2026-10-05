"""Turn a UIA snapshot into the compact text the planner reads."""


def _flags(e):
    f = []
    if e.toggled is not None:
        f.append({0: "off", 1: "on", 2: "mixed"}.get(e.toggled, "?"))
    if not e.enabled:
        f.append("disabled")
    if e.focus:
        f.append("focused")
    return f


def render(snap, max_lines=140, name_len=60):
    lines = []
    rich = snap.richness
    kind = "rich" if rich >= 6 else ("thin" if rich else "EMPTY")
    lines.append(f'APP: {snap.proc} (pid {snap.pid}) | window "{snap.title[:70]}" | richness: {kind} ({rich} interactable of {len(snap.els)} elements)')
    foc = next((e.id for e in snap.els if e.focus), None)
    lines.append(f"FOCUS: {foc or '-'}")
    if kind != "rich":
        lines.append("NOTE: the UI tree is thin; for anything not listed use ground_click with a plain-words target (a screenshot may be attached).")
    lines.append("ELEMENTS:")
    shown = 0
    for e in snap.els:
        if shown >= max_lines:
            lines.append(f"... (+{len(snap.els) - shown} more elements omitted)")
            break
        nm = e.name.replace('"', "'").replace("\n", " ")[:name_len]
        aid = f" [{e.aid}]" if e.aid else ""
        ops = " {" + ",".join(e.ops) + "}" if e.ops else ""
        fl = " (" + ",".join(_flags(e)) + ")" if _flags(e) else ""
        val = ""
        if e.password:
            val = " value=<hidden password>"
        elif e.value or e.role == "Edit":
            v = e.value.replace('"', "'").replace(chr(10), " ")
            val = f' value="{v[:50]}"' + ("..." if len(v) > 50 else "")
        lines.append(f'{e.id} {e.role} "{nm}"{aid}{ops}{val}{fl}')
        shown += 1
    return "\n".join(lines)

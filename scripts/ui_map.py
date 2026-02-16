"""AST-based UI map extractor for SEO Master Bot.

Parses all routers/ and keyboards/ to extract:
- StatesGroup classes and their states
- Handler registrations (callback_query, message) with filters
- Keyboard definitions with buttons and callback_data
- FSM transitions (set_state, clear)

Outputs:
1. Text report (ui_map_report.md)
2. Mermaid stateDiagram-v2 (ui_map.mermaid)
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class StateInfo:
    name: str
    fsm_class: str
    file: str
    line: int


@dataclass
class HandlerInfo:
    func_name: str
    handler_type: str  # "callback_query" | "message"
    filters: list[str]  # human-readable filter descriptions
    state_filter: str | None  # e.g. "ProjectCreateFSM.name"
    callback_data_filter: str | None  # e.g. 'F.data == "projects:new"'
    # Structured filter data for matching (raw values from AST)
    cb_exact: str | None = None  # exact match value from F.data == "..."
    cb_regex: str | None = None  # raw regex from F.data.regexp(r"...")
    cb_prefix: str | None = None  # prefix from F.data.startswith("...")
    file: str = ""
    line: int = 0
    transitions_to: list[str] = field(default_factory=list)  # ["ProjectCreateFSM.name", ...]
    clears_state: bool = False


@dataclass
class ButtonInfo:
    text: str
    callback_data: str  # pattern with {id} placeholders
    keyboard_func: str
    file: str
    line: int


@dataclass
class KeyboardInfo:
    func_name: str
    file: str
    line: int
    buttons: list[ButtonInfo] = field(default_factory=list)


@dataclass
class FSMGroup:
    class_name: str
    states: list[str]
    file: str
    line: int


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------


def _rel_path(path: Path, root: Path) -> str:
    """Return short relative path from project root."""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _unparse_filter(node: ast.expr) -> str:
    """Best-effort human-readable representation of a filter AST node."""
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def _extract_fstring_pattern(node: ast.JoinedStr) -> str:
    """Convert f-string AST to pattern like 'project:{id}:card'."""
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
        elif isinstance(value, ast.FormattedValue):
            # Try to get a meaningful name from the expression
            inner = value.value
            if isinstance(inner, ast.Attribute):
                parts.append(f"{{{inner.attr}}}")
            elif isinstance(inner, ast.Name):
                parts.append(f"{{{inner.id}}}")
            elif isinstance(inner, ast.Subscript):
                parts.append("{...}")
            else:
                parts.append("{*}")
    return "".join(parts)


def _extract_callback_data_kwarg(call_node: ast.Call) -> str | None:
    """Extract callback_data value from a builder.button() call."""
    for kw in call_node.keywords:
        if kw.arg == "callback_data":
            if isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
            if isinstance(kw.value, ast.JoinedStr):
                return _extract_fstring_pattern(kw.value)
            return ast.unparse(kw.value)
    return None


def _extract_text_kwarg(call_node: ast.Call) -> str | None:
    """Extract text value from a builder.button() call."""
    for kw in call_node.keywords:
        if kw.arg == "text":
            if isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
            if isinstance(kw.value, ast.JoinedStr):
                return _extract_fstring_pattern(kw.value)
            return ast.unparse(kw.value)
    # Also check positional args — text is often first positional
    if call_node.args:
        arg = call_node.args[0]
        if isinstance(arg, ast.Constant):
            return str(arg.value)
    return None


def _detect_state_filter(args: list[ast.expr]) -> str | None:
    """Detect FSM state filter like ProjectCreateFSM.name in decorator args."""
    for arg in args:
        if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
            name = arg.value.id
            if name.endswith("FSM"):
                return f"{name}.{arg.attr}"
    return None


def _detect_callback_data_filter(args: list[ast.expr]) -> tuple[str | None, str | None, str | None, str | None]:
    """Detect F.data filters and return (display, exact, regex, prefix).

    Returns raw values extracted directly from AST Constant nodes
    to avoid ast.unparse backslash-doubling issues.
    """
    for arg in args:
        unparsed = _unparse_filter(arg)
        if "F.data" not in unparsed:
            continue

        # Case 1: F.data == "exact_string" — Compare node
        if isinstance(arg, ast.Compare) and arg.ops and isinstance(arg.ops[0], ast.Eq) and arg.comparators:
            comp = arg.comparators[0]
            if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                return (unparsed, comp.value, None, None)

        # Case 2: F.data.regexp(r"pattern") — Call node
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
            if arg.func.attr == "regexp" and arg.args:
                a = arg.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    return (unparsed, None, a.value, None)

            # Case 3: F.data.startswith("prefix")
            if arg.func.attr == "startswith" and arg.args:
                a = arg.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    return (unparsed, None, None, a.value)

        # Fallback: unrecognized F.data pattern
        return (unparsed, None, None, None)

    return (None, None, None, None)


def parse_file(filepath: Path, root: Path) -> tuple[list[FSMGroup], list[HandlerInfo], list[KeyboardInfo]]:
    """Parse a single Python file and extract FSM, handlers, keyboards."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return [], [], []

    rel = _rel_path(filepath, root)
    fsm_groups: list[FSMGroup] = []
    handlers: list[HandlerInfo] = []
    keyboards: list[KeyboardInfo] = []

    for node in ast.iter_child_nodes(tree):
        # 1) StatesGroup classes
        if isinstance(node, ast.ClassDef):
            bases = [
                b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else "" for b in node.bases
            ]
            if "StatesGroup" in bases:
                states = []
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if isinstance(item.value, ast.Call):
                                    func = item.value.func
                                    if isinstance(func, ast.Name) and func.id == "State":
                                        states.append(target.id)
                fsm_groups.append(
                    FSMGroup(
                        class_name=node.name,
                        states=states,
                        file=rel,
                        line=node.lineno,
                    )
                )

        # 2) Handler functions (top-level or in module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _parse_handler(node, rel, handlers)

        # 3) Keyboard builder functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _parse_keyboard(node, rel, keyboards)

    return fsm_groups, handlers, keyboards


def _parse_handler(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel: str,
    handlers: list[HandlerInfo],
) -> None:
    """Extract handler info from a decorated function."""
    for dec in func_node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func_ref = dec.func
        if not isinstance(func_ref, ast.Attribute):
            continue
        if func_ref.attr not in ("callback_query", "message"):
            continue

        handler_type = func_ref.attr
        filters = [_unparse_filter(a) for a in dec.args]
        state_filter = _detect_state_filter(dec.args)
        cb_display, cb_exact, cb_regex, cb_prefix = _detect_callback_data_filter(dec.args)

        # Find set_state / clear transitions in body
        transitions: list[str] = []
        clears = False
        for child in ast.walk(func_node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr == "set_state" and child.args:
                    arg = child.args[0]
                    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                        transitions.append(f"{arg.value.id}.{arg.attr}")
                    else:
                        transitions.append(_unparse_filter(arg))
                elif child.func.attr == "clear":
                    # Check it's state.clear()
                    if isinstance(child.func.value, ast.Name) and child.func.value.id == "state":
                        clears = True

        handlers.append(
            HandlerInfo(
                func_name=func_node.name,
                handler_type=handler_type,
                filters=filters,
                state_filter=state_filter,
                callback_data_filter=cb_display,
                cb_exact=cb_exact,
                cb_regex=cb_regex,
                cb_prefix=cb_prefix,
                file=rel,
                line=func_node.lineno,
                transitions_to=transitions,
                clears_state=clears,
            )
        )


def _parse_keyboard(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel: str,
    keyboards: list[KeyboardInfo],
) -> None:
    """Extract keyboard builder function with its buttons."""
    buttons: list[ButtonInfo] = []

    for child in ast.walk(func_node):
        if not isinstance(child, ast.Call):
            continue
        if not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr != "button":
            continue

        text = _extract_text_kwarg(child) or "?"
        cb_data = _extract_callback_data_kwarg(child)
        if cb_data is None:
            # Check for url= kwarg (not a callback, skip)
            has_url = any(kw.arg == "url" for kw in child.keywords)
            if has_url:
                continue
            cb_data = "?"

        buttons.append(
            ButtonInfo(
                text=text,
                callback_data=cb_data,
                keyboard_func=func_node.name,
                file=rel,
                line=child.lineno,
            )
        )

    if buttons:
        keyboards.append(
            KeyboardInfo(
                func_name=func_node.name,
                file=rel,
                line=func_node.lineno,
                buttons=buttons,
            )
        )


# ---------------------------------------------------------------------------
# Scan project
# ---------------------------------------------------------------------------


def scan_project(root: Path) -> tuple[list[FSMGroup], list[HandlerInfo], list[KeyboardInfo]]:
    """Scan all .py files in routers/ and keyboards/."""
    all_fsm: list[FSMGroup] = []
    all_handlers: list[HandlerInfo] = []
    all_keyboards: list[KeyboardInfo] = []

    for directory in ["routers", "keyboards"]:
        dir_path = root / directory
        if not dir_path.exists():
            continue
        for py_file in sorted(dir_path.rglob("*.py")):
            if py_file.name.startswith("_") and py_file.name != "_helpers.py":
                continue
            if py_file.name == "__init__.py":
                continue
            fsm, hdl, kb = parse_file(py_file, root)
            all_fsm.extend(fsm)
            all_handlers.extend(hdl)
            all_keyboards.extend(kb)

    return all_fsm, all_handlers, all_keyboards


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


def generate_report(
    fsm_groups: list[FSMGroup],
    handlers: list[HandlerInfo],
    keyboards: list[KeyboardInfo],
) -> str:
    """Generate Markdown report."""
    lines: list[str] = []
    lines.append("# UI Map Report — SEO Master Bot\n")
    lines.append("Auto-generated from AST analysis.\n")

    # --- FSM Groups ---
    lines.append("## 1. FSM StatesGroup Classes\n")
    lines.append(f"Total: **{len(fsm_groups)}** FSM groups\n")
    for fsm in fsm_groups:
        lines.append(f"### {fsm.class_name}")
        lines.append(f"File: `{fsm.file}:{fsm.line}`\n")
        lines.append(f"States ({len(fsm.states)}):")
        for i, s in enumerate(fsm.states, 1):
            lines.append(f"  {i}. `{s}`")
        lines.append("")

    # --- Handlers ---
    lines.append("## 2. Handlers\n")
    lines.append(f"Total: **{len(handlers)}** handlers")
    cb_handlers = [h for h in handlers if h.handler_type == "callback_query"]
    msg_handlers = [h for h in handlers if h.handler_type == "message"]
    lines.append(f"  - callback_query: {len(cb_handlers)}")
    lines.append(f"  - message: {len(msg_handlers)}\n")

    # Group by file
    files_seen: dict[str, list[HandlerInfo]] = {}
    for h in handlers:
        files_seen.setdefault(h.file, []).append(h)

    for file, file_handlers in sorted(files_seen.items()):
        lines.append(f"### {file}\n")
        lines.append("| Handler | Type | State Filter | callback_data Filter | Transitions |")
        lines.append("|---------|------|-------------|---------------------|-------------|")
        for h in file_handlers:
            state = h.state_filter or "-"
            cb = h.callback_data_filter or "-"
            if len(cb) > 50:
                cb = cb[:47] + "..."
            trans_parts = []
            if h.transitions_to:
                trans_parts.extend(h.transitions_to)
            if h.clears_state:
                trans_parts.append("CLEAR")
            trans = ", ".join(trans_parts) if trans_parts else "-"
            lines.append(f"| `{h.func_name}` | {h.handler_type} | `{state}` | `{cb}` | {trans} |")
        lines.append("")

    # --- Keyboards ---
    lines.append("## 3. Keyboards\n")
    lines.append(f"Total: **{len(keyboards)}** keyboard builders\n")

    for kb in keyboards:
        lines.append(f"### {kb.func_name}()")
        lines.append(f"File: `{kb.file}:{kb.line}`\n")
        lines.append("| Button Text | callback_data |")
        lines.append("|-------------|---------------|")
        for btn in kb.buttons:
            lines.append(f"| {btn.text} | `{btn.callback_data}` |")
        lines.append("")

    # --- Navigation graph ---
    lines.append("## 4. Navigation Graph (callback_data links)\n")
    lines.append("Which keyboard button leads to which handler:\n")

    # Build lookup: callback_data pattern -> handler
    handler_lookup: dict[str, str] = {}
    for h in handlers:
        if h.callback_data_filter:
            # Extract the pattern from filter
            pattern = h.callback_data_filter
            handler_lookup[pattern] = f"{h.func_name} ({h.file})"

    # For each keyboard, try to match buttons to handlers
    for kb in keyboards:
        lines.append(f"**{kb.func_name}()** ({kb.file}):")
        for btn in kb.buttons:
            target = _find_handler_for_callback(btn.callback_data, handlers)
            if target:
                lines.append(
                    f"  - [{btn.text}] `{btn.callback_data}` -> `{target.func_name}` ({target.file}:{target.line})"
                )
            else:
                lines.append(f"  - [{btn.text}] `{btn.callback_data}` -> ???")
        lines.append("")

    return "\n".join(lines)


def _find_handler_for_callback(callback_data: str, handlers: list[HandlerInfo]) -> HandlerInfo | None:
    """Match a callback_data pattern to its handler.

    Uses structured cb_exact/cb_regex/cb_prefix fields that contain
    raw values extracted from AST Constant nodes (no backslash issues).
    """
    # Build test string: replace {var} placeholders with digits
    test_str = re.sub(r"\{[^}]+\}", "123", callback_data)

    for h in handlers:
        if h.handler_type != "callback_query":
            continue

        # Case 1: exact match — F.data == "value"
        if h.cb_exact is not None and (h.cb_exact == callback_data or h.cb_exact == test_str):
            return h

        # Case 2: regex match — F.data.regexp(r"^pattern$")
        if h.cb_regex is not None:
            try:
                if re.fullmatch(h.cb_regex, callback_data):
                    return h
                if re.fullmatch(h.cb_regex, test_str):
                    return h
            except re.error:
                pass

        # Case 3: prefix match — F.data.startswith("prefix")
        if h.cb_prefix is not None:
            if callback_data.startswith(h.cb_prefix) or test_str.startswith(h.cb_prefix):
                return h

    return None


# ---------------------------------------------------------------------------
# Mermaid generator
# ---------------------------------------------------------------------------


def generate_mermaid(
    fsm_groups: list[FSMGroup],
    handlers: list[HandlerInfo],
    keyboards: list[KeyboardInfo],
) -> str:
    """Generate Mermaid stateDiagram-v2 showing FSM flows + screen navigation."""
    lines: list[str] = []
    lines.append("stateDiagram-v2")
    lines.append("")

    # --- FSM state machines (with real transitions from handlers) ---
    # Build transition map: for handlers in state X that call set_state(Y)
    fsm_transitions: dict[str, set[str]] = {}  # "FSM.state" -> {"FSM.next_state", ...}
    fsm_clears: dict[str, bool] = {}  # "FSM.state" -> True if handler clears state
    for h in handlers:
        if not h.state_filter:
            continue
        for trans in h.transitions_to:
            fsm_transitions.setdefault(h.state_filter, set()).add(trans)
        if h.clears_state:
            fsm_clears[h.state_filter] = True

    for fsm in fsm_groups:
        safe_name = fsm.class_name.replace("FSM", "")
        fsm_name = fsm.class_name
        lines.append(f"    state {safe_name} {{")

        # Define all states
        for state in fsm.states:
            state_id = f"{safe_name}_{state}"
            lines.append(f"        {state_id}: {state}")

        # Entry: [*] → first state
        if fsm.states:
            lines.append(f"        [*] --> {safe_name}_{fsm.states[0]}")

        # Draw real transitions
        drawn_edges: set[str] = set()
        for state in fsm.states:
            src_key = f"{fsm_name}.{state}"
            src_id = f"{safe_name}_{state}"
            targets = fsm_transitions.get(src_key, set())
            for target in targets:
                parts = target.split(".")
                if len(parts) == 2 and parts[0] == fsm_name:
                    tgt_id = f"{safe_name}_{parts[1]}"
                    edge = f"{src_id}-->{tgt_id}"
                    if edge not in drawn_edges:
                        drawn_edges.add(edge)
                        lines.append(f"        {src_id} --> {tgt_id}")
            # If handler clears state, draw exit
            if fsm_clears.get(src_key):
                edge = f"{src_id}-->[*]"
                if edge not in drawn_edges:
                    drawn_edges.add(edge)
                    lines.append(f"        {src_id} --> [*]")

        # If no transitions found for last state, add exit
        if fsm.states:
            last_id = f"{safe_name}_{fsm.states[-1]}"
            exit_edge = f"{last_id}-->[*]"
            if exit_edge not in drawn_edges:
                lines.append(f"        {last_id} --> [*]")

        lines.append("    }")
        lines.append("")

    # --- Screen navigation (keyboard -> handler) ---
    lines.append("    %% Screen navigation")
    lines.append("")

    # Define screen nodes from keyboard functions
    screen_nodes: set[str] = set()
    for kb in keyboards:
        node_name = kb.func_name.replace("_kb", "").replace("_confirm", "_cfm")
        screen_nodes.add(node_name)
        lines.append(f'    state "{_humanize(kb.func_name)}" as {node_name}')

    lines.append("")

    # Draw edges from screens to other screens or FSM entry points
    edges_seen: set[str] = set()
    for kb in keyboards:
        src = kb.func_name.replace("_kb", "").replace("_confirm", "_cfm")
        for btn in kb.buttons:
            target_handler = _find_handler_for_callback(btn.callback_data, handlers)
            if not target_handler:
                continue

            # Determine target node
            target_node = _handler_to_screen(target_handler, keyboards, fsm_groups)
            if not target_node or target_node == src:
                continue

            edge_key = f"{src}-->{target_node}"
            if edge_key in edges_seen:
                continue
            edges_seen.add(edge_key)

            # Shorten label
            label = btn.text
            if len(label) > 25:
                label = label[:22] + "..."
            lines.append(f"    {src} --> {target_node}: {label}")

    lines.append("")

    # --- Entry points from handlers that start FSMs ---
    lines.append("    %% FSM entry points")
    for h in handlers:
        if not h.transitions_to:
            continue
        for trans in h.transitions_to:
            parts = trans.split(".")
            if len(parts) == 2:
                fsm_class = parts[0].replace("FSM", "")
                state_name = parts[1]
                # Only draw entry if this is the first state of that FSM
                for fsm in fsm_groups:
                    if fsm.class_name.replace("FSM", "") == fsm_class:
                        if fsm.states and fsm.states[0] == state_name:
                            # Find source screen
                            src_screen = _handler_to_source_screen(h, keyboards)
                            if src_screen:
                                edge_key = f"{src_screen}-->_{fsm_class}"
                                if edge_key not in edges_seen:
                                    edges_seen.add(edge_key)
                                    lines.append(f"    {src_screen} --> {fsm_class}: Start {fsm_class}")
                        break

    return "\n".join(lines)


def _humanize(func_name: str) -> str:
    """Convert function name to human-readable label."""
    name = func_name.replace("_kb", "").replace("_confirm", " Confirm")
    name = name.replace("_", " ").title()
    return name


def _handler_to_screen(
    handler: HandlerInfo,
    keyboards: list[KeyboardInfo],
    fsm_groups: list[FSMGroup],
) -> str | None:
    """Determine which screen a handler renders.

    Uses handler name patterns and callback_data to map to screen nodes.
    Screen node names must match keyboard func_name.replace("_kb", "").
    """
    name = handler.func_name

    # --- 1) Handler name patterns ---
    # IMPORTANT: More specific patterns must come first (checked via `in` operator)
    # e.g. "scheduler_categories" before "categories"
    _NAME_PATTERNS_ORDERED: list[tuple[str, str]] = [
        # Scheduler (must be before "categories")
        ("scheduler_categories", "scheduler_category_list"),
        ("scheduler_main", "scheduler_category_list"),
        ("scheduler_cat", "scheduler_category_list"),
        ("schedule_summary", "schedule_summary"),
    ]
    for pattern, screen in _NAME_PATTERNS_ORDERED:
        if pattern in name:
            return screen

    _NAME_PATTERNS = {
        "project_card": "project_card",
        "project_list": "project_list",
        "projects_list": "project_list",
        "category_card": "category_card",
        "category_list": "category_list",
        "categories_list": "category_list",
        "categories": "category_list",
        "profile_main": "profile_main",
        "profile_history": "profile_history",
        "profile_referral": "profile_referral",
        "settings_main": "settings_main",
        "settings_notif": "settings_notifications",
        "tariffs_main": "tariffs_main",
        "tariffs_topup": "package_list",
        "dashboard": "dashboard",
        "menu_main": "dashboard",
        "help_main": "help_main",
        "help": "help_main",
        "admin_main": "admin_dashboard",
        "admin_monitor": "admin_dashboard",
        "admin_costs": "admin_dashboard",
        "admin_broadcast": "admin_broadcast_audience",
        # Connections
        "connection_list": "_connection_list",
        "connections": "_connection_list",
        "connection_card": "_connection_card",
        # Publishing
        "article_confirm": "article_cfm",
        "article_preview": "article_preview",
        "social_confirm": "social_cfm",
        "social_review": "social_review",
        "quick_combo": "quick_combo_list",
        "quick_publish": "quick_combo_list",
        # Category sub-screens
        "kw_main": "keywords_main",
        "keywords_main": "keywords_main",
        "keyword_results": "keyword_results",
        "kw_results": "keyword_results",
        "description_card": "description_existing",
        "description_existing": "description_existing",
        "reviews_card": "review_existing",
        "reviews_main": "review_existing",
        "prices_card": "price_existing",
        "prices_main": "price_existing",
        "media_card": "media_menu",
        "media_main": "media_menu",
        # Audit
        "audit_card": "audit_menu",
        "audit_main": "audit_menu",
        "audit_results": "audit_results",
        "competitor_results": "competitor_results",
        # Scheduler — handled in _NAME_PATTERNS_ORDERED above
        # Payments
        "package_select": "package_pay",
        "sub_select": "subscription_pay",
        "sub_manage": "subscription_manage",
    }

    for pattern, screen in _NAME_PATTERNS.items():
        if pattern in name:
            return screen

    # --- 2) callback_data patterns (raw values from structured fields) ---
    # Check cb_exact first
    exact = handler.cb_exact
    if exact:
        _EXACT_MAP = {
            "projects:new": "project_list",
            "projects:list": "project_list",
            "menu:main": "dashboard",
            "profile:main": "profile_main",
            "profile:history": "profile_history",
            "profile:referral": "profile_referral",
            "tariffs:main": "tariffs_main",
            "tariffs:topup": "package_list",
            "settings:main": "settings_main",
            "help:main": "help_main",
            "admin:main": "admin_dashboard",
            "admin:monitoring": "admin_dashboard",
            "admin:costs": "admin_dashboard",
            "admin:broadcast": "admin_broadcast_audience",
        }
        if exact in _EXACT_MAP:
            return _EXACT_MAP[exact]

    # Check cb_regex for structural patterns
    regex = handler.cb_regex
    if regex:
        _REGEX_MAP = [
            (r"project.*:card", "project_card"),
            (r"project.*:edit", "project_edit_fields"),
            (r"project.*:categories", "category_list"),
            (r"project.*:cat:new", "category_list"),
            (r"project.*:connections", "_connection_list"),
            (r"project.*:scheduler", "scheduler_category_list"),
            (r"project.*:audit\$", "audit_menu"),
            (r"project.*:audit:run", "audit_results"),
            (r"project.*:competitor", "competitor_cfm"),
            (r"project.*:delete\$", "project_delete_cfm"),
            (r"project.*:delete:confirm", "project_list"),
            (r"project.*:timezone", "project_card"),
            (r"category.*:card", "category_card"),
            (r"category.*:publish\$", "publish_platform_choice"),
            (r"category.*:keywords", "keywords_main"),
            (r"category.*:description", "description_existing"),
            (r"category.*:prices\$", "price_existing"),
            (r"category.*:prices:update", "price_method"),
            (r"category.*:reviews\$", "review_existing"),
            (r"category.*:reviews:regen", "review_quantity"),
            (r"category.*:media", "media_menu"),
            (r"category.*:delete\$", "category_delete_cfm"),
            (r"category.*:delete:confirm", "category_list"),
            (r"category.*:img_settings", "category_card"),
            (r"category.*:text_settings", "category_card"),
            (r"conn.*:card", "_connection_card"),
            (r"conn.*:delete\$", "_connection_delete_cfm"),
            (r"conn.*:delete:confirm", "_connection_list"),
            (r"page:projects", "project_list"),
            (r"page:categories", "category_list"),
            (r"sched:cat:\(", "scheduler_platform_list"),
            (r"price:cat.*:text", "price_method"),
            (r"price:cat.*:excel", "price_method"),
            (r"price:cat.*:clear", "price_existing"),
            (r"tariff:.*:select", "package_pay"),
            (r"sub:.*:select", "subscription_pay"),
            (r"kw:qty:", "keyword_quantity"),
            (r"review:qty:", "review_quantity"),
        ]
        for pat, screen in _REGEX_MAP:
            if re.search(pat, regex):
                return screen

    # Check cb_prefix
    prefix = handler.cb_prefix
    if prefix:
        _PREFIX_MAP = {
            "settings:notify:": "settings_notifications",
            "page:projects:": "project_list",
            "vk_group:": "_connection_list",
            "pin_board:": "_connection_list",
        }
        for pfx, screen in _PREFIX_MAP.items():
            if prefix == pfx:
                return screen

    return None


def _handler_to_source_screen(handler: HandlerInfo, keyboards: list[KeyboardInfo]) -> str | None:
    """Find the screen (keyboard) that triggers this handler."""
    if not handler.callback_data_filter:
        return None

    # Find which keyboard has a button matching this handler's filter
    for kb in keyboards:
        for btn in kb.buttons:
            target = _find_handler_for_callback(btn.callback_data, [handler])
            if target:
                return kb.func_name.replace("_kb", "").replace("_confirm", "_cfm")

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _safe_print(text: str) -> None:
    """Print with fallback for Windows console encoding issues."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    output_dir = root / "docs"
    output_dir.mkdir(exist_ok=True)

    print(f"Scanning project: {root}")
    fsm_groups, handlers, keyboards = scan_project(root)

    print(f"Found: {len(fsm_groups)} FSM groups, {len(handlers)} handlers, {len(keyboards)} keyboards")

    # Generate report
    report = generate_report(fsm_groups, handlers, keyboards)
    report_path = output_dir / "ui_map_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report: {report_path}")

    # Generate Mermaid
    mermaid = generate_mermaid(fsm_groups, handlers, keyboards)
    mermaid_path = output_dir / "ui_map.mermaid"
    mermaid_path.write_text(mermaid, encoding="utf-8")
    print(f"Mermaid: {mermaid_path}")

    # Also print summary
    print("\n--- FSM Summary ---")
    for fsm in fsm_groups:
        print(f"  {fsm.class_name} ({len(fsm.states)} states): {', '.join(fsm.states)}")

    print("\n--- Handler Summary ---")
    print(f"  callback_query: {sum(1 for h in handlers if h.handler_type == 'callback_query')}")
    print(f"  message: {sum(1 for h in handlers if h.handler_type == 'message')}")

    print("\n--- Keyboard Summary ---")
    total_buttons = sum(len(kb.buttons) for kb in keyboards)
    print(f"  {len(keyboards)} keyboards, {total_buttons} total buttons")

    # Print unmatched buttons (buttons that don't lead to any handler)
    unmatched = []
    for kb in keyboards:
        for btn in kb.buttons:
            if btn.callback_data == "?":
                continue
            target = _find_handler_for_callback(btn.callback_data, handlers)
            if not target:
                unmatched.append((kb.func_name, btn.text, btn.callback_data))

    if unmatched:
        print(f"\n--- Unmatched Buttons ({len(unmatched)}) ---")
        for kb_name, text, data in unmatched:
            _safe_print(f"  [{text}] callback_data='{data}' in {kb_name}()")


if __name__ == "__main__":
    main()

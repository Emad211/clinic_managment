"""Journey templates: data-driven definitions → concrete steps (docs/05 §5, §7). Pure.

Day values in a definition are integers or tiny expressions over the journey's
parameters, e.g. ``"max(1, {due_day} - 10)"``. Only integers, ``+ - *``,
unary minus, ``max``/``min`` and ``{param}`` references are allowed; anything
else is rejected when the template is parsed, never evaluated.

Day arithmetic (G1): day 0 is the origin invoice's ``work_date``; "one month"
is 30 days (A16). An expect step's window is ``[day, end]`` where ``end`` is
given directly or as ``day + window_days``.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Mapping

CATEGORIES = frozenset({"visit", "bs_test", "bp_check", "dressing", "suture_removal", "ear_irrigation", "nebulizer"})
_PARAM = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_FUNCS = {"max": max, "min": min}
MAX_STEPS = 60


class TemplateError(ValueError):
    pass


# ------------------------------------------------------------------ expressions
def _check(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        _check(node.body)
    elif isinstance(node, ast.Constant) and type(node.value) is int:
        pass
    elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        _check(node.left)
        _check(node.right)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        _check(node.operand)
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS
          and not node.keywords and node.args):
        for arg in node.args:
            _check(arg)
    else:
        raise TemplateError(f"unsupported expression element: {ast.dump(node)[:60]}")


def _eval(node: ast.AST) -> int:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp):
        return -_eval(node.operand)
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left), _eval(node.right)
        return a + b if isinstance(node.op, ast.Add) else a - b if isinstance(node.op, ast.Sub) else a * b
    return _FUNCS[node.func.id](*(_eval(a) for a in node.args))


def param_names(value: Any) -> set[str]:
    return set(_PARAM.findall(value)) if isinstance(value, str) else set()


def evaluate(value: Any, params: Mapping[str, Any]) -> int:
    """int → itself; '{x} + 3' → integer. Missing or non-integer parameters raise TemplateError."""
    if type(value) is int:
        return value
    if not isinstance(value, str):
        raise TemplateError(f"day value must be an integer or expression, got {value!r}")

    def sub(m: re.Match) -> str:
        v = params.get(m.group(1))
        if type(v) is not int:
            raise TemplateError(f"parameter {m.group(1)} must be an integer, got {v!r}")
        return f"({v})"
    tree = ast.parse(_PARAM.sub(sub, value), mode="eval")
    _check(tree)
    return _eval(tree)


# ------------------------------------------------------------------ definitions
@dataclass(frozen=True)
class StepDef:
    kind: str
    day: Any
    purpose: str | None = None
    category: str | None = None
    end: Any = None
    window_days: Any = None
    accept_early: bool = False
    recall_on_miss: bool = False
    completes: bool = False
    when: Any = None
    repeat: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Template:
    code: str
    title: str
    enabled: bool
    params: Mapping[str, Any]
    steps: tuple[StepDef, ...]
    call_rules: Mapping[str, Any]
    continue_on_success: bool = False

    def refused_rule(self) -> Mapping[str, int] | None:
        """None → «refused» closes the journey (G5); else {'retry_days', 'max'} (ear_wax_norx)."""
        rule = self.call_rules.get("refused", "close")
        return None if rule == "close" else rule


_STEP_KEYS = {"kind", "day", "purpose", "category", "end", "window_days", "accept_early", "recall_on_miss",
              "completes", "when", "repeat"}


def parse_template(data: Mapping[str, Any]) -> Template:
    try:
        code, title = data["code"], data["title"]
        raw_steps = data["steps"]
    except (KeyError, TypeError) as exc:
        raise TemplateError(f"template is missing {exc}") from None
    if not re.fullmatch(r"[a-z_]{2,40}", str(code)):
        raise TemplateError(f"bad template code {code!r}")
    steps = []
    for i, raw in enumerate(raw_steps):
        unknown = set(raw) - _STEP_KEYS
        if unknown:
            raise TemplateError(f"{code} step {i}: unknown keys {sorted(unknown)}")
        s = StepDef(**{k: raw[k] for k in raw})
        if s.kind == "call":
            if not s.purpose or s.category or s.end is not None or s.window_days is not None:
                raise TemplateError(f"{code} step {i}: a call needs a purpose and no window")
        elif s.kind == "expect":
            if s.category not in CATEGORIES:
                raise TemplateError(f"{code} step {i}: unknown category {s.category!r}")
            if (s.end is None) == (s.window_days is None):
                raise TemplateError(f"{code} step {i}: give exactly one of end / window_days")
        else:
            raise TemplateError(f"{code} step {i}: unknown kind {s.kind!r}")
        for value in (s.day, s.end, s.window_days, s.when, *(s.repeat or {}).values()):
            if value is not None and type(value) is not int:
                if not isinstance(value, str):
                    raise TemplateError(f"{code} step {i}: bad value {value!r}")
                _check(ast.parse(_PARAM.sub("(0)", value), mode="eval"))
        steps.append(s)
    if not any(s.kind == "expect" for s in steps):
        raise TemplateError(f"{code}: a template needs at least one expect step")
    return Template(code, title, bool(data.get("enabled", True)), dict(data.get("params", {})), tuple(steps),
                    dict(data.get("call_rules", {})), bool(data.get("continue_on_success", False)))


# ------------------------------------------------------------------ instantiation
@dataclass(frozen=True)
class PlannedStep:
    seq: int
    kind: str
    due_date: date
    window_end: date | None
    category: str | None
    purpose: str
    accept_early: bool
    recall_on_miss: bool
    completes: bool


def merged_params(t: Template, given: Mapping[str, Any]) -> dict[str, Any]:
    params = {**t.params, **{k: v for k, v in given.items() if v is not None}}
    needed = set()
    for s in t.steps:
        for value in (s.day, s.end, s.window_days, s.when, *(s.repeat or {}).values()):
            needed |= param_names(value)
    missing = sorted(n for n in needed if params.get(n) is None)
    if missing:
        raise TemplateError(f"{t.code}: missing parameters {missing}")
    return params


def plan(t: Template, given: Mapping[str, Any], start: date) -> list[PlannedStep]:
    """Concrete steps in due order. Days before 1 are clamped to 1 (nothing is due on day 0)."""
    params = merged_params(t, given)
    out: list[tuple[int, int, int | None, StepDef]] = []        # (day, def index, end_day, def)
    for idx, s in enumerate(t.steps):
        if s.when is not None and evaluate(s.when, params) <= 0:
            continue
        first = evaluate(s.day, params)
        days = [first]
        if s.repeat:
            every = evaluate(s.repeat["every_days"], params)
            if every <= 0:
                raise TemplateError(f"{t.code}: repeat every_days must be positive")
            if "count" in s.repeat:
                count = evaluate(s.repeat["count"], params)
                if not 1 <= count <= MAX_STEPS:
                    raise TemplateError(f"{t.code}: repeat count out of range: {count}")
                days = [first + every * k for k in range(count)]
            else:
                before = evaluate(s.repeat["before_day"], params)
                days = list(range(first, before, every))
        for day in days:
            day = max(1, day)
            end = None
            if s.kind == "expect":
                end = evaluate(s.end, params) if s.end is not None else day + evaluate(s.window_days, params)
                if end < day:
                    raise TemplateError(f"{t.code}: window ends before it starts (day {day}, end {end})")
            out.append((day, idx, end, s))
    if len(out) > MAX_STEPS:
        raise TemplateError(f"{t.code}: too many steps ({len(out)})")
    out.sort(key=lambda x: (x[0], x[1]))
    return [PlannedStep(seq, s.kind, start + timedelta(days=day),
                        None if end is None else start + timedelta(days=end),
                        s.category, s.purpose or f"expect_{s.category}", s.accept_early, s.recall_on_miss,
                        s.completes)
            for seq, (day, _idx, end, s) in enumerate(out, start=1)]


@dataclass
class TemplateSet:
    by_code: dict[str, Template] = field(default_factory=dict)

    def get(self, code: str) -> Template:
        try:
            return self.by_code[code]
        except KeyError:
            raise TemplateError(f"unknown template {code!r}") from None

import ast
from typing import List, Tuple, Optional

# Scene base classes recognised by Manim CE.
_SCENE_BASES = {
    "Scene", "MovingCameraScene", "ThreeDScene", "ZoomedScene",
    "VectorScene", "LinearTransformationScene", "ReconfigurableScene",
    "SpecialThreeDScene",
}

# Modules/builtins whose presence in generated code is a security violation.
FORBIDDEN_MODULES = {
    "os", "subprocess", "socket", "sys", "importlib", "shutil",
    "pathlib", "ctypes", "multiprocessing", "threading", "pty",
    "signal", "resource", "fcntl", "tempfile", "http", "urllib",
    "ftplib", "smtplib", "telnetlib", "xmlrpc",
}
FORBIDDEN_BUILTINS = {
    "eval", "exec", "compile", "__import__", "open", "breakpoint",
    "memoryview", "vars", "globals", "locals", "getattr", "setattr",
    "delattr",
}


def check_manim_security(code: str) -> List[str]:
    """Return a list of security violations found in generated Manim code.

    Call this BEFORE sanitize_manim_code and before writing to disk.
    An empty list means the code is safe to proceed.
    """
    violations: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return violations  # SyntaxError caught elsewhere

    class SecurityChecker(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    violations.append(f"Forbidden module import: {alias.name}")
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    violations.append(f"Forbidden from-import: {node.module}")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTINS:
                violations.append(f"Forbidden builtin call: {node.func.id}()")
            # Also catch attribute-style: builtins.eval(...)
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in FORBIDDEN_BUILTINS):
                violations.append(f"Forbidden builtin call via attribute: {node.func.attr}()")
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute):
            # Catch os.system, subprocess.run, etc. accessed as attributes
            if isinstance(node.value, ast.Name) and node.value.id in FORBIDDEN_MODULES:
                violations.append(f"Forbidden module attribute access: {node.value.id}.{node.attr}")
            self.generic_visit(node)

    SecurityChecker().visit(tree)
    return violations


def sanitize_manim_code(code: str, scene_id: Optional[int] = None) -> Tuple[str, List[str]]:
    """Perform conservative AST-based sanitization of LLM-generated Manim CE code.

    The sanitizer rewrites a small set of known deprecated identifiers to safe
    alternatives, normalizes legacy imports (manimlib -> manim), and renames the
    primary class to `Scene{scene_id}` when `scene_id` is provided. It returns
    the sanitized source and a list of human-readable warnings describing the
    changes performed.

    This function deliberately keeps transformations conservative to avoid
    changing program logic in risky ways.
    """
    warnings: List[str] = []

    # Quick fallback: if empty code, return as-is
    if not code:
        return code, warnings

    try:
        tree = ast.parse(code)
    except Exception as e:
        warnings.append(f"AST parse failed: {e}")
        return code, warnings

    # Pre-scan: find the primary scene class so we rename only that one.
    # Prefer the first class that explicitly inherits from a known Scene base;
    # fall back to the first class in the file.
    primary_class_name: Optional[str] = None
    if scene_id is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                base_names = {
                    b.id if isinstance(b, ast.Name) else
                    (b.attr if isinstance(b, ast.Attribute) else "")
                    for b in node.bases
                }
                if base_names & _SCENE_BASES:
                    primary_class_name = node.name
                    break
        if primary_class_name is None:
            # No explicit Scene subclass — rename first class in the file.
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    primary_class_name = node.name
                    break

    # Conservative replacements mapping
    name_map = {
        "ShowCreation": "Create",
        "ShowCreationThenFadeOut": "Create",
        "SVGMobject": "Circle",
        "SVGCircle": "Circle",
        "VGraph": "VGroup",
        "there_and_back_once": "there_and_back",
    }

    color_map = {
        "DARK_RED": "#8B0000",
        "DARK_BLUE": "#00008B",
        "DARK_GREEN": "#006400",
        "LIGHT_GRAY": "GRAY_A",
        "DARK_GRAY": "GRAY_E",
    }

    # Manim CE 0.20 rate_functions members. The LLM reliably emits bare easing
    # names (`rate_func=ease_out_sine`) which are a NameError under
    # `from manim import *` — only `rate_functions.<name>` resolves. Observed
    # to survive error-feedback retries (the model re-emits the same bare
    # name), so it must be fixed deterministically here.
    _RATE_FUNCTIONS = {
        "linear", "smooth", "smoothstep", "smootherstep", "smoothererstep",
        "rush_into", "rush_from", "slow_into", "double_smooth",
        "there_and_back", "there_and_back_with_pause", "running_start",
        "not_quite_there", "wiggle", "lingering", "exponential_decay",
        "unit_interval", "zero",
    } | {
        f"ease_{phase}_{shape}"
        for phase in ("in", "out", "in_out")
        for shape in ("sine", "quad", "cubic", "quart", "quint",
                      "expo", "circ", "back", "elastic", "bounce")
    }

    def _is_bg_assign_target(t: ast.expr) -> bool:
        """Match `config.background_color` and `*.camera.background_color`."""
        if not (isinstance(t, ast.Attribute) and t.attr == "background_color"):
            return False
        v = t.value
        if isinstance(v, ast.Name) and v.id == "config":
            return True
        if isinstance(v, ast.Attribute) and v.attr == "camera":
            return True
        return False

    class Sanitizer(ast.NodeTransformer):
        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
            # Normalize legacy manim imports
            if node.module and ("manimlib" in node.module or "manimgl" in node.module):
                old = node.module
                node.module = "manim"
                warnings.append(f"Rewrote import: from {old} -> from manim")
            return self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            # rate_functions.ease_out -> rate_functions.ease_out_sine
            if isinstance(node.value, ast.Name):
                key = f"{node.value.id}.{node.attr}"
                if key == "rate_functions.ease_out":
                    node.attr = "ease_out_sine"
                    warnings.append("Rewrote rate_functions.ease_out -> rate_functions.ease_out_sine")
                # config.background does not exist in Manim CE; the render
                # fails with AttributeError. Works for both read and assign.
                if key == "config.background":
                    node.attr = "background_color"
                    warnings.append("Rewrote config.background -> config.background_color")
            return self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> ast.AST:
            # Replace known deprecated names with safer alternatives
            if node.id in name_map:
                new = name_map[node.id]
                warnings.append(f"Replaced identifier: {node.id} -> {new}")
                return ast.copy_location(ast.Name(id=new, ctx=node.ctx), node)

            if node.id in color_map:
                val = color_map[node.id]
                if isinstance(val, str) and val.startswith("#"):
                    warnings.append(f"Replaced color constant {node.id} -> '{val}'")
                    return ast.copy_location(ast.Constant(value=val), node)
                else:
                    warnings.append(f"Replaced color constant {node.id} -> {val}")
                    return ast.copy_location(ast.Name(id=val, ctx=node.ctx), node)

            return node

        def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
            # Only rename the primary scene class; leave helper classes untouched.
            if scene_id is not None and node.name == primary_class_name:
                desired = f"Scene{scene_id}"
                if node.name != desired:
                    warnings.append(f"Renamed class {node.name} -> {desired}")
                    node.name = desired
            return self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign) -> ast.AST:
            # The LLM reliably writes `config.background_color = WHITE` as the
            # first line of construct(). The camera is initialized before
            # construct() runs, so the assignment has ZERO effect and the video
            # renders on Manim's default black — while also tricking the
            # injection pass below into thinking a background was set. Strip
            # every background assignment; the module-level injection below is
            # the single source of truth.
            if any(_is_bg_assign_target(t) for t in node.targets):
                warnings.append(
                    "Removed background_color assignment (pipeline owns the background)")
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> ast.AST:
            self.generic_visit(node)
            kept = []
            for kw in node.keywords:
                if (kw.arg == "rate_func" and isinstance(kw.value, ast.Name)):
                    name = kw.value.id
                    if name in _RATE_FUNCTIONS:
                        kw.value = ast.copy_location(ast.Attribute(
                            value=ast.Name(id="rate_functions", ctx=ast.Load()),
                            attr=name, ctx=ast.Load()), kw.value)
                        warnings.append(
                            f"Qualified rate_func: {name} -> rate_functions.{name}")
                    else:
                        warnings.append(
                            f"Dropped unknown rate_func={name} (would NameError)")
                        continue
                kept.append(kw)
            node.keywords = kept
            return node

    try:
        transformer = Sanitizer()
        new_tree = transformer.visit(tree)

        # Pipeline contract: scenes render on a WHITE canvas, set at MODULE
        # level — config.background_color is read when the camera initializes,
        # before construct() runs, so only a module-level assignment works.
        # All LLM-written background assignments were stripped above, so this
        # injection is unconditional and the single source of truth.
        if isinstance(new_tree, ast.Module):
            insert_at = 0
            for i, stmt in enumerate(new_tree.body):
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    insert_at = i + 1
            bg_assign = ast.Assign(
                targets=[ast.Attribute(value=ast.Name(id="config", ctx=ast.Load()),
                                       attr="background_color", ctx=ast.Store())],
                value=ast.Name(id="WHITE", ctx=ast.Load()),
            )
            new_tree.body.insert(insert_at, bg_assign)
            warnings.append("Injected module-level config.background_color = WHITE (pipeline contract)")

        ast.fix_missing_locations(new_tree)
        try:
            new_code = ast.unparse(new_tree)
        except Exception:
            # ast.unparse may not always be available; fallback to original code
            warnings.append("ast.unparse unavailable; returning original code")
            return code, warnings

        return new_code, warnings

    except Exception as e:
        warnings.append(f"Sanitizer transformer error: {e}")
        return code, warnings

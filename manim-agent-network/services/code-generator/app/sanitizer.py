import ast
from typing import List, Tuple, Optional


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
        # If parsing fails, return original code and report parse error as a warning
        warnings.append(f"AST parse failed: {e}")
        return code, warnings

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
        "LIGHT_GRAY": "GRAY_A",
        "DARK_GRAY": "GRAY_E",
    }

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
            if scene_id is not None:
                desired = f"Scene{scene_id}"
                if node.name != desired:
                    warnings.append(f"Renamed class {node.name} -> {desired}")
                    node.name = desired
            return self.generic_visit(node)

    try:
        transformer = Sanitizer()
        new_tree = transformer.visit(tree)
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

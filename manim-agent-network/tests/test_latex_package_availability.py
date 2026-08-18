"""
Property-based tests for LaTeX package availability in Manim rendering.

Task 1.1: Test LaTeX package availability

This test verifies that Manim scenes with Tex/MathTex objects render successfully
without "standalone.cls not found" errors.

Property: For all scenes with Tex/MathTex, `manim render` should succeed without
LaTeX package errors.

EXPECTED OUTCOME: Test FAILS with LaTeX package errors on UNFIXED code
(confirms bug exists).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
import requests
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
import sys

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import settings as config_settings


# ---------------------------------------------------------------------------
# Test strategies - Tex/MathTex strings that require LaTeX packages
# ---------------------------------------------------------------------------

def tex_string_strategy():
    """Generate various Tex/MathTex strings that require LaTeX packages."""
    return st.one_of(
        # Basic text in math mode
        st.builds(
            lambda x: f"MathTex(r'{x}')",
            st.sampled_from([
                r"\text{Hello World}",
                r"\text{Transformer Architecture}",
                r"\text{Masked Self-Attention}",
                r"\text{Feed Forward Network}",
                r"\text{Layer Normalization}",
                r"\text{Positional Encoding}",
                r"\text{Attention Scores}",
                r"\text{Query Key Value}",
            ])
        ),
        # Fractions and math expressions
        st.builds(
            lambda x: f"MathTex(r'{x}')",
            st.sampled_from([
                r"\frac{a}{b}",
                r"\frac{1}{2}",
                r"\sqrt{x}",
                r"\sqrt{x^2 + y^2}",
                r"\sum_{i=1}^{n} x_i",
                r"\int_{0}^{1} f(x) dx",
            ])
        ),
        # Greek letters
        st.builds(
            lambda x: f"MathTex(r'{x}')",
            st.sampled_from([
                r"\alpha + \beta = \gamma",
                r"\delta = \epsilon + \zeta",
                r"\theta \in [0, \pi]",
                r"\lambda = \frac{1}{\sigma\sqrt{2\pi}}",
            ])
        ),
        # Matrices
        st.builds(
            lambda x: f"MathTex(r'{x}')",
            st.sampled_from([
                r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
                r"\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}",
            ])
        ),
        # Tex with text command
        st.builds(
            lambda x: f"Tex(r'{x}')",
            st.sampled_from([
                r"\text{This is a test}",
                r"\text{Manim renders LaTeX}",
                r"\text{Standalone package test}",
            ])
        ),
    )


def manim_scene_strategy():
    """Generate Manim scene code with Tex/MathTex objects."""
    return st.builds(
        lambda tex_obj: f"""from manim import *

class Scene1(Scene):
    def construct(self):
        {tex_obj}
        self.wait()
""",
        tex_string_strategy()
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def render_manim_in_validator_container(code: str, container_name: str = "manim-agent-network-validator-1") -> tuple[int, str, str]:
    """
    Render Manim code inside the validator Docker container.
    
    Args:
        code: Manim Python code to render
        container_name: Name of the validator container
        
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    # Create a temporary directory for the test
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write the Manim code to a file
        code_path = Path(tmpdir) / "test_scene.py"
        code_path.write_text(code)
        
        # Copy the file to the container's workspace
        subprocess.run(
            ["docker", "cp", str(code_path), f"{container_name}:/workspace/temp/test_scene.py"],
            check=True,
            capture_output=True
        )
        
        # Run manim render in the container
        cmd = [
            "docker", "exec", "-w", "/workspace",
            container_name,
            "manim", "render", "-ql",
            "--media_dir", "/workspace/temp/test_latex_output",
            "/workspace/temp/test_scene.py",
            "Scene1"
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout after 120 seconds"
        except Exception as e:
            return -1, "", str(e)


def render_manim_via_validator_api(code: str, code_path: str) -> dict:
    """
    Render Manim code via the validator service API.
    
    Args:
        code: Manim Python code to render
        code_path: Path where the code file is stored
        
    Returns:
        Dict with success, render_path, and error_log keys
    """
    # Write the code file to the shared workspace
    Path(code_path).write_text(code)
    
    # Call the validator API
    validator_url = "http://localhost:8003/validate"
    payload = {
        "job_id": "test-latex-job",
        "scene_id": 1,
        "code_path": code_path
    }
    
    try:
        response = requests.post(validator_url, json=payload, timeout=180)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {
            "success": False,
            "error_log": str(e)
        }


def check_latex_error(stderr: str, stdout: str) -> tuple[bool, str]:
    """
    Check if the output contains LaTeX package errors.
    
    Returns:
        (has_error, error_message)
    """
    combined = stderr + stdout
    
    # Check for standalone.cls not found
    if "standalone.cls" in combined or "File 'standalone' not found" in combined:
        return True, "LaTeX standalone.cls package not found"
    
    # Check for other common LaTeX package errors
    if "LaTeX Error:" in combined and "not found" in combined:
        return True, f"LaTeX package error: {combined}"
    
    return False, ""


# ---------------------------------------------------------------------------
# Property-based tests - These run against the validator container
# ---------------------------------------------------------------------------

def test_latex_standalone_package_specific():
    """
    Specific test for standalone.cls package availability.
    
    This test specifically targets the standalone.cls package issue
    that is mentioned in the bug description.
    
    EXPECTED ON UNFIXED CODE: FAIL with "LaTeX Error: File `standalone.cls' not found"
    EXPECTED ON FIXED CODE: PASS
    """
    # Code that specifically requires standalone.cls
    scene_code = """from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"\\text{Transformer Architecture}")
        self.add(formula)
        self.wait()
"""
    
    # Render in the validator container
    returncode, stdout, stderr = render_manim_in_validator_container(scene_code)
    
    # Check for LaTeX package errors
    has_error, error_msg = check_latex_error(stderr, stdout)
    
    print(f"\n=== Standalone Package Test ===")
    print(f"Return code: {returncode}")
    print(f"Has LaTeX error: {has_error}")
    print(f"Error message: {error_msg}")
    print(f"STDERR (first 1000 chars): {stderr[:1000]}")
    
    # This should fail on unfixed code with "standalone.cls not found"
    # On fixed code, this should pass
    assert not has_error, f"LaTeX package error detected: {error_msg}"
    assert returncode == 0, f"Manim render failed with return code {returncode}. STDERR: {stderr[:500]}"


def test_latex_math_frac():
    """
    Test MathTex with fraction expression.
    
    EXPECTED ON UNFIXED CODE: FAIL
    EXPECTED ON FIXED CODE: PASS
    """
    scene_code = """from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"\\frac{1}{2}")
        self.add(formula)
        self.wait()
"""
    
    returncode, stdout, stderr = render_manim_in_validator_container(scene_code)
    has_error, error_msg = check_latex_error(stderr, stdout)
    
    print(f"\n=== Fraction Test ===")
    print(f"Return code: {returncode}")
    print(f"Has LaTeX error: {has_error}")
    
    assert not has_error, f"LaTeX package error: {error_msg}"
    assert returncode == 0, f"Manim render failed: {stderr[:500]}"


def test_latex_equation():
    """
    Test MathTex with equation.
    
    EXPECTED ON UNFIXED CODE: FAIL
    EXPECTED ON FIXED CODE: PASS
    """
    scene_code = """from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"x^2 + y^2 = z^2")
        self.add(formula)
        self.wait()
"""
    
    returncode, stdout, stderr = render_manim_in_validator_container(scene_code)
    has_error, error_msg = check_latex_error(stderr, stdout)
    
    print(f"\n=== Equation Test ===")
    print(f"Return code: {returncode}")
    print(f"Has LaTeX error: {has_error}")
    
    assert not has_error, f"LaTeX package error: {error_msg}"
    assert returncode == 0, f"Manim render failed: {stderr[:500]}"


def test_latex_greek_letters():
    """
    Test MathTex with Greek letters.
    
    EXPECTED ON UNFIXED CODE: FAIL
    EXPECTED ON FIXED CODE: PASS
    """
    scene_code = """from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"\\alpha + \\beta = \\gamma")
        self.add(formula)
        self.wait()
"""
    
    returncode, stdout, stderr = render_manim_in_validator_container(scene_code)
    has_error, error_msg = check_latex_error(stderr, stdout)
    
    print(f"\n=== Greek Letters Test ===")
    print(f"Return code: {returncode}")
    print(f"Has LaTeX error: {has_error}")
    
    assert not has_error, f"LaTeX package error: {error_msg}"
    assert returncode == 0, f"Manim render failed: {stderr[:500]}"


def test_latex_tex_text():
    """
    Test Tex with text command.
    
    EXPECTED ON UNFIXED CODE: FAIL
    EXPECTED ON FIXED CODE: PASS
    """
    scene_code = """from manim import *

class Scene1(Scene):
    def construct(self):
        text = Tex(r"\\text{Manim renders LaTeX}")
        self.add(text)
        self.wait()
"""
    
    returncode, stdout, stderr = render_manim_in_validator_container(scene_code)
    has_error, error_msg = check_latex_error(stderr, stdout)
    
    print(f"\n=== Tex Text Test ===")
    print(f"Return code: {returncode}")
    print(f"Has LaTeX error: {has_error}")
    
    assert not has_error, f"LaTeX package error: {error_msg}"
    assert returncode == 0, f"Manim render failed: {stderr[:500]}"


# ---------------------------------------------------------------------------
# Counterexample documentation
# ---------------------------------------------------------------------------

def test_document_counterexamples():
    """
    Document specific Tex strings that fail to compile.
    
    This test runs several known problematic cases and documents
    which ones fail.
    
    EXPECTED ON UNFIXED CODE: FAIL (documents the failures)
    EXPECTED ON FIXED CODE: PASS (no failures to document)
    """
    test_cases = [
        (r"MathTex(r'\text{Hello World}')", "Basic text command"),
        (r"MathTex(r'\text{Transformer Architecture}')", "Text with spaces"),
        (r"MathTex(r'\frac{1}{2}')", "Fraction"),
        (r"MathTex(r'\alpha + \beta = \gamma')", "Greek letters"),
        (r"Tex(r'\text{Standalone test}')", "Tex with text"),
    ]
    
    results = []
    
    for tex_expr, description in test_cases:
        scene_code = f"""from manim import *

class Scene1(Scene):
    def construct(self):
        {tex_expr}
        self.wait()
"""
        
        returncode, stdout, stderr = render_manim_in_validator_container(scene_code)
        has_error, error_msg = check_latex_error(stderr, stdout)
        
        results.append({
            "description": description,
            "tex_expr": tex_expr,
            "returncode": returncode,
            "has_error": has_error,
            "error_msg": error_msg,
        })
        
        print(f"\n=== {description} ===")
        print(f"Expression: {tex_expr}")
        print(f"Return code: {returncode}")
        print(f"Has error: {has_error}")
        if has_error:
            print(f"Error: {error_msg}")
    
    # Document which cases failed
    failed_cases = [r for r in results if r["has_error"]]
    
    print(f"\n=== Summary ===")
    print(f"Total cases: {len(results)}")
    print(f"Failed cases: {len(failed_cases)}")
    
    if failed_cases:
        print("\nFailed cases:")
        for fc in failed_cases:
            print(f"  - {fc['description']}: {fc['error_msg']}")
    
    # This test documents the failures - it will fail on unfixed code
    # but that's expected to demonstrate the bug
    if failed_cases:
        pytest.fail(f"{len(failed_cases)} out of {len(results)} cases failed with LaTeX errors. "
                   f"This confirms the bug exists: standalone.cls is not installed in the validator container.")


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v", "-s"])
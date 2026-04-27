# Bugfix Requirements Document

## Introduction

The Manim Agent Network video generation system is experiencing rendering failures in scenes 1, 3, and 4 due to three distinct categories of errors: LaTeX package dependencies, Manim API syntax errors, and Python string escape sequence issues. These failures prevent the code generator service from producing valid Manim code, causing the validator service to reject scenes even after multiple retry attempts. This bugfix addresses all three error categories to ensure consistent scene rendering across the pipeline.

## Bug Analysis

### Current Behavior (Defect)

**LaTeX Compilation Errors:**

1.1 WHEN the code generator produces Tex() or MathTex() objects in scenes 3 and 4 THEN the validator fails with "LaTeX Error: File `standalone.cls' not found"

**Manim API Syntax Errors:**

1.2 WHEN the code generator produces code using `CYAN` constant in scene 1 (line 29) THEN the validator fails with "NameError: name 'CYAN' is not defined"

1.3 WHEN the code generator produces Rectangle initialization with duplicate `color` parameter in scene 3 (line 11) THEN the validator fails with "TypeError: Rectangle.__init__() got multiple values for argument 'color'"

**Python String Escape Sequence Errors:**

1.4 WHEN the code generator produces Tex strings with single backslashes like `"Masked\\Self-Attn"` in scene 3 THEN the validator fails with invalid escape sequence warnings or errors

**Retry Mechanism Failures:**

1.5 WHEN scenes 3 and 4 fail validation THEN the retry mechanism (up to 3 attempts) does not successfully recover and all attempts fail

**Pipeline Execution Performance:**

1.6 WHEN the pipeline processes multiple scenes THEN the code-generator and validator services process scenes strictly sequentially, causing unnecessary delays when scenes could be processed independently

### Expected Behavior (Correct)

**LaTeX Compilation:**

2.1 WHEN the code generator produces Tex() or MathTex() objects THEN the validator SHALL successfully compile LaTeX without missing package errors

**Manim API Syntax:**

2.2 WHEN the code generator produces code using color constants THEN the validator SHALL successfully execute with properly imported Manim color names (e.g., using `BLUE` instead of `CYAN`, or importing from `manim.constants`)

2.3 WHEN the code generator produces Rectangle initialization THEN the validator SHALL successfully execute without duplicate parameter errors

**Python String Escaping:**

2.4 WHEN the code generator produces Tex strings with special characters THEN the validator SHALL successfully parse strings with proper escape sequences (e.g., raw strings `r"Masked\Self-Attn"` or double backslashes `"Masked\\\\Self-Attn"`)

**Retry Mechanism:**

2.5 WHEN a scene fails validation with correctable errors THEN the retry mechanism SHALL provide sufficient error context to the code generator to produce valid code within 3 attempts

**Pipeline Execution Performance:**

2.6 WHEN the pipeline processes multiple scenes THEN the system SHALL support configurable execution modes:
- **Serial mode**: Process scenes one at a time (current behavior, useful for debugging)
- **Parallel mode**: Process independent scenes concurrently (faster execution, better resource utilization)

2.7 WHEN parallel mode is enabled THEN the system SHALL process code generation and validation for multiple scenes concurrently while maintaining proper error handling and retry logic for each scene

### Unchanged Behavior (Regression Prevention)

**Successful Scene Rendering:**

3.1 WHEN scenes 2 and 5 are rendered THEN the system SHALL CONTINUE TO successfully generate and validate these scenes without errors

**Multi-Service Architecture:**

3.2 WHEN the orchestrator coordinates between services (script-writer, code-generator, validator, voiceover, assembler) THEN the system SHALL CONTINUE TO maintain proper service communication and state management

**Error Feedback Loop:**

3.3 WHEN the validator detects errors in generated code THEN the system SHALL CONTINUE TO capture stderr and feed error messages back to the code generator for retry attempts

**Docker Container Execution:**

3.4 WHEN Manim rendering occurs in the validator service container THEN the system SHALL CONTINUE TO execute `manim render` commands within the containerized environment

**LLM Code Generation:**

3.5 WHEN the code generator service uses the LLM (moonshotai/kimi-k2-instruct) to generate Manim code THEN the system SHALL CONTINUE TO produce syntactically valid Python code structure (imports, class definitions, construct methods)

**Pipeline Execution Consistency:**

3.6 WHEN the execution mode is changed THEN the system SHALL CONTINUE TO produce the same final output (successful scenes rendered, failed scenes reported) regardless of whether serial or parallel mode is used

# Manim Rendering Errors Fix - Bugfix Design

## Overview

This bugfix addresses three categories of rendering failures in the Manim Agent Network that prevent scenes 1, 3, and 4 from rendering successfully. The failures stem from: (1) missing LaTeX packages in the Docker container, (2) incorrect Manim API syntax in LLM-generated code, and (3) invalid Python string escape sequences in Tex objects. Additionally, we introduce configurable pipeline execution modes (serial vs parallel) to improve performance when processing multiple scenes. The fix strategy involves enhancing the code generator's prompt engineering to prevent syntax errors, installing missing LaTeX dependencies in the validator container, and implementing parallel processing capabilities in the orchestrator.

## Glossary

- **Bug_Condition (C)**: The condition that triggers rendering failures - when the code generator produces code with LaTeX package dependencies, invalid Manim API syntax, or improper string escaping
- **Property (P)**: The desired behavior - all generated Manim code should render successfully without LaTeX, syntax, or escape sequence errors
- **Preservation**: Existing successful rendering behavior for scenes 2 and 5, multi-service architecture, error feedback loop, and Docker execution environment must remain unchanged
- **Code Generator Service**: The service in `services/code-generator/app/main.py` that uses an LLM to generate Manim Python code from scene descriptions
- **Validator Service**: The service in `services/validator/app/main.py` that executes `manim render` commands and captures stderr for error feedback
- **Orchestrator Service**: The service in `services/orchestrator/app/core/graph.py` that coordinates the LangGraph workflow between all services
- **LaTeX Compilation**: The process by which Manim's Tex() and MathTex() objects compile LaTeX strings into rendered text using the system's LaTeX installation
- **Manim CE**: Manim Community Edition - the open-source mathematical animation library used for rendering
- **CYAN Constant**: An undefined color constant in Manim CE (the correct constant is BLUE or colors must be imported from manim.constants)
- **Execution Mode**: The pipeline processing strategy - serial (sequential scene processing) or parallel (concurrent scene processing)

## Bug Details

### Bug Condition

The bug manifests when the code generator produces Manim code that contains any of three error patterns: (1) Tex/MathTex objects that require the `standalone.cls` LaTeX package not installed in the validator container, (2) references to undefined Manim constants like `CYAN` or duplicate parameter assignments like `color=X, color=Y`, or (3) Python strings with invalid escape sequences like `"Masked\\Self-Attn"` instead of raw strings or properly escaped sequences. The validator service executes `manim render` which fails with compilation or runtime errors, and the retry mechanism (up to 3 attempts) does not successfully recover because the code generator continues producing similar errors.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type GeneratedManimCode
  OUTPUT: boolean
  
  RETURN (containsTexOrMathTex(input.code) AND requiresStandalonePackage(input.code))
         OR (containsUndefinedConstant(input.code, "CYAN"))
         OR (containsDuplicateParameter(input.code, "color"))
         OR (containsInvalidEscapeSequence(input.code))
         AND NOT manimRenderSucceeds(input.code)
END FUNCTION

FUNCTION containsTexOrMathTex(code)
  RETURN "Tex(" IN code OR "MathTex(" IN code
END FUNCTION

FUNCTION requiresStandalonePackage(code)
  # LaTeX compilation fails with "File `standalone.cls' not found"
  RETURN texCompilationRequiresPackage(code, "standalone")
END FUNCTION

FUNCTION containsUndefinedConstant(code, constantName)
  RETURN constantName IN code AND NOT isImported(code, constantName)
END FUNCTION

FUNCTION containsDuplicateParameter(code, paramName)
  RETURN hasDuplicateKeywordArg(code, paramName)
END FUNCTION

FUNCTION containsInvalidEscapeSequence(code)
  # Detects single backslash patterns like "\\S" that are not valid Python escapes
  RETURN hasInvalidBackslashPattern(code)
END FUNCTION
```

### Examples

**Example 1: LaTeX Package Error (Scene 3)**
- **Input**: Code generator produces `MathTex(r"\text{Transformer Architecture}")` 
- **Expected**: Validator successfully compiles LaTeX and renders the scene
- **Actual**: Validator fails with `LaTeX Error: File 'standalone.cls' not found`
- **Root Cause**: The validator Docker container is missing the `texlive-latex-extra` package

**Example 2: Undefined Constant Error (Scene 1, line 29)**
- **Input**: Code generator produces `Rectangle(color=CYAN, width=2, height=1)`
- **Expected**: Validator successfully executes the code with a valid color constant
- **Actual**: Validator fails with `NameError: name 'CYAN' is not defined`
- **Root Cause**: CYAN is not a valid Manim CE constant; should use BLUE or import from manim.constants

**Example 3: Duplicate Parameter Error (Scene 3, line 11)**
- **Input**: Code generator produces `Rectangle(color=RED, width=2, height=1, color=BLUE)`
- **Expected**: Validator successfully creates a Rectangle with a single color parameter
- **Actual**: Validator fails with `TypeError: Rectangle.__init__() got multiple values for argument 'color'`
- **Root Cause**: LLM generated duplicate keyword arguments in the same function call

**Example 4: Invalid Escape Sequence (Scene 3)**
- **Input**: Code generator produces `Tex("Masked\\Self-Attn")`
- **Expected**: Validator successfully parses the string with proper escaping
- **Actual**: Python parser warns or fails with `SyntaxWarning: invalid escape sequence '\S'`
- **Root Cause**: Single backslash creates invalid escape sequence; should use raw string `r"Masked\Self-Attn"` or double backslash `"Masked\\\\Self-Attn"`

**Example 5: Retry Mechanism Failure (Scenes 3 and 4)**
- **Input**: Scene fails validation with LaTeX error, retry attempt 1, 2, 3
- **Expected**: Code generator receives error context and produces corrected code within 3 attempts
- **Actual**: All 3 retry attempts fail with similar errors; scene marked as failed
- **Root Cause**: Error feedback is insufficient or LLM prompt does not adequately guide correction

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Scenes 2 and 5 must continue to render successfully without any errors
- Multi-service architecture (orchestrator, script-writer, code-generator, validator, voiceover, assembler) must maintain proper communication and state management
- Error feedback loop where validator captures stderr and feeds error messages back to code generator must continue to function
- Docker container execution environment for Manim rendering must remain unchanged
- LLM code generation must continue to produce syntactically valid Python code structure (imports, class definitions, construct methods)
- Final output quality and video assembly process must remain unchanged

**Scope:**
All inputs that do NOT involve LaTeX compilation, Manim API syntax errors, or Python string escape issues should be completely unaffected by this fix. This includes:
- Scenes that use only basic Manim shapes and animations without text
- Scenes that already use correct Manim API syntax
- Scenes that use proper string escaping (raw strings or double backslashes)
- All other services in the pipeline (script-writer, voiceover, assembler, image-fetcher)
- The LangGraph state machine and workflow routing logic

## Hypothesized Root Cause

Based on the bug description and code analysis, the most likely issues are:

1. **Missing LaTeX Packages in Validator Container**: The validator service Docker image does not include the `texlive-latex-extra` package, which provides `standalone.cls` and other commonly used LaTeX packages. When Manim's Tex/MathTex objects attempt to compile LaTeX, the compilation fails because the required packages are not available in the container environment.

2. **Insufficient Prompt Engineering in Code Generator**: The LLM prompt in `services/code-generator/app/main.py` does not explicitly warn against using undefined constants like CYAN, does not prevent duplicate parameter assignments, and does not enforce proper string escaping for Tex objects. The few-shot examples may not adequately demonstrate these patterns.

3. **Inadequate Error Context in Retry Mechanism**: When the validator returns error logs to the code generator for retry attempts, the error messages may not provide sufficient context for the LLM to understand and correct the specific issues. The retry prompt may not emphasize the specific error patterns strongly enough.

4. **Sequential Processing Bottleneck**: The orchestrator processes scenes strictly sequentially in the code_generator_node and validator_node, even though scenes are independent and could be processed concurrently. This causes unnecessary delays when multiple scenes need generation or validation.

## Correctness Properties

Property 1: Bug Condition - Rendering Success for All Scenes

_For any_ generated Manim code where the scene description requires LaTeX text, Manim API calls, or string literals with special characters, the fixed code generator SHALL produce code that renders successfully without LaTeX package errors, undefined constant errors, duplicate parameter errors, or invalid escape sequence errors.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - Existing Successful Scenes

_For any_ scene that currently renders successfully (scenes 2 and 5), the fixed system SHALL produce exactly the same rendering behavior, preserving all existing functionality for successful scenes.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

Property 3: Retry Mechanism - Error Recovery

_For any_ scene that fails validation with correctable errors (LaTeX, syntax, or escape sequence issues), the fixed retry mechanism SHALL provide sufficient error context to enable the code generator to produce valid code within 3 attempts.

**Validates: Requirements 2.5**

Property 4: Parallel Execution - Performance and Correctness

_For any_ pipeline execution in parallel mode, the fixed orchestrator SHALL process multiple scenes concurrently while producing the same final output (successful scenes rendered, failed scenes reported) as serial mode, with improved execution time.

**Validates: Requirements 2.6, 2.7, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File 1**: `infrastructure/docker/Dockerfile.validator`

**Changes**:
1. **Install LaTeX Packages**: Add `texlive-latex-extra` package to the validator Docker image to provide `standalone.cls` and other commonly used LaTeX packages
   - Add `RUN apt-get update && apt-get install -y texlive-latex-extra && rm -rf /var/lib/apt/lists/*` to the Dockerfile
   - This ensures all LaTeX compilation dependencies are available when Manim renders Tex/MathTex objects

**File 2**: `services/code-generator/app/main.py`

**Function**: `_generate_manim()` - specifically the prompt construction

**Specific Changes**:
1. **Add Color Constant Warning**: Add explicit guidance in the system prompt to use only valid Manim CE color constants
   - Add section: "VALID COLOR CONSTANTS: Use only these colors: RED, BLUE, GREEN, YELLOW, ORANGE, PURPLE, PINK, WHITE, BLACK, GRAY. NEVER use CYAN (not defined in Manim CE)."
   - Emphasize in few-shot examples: Show correct color usage

2. **Add Duplicate Parameter Prevention**: Add explicit rule to prevent duplicate keyword arguments
   - Add section: "NEVER use the same parameter name twice in a function call (e.g., color=RED, color=BLUE is INVALID)"
   - Add validation reminder: "Check that each parameter appears only once"

3. **Add String Escaping Guidance**: Add explicit rules for Tex/MathTex string formatting
   - Add section: "STRING ESCAPING FOR TEX: Always use raw strings for Tex/MathTex: r'\\text{...}' or r'\\frac{...}'. If you cannot use raw strings, double all backslashes: '\\\\text{...}'"
   - Update few-shot examples to consistently use raw strings: `MathTex(r"E = mc^2")`

4. **Enhance Retry Prompt**: Strengthen the error correction guidance in the retry prompt
   - Add specific error pattern matching: "If error contains 'not defined', check imports and constants. If error contains 'multiple values', remove duplicate parameters. If error contains 'invalid escape', use raw strings."
   - Add emphasis: "CRITICAL: Read the error log carefully and fix the EXACT issue mentioned."

5. **Add Validation Checklist**: Add a pre-generation checklist to the prompt
   - "Before generating code, verify: (1) All color constants are valid, (2) No duplicate parameters, (3) All Tex strings use raw strings or double backslashes"

**File 3**: `services/orchestrator/app/core/graph.py`

**Changes**:
1. **Add Execution Mode Configuration**: Add support for serial vs parallel execution modes
   - Add `EXECUTION_MODE` environment variable to `shared/config.py` with values "serial" or "parallel" (default: "serial")
   - Modify `code_generator_node` to support parallel scene processing using `asyncio.gather()` when mode is "parallel"
   - Modify `validator_node` to support parallel scene validation using `asyncio.gather()` when mode is "parallel"

2. **Implement Parallel Code Generation**: Refactor `code_generator_node` to process multiple scenes concurrently
   - Collect all scenes that need generation into a list
   - Use `asyncio.gather()` to call code generator service for all scenes in parallel
   - Maintain proper error handling and retry count tracking for each scene independently

3. **Implement Parallel Validation**: Refactor `validator_node` to validate multiple scenes concurrently
   - Collect all scenes that need validation into a list
   - Use `asyncio.gather()` to call validator service for all scenes in parallel
   - Maintain proper error logging and render path tracking for each scene independently

4. **Preserve Serial Mode**: Ensure serial mode continues to work exactly as before for debugging and compatibility
   - Use conditional logic: `if settings.EXECUTION_MODE == "parallel"` to switch between implementations
   - Default to serial mode to maintain backward compatibility

**File 4**: `shared/config.py`

**Changes**:
1. **Add Execution Mode Setting**: Add new configuration parameter for pipeline execution mode
   - Add: `EXECUTION_MODE: str = os.getenv("EXECUTION_MODE", "serial")`
   - Add validation: Ensure value is either "serial" or "parallel"

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fixes work correctly and preserve existing behavior. We will test each error category independently, then test the integrated system with all fixes applied.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that generate Manim code with each error pattern and attempt to render it using the UNFIXED validator service. Run these tests to observe failures and confirm the root causes.

**Test Cases**:
1. **LaTeX Package Test**: Generate code with `MathTex(r"\text{Test}")` and render in unfixed validator container (will fail with "standalone.cls not found")
2. **Undefined Constant Test**: Generate code with `Rectangle(color=CYAN)` and render (will fail with "NameError: name 'CYAN' is not defined")
3. **Duplicate Parameter Test**: Generate code with `Rectangle(color=RED, width=2, color=BLUE)` and render (will fail with "multiple values for argument 'color'")
4. **Invalid Escape Sequence Test**: Generate code with `Tex("Test\\String")` and render (will fail with "invalid escape sequence")
5. **Retry Mechanism Test**: Trigger a validation failure and observe retry attempts on unfixed code (will fail all 3 attempts)

**Expected Counterexamples**:
- LaTeX compilation fails with missing package errors in validator container
- Python execution fails with NameError for undefined constants
- Python execution fails with TypeError for duplicate parameters
- Python parser fails with SyntaxWarning or SyntaxError for invalid escape sequences
- Retry mechanism does not recover from errors within 3 attempts

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed system produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := generateAndRender_fixed(input)
  ASSERT expectedBehavior(result)
END FOR

FUNCTION expectedBehavior(result)
  RETURN result.renderSuccess == TRUE
         AND result.errorLog == NULL
         AND result.videoFileExists == TRUE
END FUNCTION
```

**Test Cases**:
1. **LaTeX Rendering Test**: Generate code with various Tex/MathTex objects and verify successful rendering with fixed validator
2. **Color Constants Test**: Generate code with all valid Manim color constants and verify no undefined constant errors
3. **Parameter Uniqueness Test**: Generate code with various Manim objects and verify no duplicate parameter errors
4. **String Escaping Test**: Generate code with Tex strings containing backslashes and verify proper escaping
5. **Retry Success Test**: Trigger correctable errors and verify retry mechanism succeeds within 3 attempts
6. **Parallel Execution Test**: Process multiple scenes in parallel mode and verify all scenes render successfully

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed system produces the same result as the original system.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT generateAndRender_original(input) = generateAndRender_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for successful scenes (2 and 5), then write property-based tests capturing that behavior and verify it continues after fix.

**Test Cases**:
1. **Successful Scene Preservation**: Observe that scenes 2 and 5 render successfully on unfixed code, then verify they continue to render identically after fix
2. **Service Communication Preservation**: Observe that all services communicate correctly on unfixed code, then verify communication patterns remain unchanged
3. **Error Feedback Preservation**: Observe that error feedback loop works on unfixed code, then verify it continues to function identically
4. **Docker Execution Preservation**: Observe that Docker container execution works on unfixed code, then verify container behavior remains unchanged
5. **LLM Generation Preservation**: Observe that LLM generates valid Python structure on unfixed code, then verify structure quality remains unchanged
6. **Serial Mode Preservation**: Verify that serial execution mode produces identical results before and after adding parallel mode support

### Unit Tests

- Test LaTeX package installation in validator Docker image (verify `standalone.cls` is available)
- Test code generator prompt includes all new guidance sections (color constants, duplicate parameters, string escaping)
- Test retry prompt includes enhanced error pattern matching
- Test execution mode configuration loads correctly from environment variables
- Test parallel processing logic handles errors independently for each scene
- Test serial mode continues to work with new code changes

### Property-Based Tests

- Generate random scene descriptions and verify all generated code renders successfully (no LaTeX, syntax, or escape errors)
- Generate random Manim object configurations and verify no duplicate parameters are produced
- Generate random Tex strings with special characters and verify proper escaping is applied
- Generate random scene sets and verify parallel mode produces same output as serial mode
- Generate random error scenarios and verify retry mechanism recovers within 3 attempts

### Integration Tests

- Test full pipeline with scenes 1, 3, and 4 (previously failing) and verify all render successfully
- Test full pipeline with all 5 scenes and verify scenes 2 and 5 continue to render successfully
- Test retry mechanism with intentionally broken code and verify recovery
- Test parallel execution mode with multiple scenes and verify correct final output
- Test switching between serial and parallel modes and verify consistent results
- Test Docker container builds successfully with new LaTeX packages
- Test end-to-end video generation with all fixes applied

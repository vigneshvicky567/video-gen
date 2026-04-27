# Implementation Plan

## Overview

This implementation plan addresses three categories of rendering failures in the Manim Agent Network:
1. **LaTeX Compilation Errors** - Missing standalone.cls package
2. **Manim API Syntax Errors** - Undefined CYAN constant, duplicate color parameters
3. **Python String Escape Sequence Errors** - Invalid backslash patterns in Tex strings
4. **Pipeline Performance** - Sequential processing bottleneck

The plan follows the exploratory bugfix workflow: explore the bugs first, write preservation tests, then implement fixes with validation.

---

## Phase 1: Bug Condition Exploration (BEFORE Fix)

- [ ] 1. Write bug condition exploration tests
  - **Property 1: Bug Condition** - Rendering Failures for LaTeX, API Syntax, and Escape Sequences
  - **CRITICAL**: Write these property-based tests BEFORE implementing the fix
  - **GOAL**: Surface counterexamples that demonstrate the bugs exist in the unfixed code
  - **IMPORTANT**: These tests MUST FAIL on unfixed code - failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior - they will validate the fix when they pass after implementation
  
  - [ ] 1.1 Test LaTeX package availability
    - **Scoped PBT Approach**: Test that Manim code with `MathTex(r"\text{...}")` renders successfully
    - Generate Manim scenes with various Tex/MathTex objects requiring LaTeX packages
    - Property: For all scenes with Tex/MathTex, `manim render` should succeed without "standalone.cls not found" errors
    - Run test on UNFIXED validator container
    - **EXPECTED OUTCOME**: Test FAILS with LaTeX package errors (confirms bug exists)
    - Document counterexamples: specific Tex strings that fail to compile
    - _Requirements: 1.1, 2.1_
  
  - [ ] 1.2 Test Manim color constant validity
    - **Scoped PBT Approach**: Test that generated code uses only valid Manim CE color constants
    - Generate Manim scenes with Rectangle/Circle objects using color constants
    - Property: For all generated scenes, no undefined constant errors (e.g., CYAN) should occur
    - Run test on UNFIXED code generator output
    - **EXPECTED OUTCOME**: Test FAILS with "NameError: name 'CYAN' is not defined" (confirms bug exists)
    - Document counterexamples: specific color constants that are undefined
    - _Requirements: 1.2, 2.2_
  
  - [ ] 1.3 Test parameter uniqueness in Manim objects
    - **Scoped PBT Approach**: Test that generated code has no duplicate keyword arguments
    - Generate Manim scenes with various object initializations
    - Property: For all generated scenes, no duplicate parameter errors should occur
    - Run test on UNFIXED code generator output
    - **EXPECTED OUTCOME**: Test FAILS with "TypeError: got multiple values for argument 'color'" (confirms bug exists)
    - Document counterexamples: specific function calls with duplicate parameters
    - _Requirements: 1.3, 2.3_
  
  - [ ] 1.4 Test string escape sequence validity
    - **Scoped PBT Approach**: Test that Tex strings use proper escaping (raw strings or double backslashes)
    - Generate Manim scenes with Tex objects containing special characters
    - Property: For all generated scenes with Tex strings, no invalid escape sequence warnings should occur
    - Run test on UNFIXED code generator output
    - **EXPECTED OUTCOME**: Test FAILS with "SyntaxWarning: invalid escape sequence" (confirms bug exists)
    - Document counterexamples: specific Tex strings with invalid escape sequences
    - _Requirements: 1.4, 2.4_
  
  - [ ] 1.5 Test retry mechanism effectiveness
    - **Scoped PBT Approach**: Test that retry mechanism recovers from correctable errors within 3 attempts
    - Trigger validation failures with correctable errors (LaTeX, syntax, escape issues)
    - Property: For all correctable errors, retry mechanism should succeed within 3 attempts
    - Run test on UNFIXED orchestrator with error feedback loop
    - **EXPECTED OUTCOME**: Test FAILS with all 3 retry attempts failing (confirms bug exists)
    - Document counterexamples: specific error patterns that fail to recover
    - _Requirements: 1.5, 2.5_

---

## Phase 2: Preservation Property Tests (BEFORE Fix)

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Existing Successful Scenes and Architecture
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (scenes 2 and 5)
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  
  - [ ] 2.1 Observe and test successful scene rendering (scenes 2 and 5)
    - **Observation**: Run scenes 2 and 5 on UNFIXED code and record outputs
    - Observe: Scene 2 renders successfully with specific visual elements
    - Observe: Scene 5 renders successfully with specific visual elements
    - Write property-based test: For all scenes that don't trigger bug conditions, rendering succeeds
    - Property: For scenes 2 and 5, `render_paths` should be populated and video files should exist
    - Verify test passes on UNFIXED code
    - _Requirements: 3.1_
  
  - [ ] 2.2 Observe and test multi-service communication
    - **Observation**: Monitor service communication on UNFIXED code
    - Observe: Orchestrator successfully calls script-writer, code-generator, validator, voiceover, assembler
    - Observe: State is properly maintained across service calls
    - Write property-based test: For all pipeline executions, service communication patterns remain unchanged
    - Property: All services respond with expected schemas and status codes
    - Verify test passes on UNFIXED code
    - _Requirements: 3.2_
  
  - [ ] 2.3 Observe and test error feedback loop
    - **Observation**: Trigger validation errors on UNFIXED code and observe feedback
    - Observe: Validator captures stderr and returns error_log to orchestrator
    - Observe: Orchestrator passes error_log and previous_code to code generator for retry
    - Write property-based test: For all validation failures, error feedback loop functions correctly
    - Property: Error logs are captured and passed to code generator with proper structure
    - Verify test passes on UNFIXED code
    - _Requirements: 3.3_
  
  - [ ] 2.4 Observe and test Docker container execution
    - **Observation**: Monitor Docker container behavior on UNFIXED code
    - Observe: Validator executes `manim render` commands within container
    - Observe: Container environment variables and volumes are properly configured
    - Write property-based test: For all render operations, Docker execution environment remains unchanged
    - Property: Manim commands execute in containerized environment with proper isolation
    - Verify test passes on UNFIXED code
    - _Requirements: 3.4_
  
  - [ ] 2.5 Observe and test LLM code generation structure
    - **Observation**: Generate multiple scenes on UNFIXED code and analyze structure
    - Observe: Generated code has proper imports (`from manim import *`)
    - Observe: Generated code has proper class definitions (`class Scene{N}(Scene)`)
    - Observe: Generated code has proper construct methods
    - Write property-based test: For all generated code, Python structure is syntactically valid
    - Property: All generated code passes Python AST parsing and has required Manim structure
    - Verify test passes on UNFIXED code
    - _Requirements: 3.5_

---

## Phase 3: Implementation

- [ ] 3. Fix LaTeX package dependencies in validator container

  - [ ] 3.1 Verify LaTeX packages in base Docker image
    - Check `infrastructure/docker/Dockerfile.base` for LaTeX package installation
    - Verify `texlive-latex-extra` is installed (provides standalone.cls)
    - If missing, add: `RUN apt-get update && apt-get install -y texlive-latex-extra && rm -rf /var/lib/apt/lists/*`
    - **NOTE**: Based on code review, `texlive-latex-extra` is already installed in Dockerfile.base
    - Verify the package list includes: texlive-latex-base, texlive-latex-extra, texlive-pictures, texlive-science
    - _Bug_Condition: isBugCondition(input) where containsTexOrMathTex(input.code) AND requiresStandalonePackage(input.code)_
    - _Expected_Behavior: LaTeX compilation succeeds without missing package errors_
    - _Preservation: Docker container execution environment remains unchanged (3.4)_
    - _Requirements: 1.1, 2.1, 3.4_

  - [ ] 3.2 Rebuild validator Docker image with LaTeX packages
    - Run `make build` to rebuild Docker images with updated Dockerfile
    - Verify validator container starts successfully
    - Test LaTeX compilation in validator container: `docker exec validator-container manim --version`
    - _Requirements: 1.1, 2.1_

  - [ ] 3.3 Verify bug condition exploration test now passes for LaTeX
    - **Property 1: Expected Behavior** - LaTeX Compilation Success
    - **IMPORTANT**: Re-run the SAME test from task 1.1 - do NOT write a new test
    - The test from task 1.1 encodes the expected behavior
    - When this test passes, it confirms LaTeX compilation works correctly
    - Run LaTeX package availability test from step 1.1
    - **EXPECTED OUTCOME**: Test PASSES (confirms LaTeX bug is fixed)
    - _Requirements: 2.1_

- [ ] 4. Fix Manim API syntax errors in code generator

  - [ ] 4.1 Add color constant validation to code generator prompt
    - Open `services/code-generator/app/main.py`
    - Locate the `_generate_manim()` function and the prompt construction
    - Add new section to prompt after "HARD RULES FOR LAYOUT":
      ```
      ============================================================
      MANIM CE API RULES (MANDATORY)
      ============================================================
      1. **VALID COLOR CONSTANTS**: Use only these colors from Manim CE:
         RED, BLUE, GREEN, YELLOW, ORANGE, PURPLE, PINK, WHITE, BLACK, GRAY, TEAL, MAROON, GOLD
         NEVER use CYAN (not defined in Manim CE - use BLUE instead)
      
      2. **NO DUPLICATE PARAMETERS**: Never use the same parameter name twice in a function call
         INVALID: Rectangle(color=RED, width=2, color=BLUE)
         VALID: Rectangle(color=RED, width=2)
      
      3. **STRING ESCAPING FOR TEX**: Always use raw strings for Tex/MathTex objects
         INVALID: Tex("Masked\\Self-Attn")
         VALID: Tex(r"Masked\Self-Attn") or Tex("Masked\\\\Self-Attn")
         All LaTeX strings MUST use r"..." prefix or double backslashes
      ```
    - _Bug_Condition: containsUndefinedConstant(input.code, "CYAN") OR containsDuplicateParameter(input.code, "color") OR containsInvalidEscapeSequence(input.code)_
    - _Expected_Behavior: Generated code uses valid Manim CE constants, no duplicate parameters, proper string escaping_
    - _Preservation: LLM code generation structure remains valid (3.5)_
    - _Requirements: 1.2, 1.3, 1.4, 2.2, 2.3, 2.4, 3.5_

  - [ ] 4.2 Update few-shot examples with correct patterns
    - In the same prompt, update Example 1 to use raw strings:
      ```python
      formula = MathTex(r'y = \\sin(x)', font_size=36)
      ```
    - Update Example 2 to show correct color usage:
      ```python
      circle = Circle(radius=1, color=BLUE)  # Use BLUE, not CYAN
      ```
    - Update Example 3 to use raw strings:
      ```python
      formula = MathTex(r'E = mc^2', font_size=72)
      ```
    - Add comment in examples: "# Always use raw strings (r'...') for LaTeX"
    - _Requirements: 2.2, 2.3, 2.4_

  - [ ] 4.3 Add validation checklist to prompt
    - Add new section before "OUTPUT REQUIREMENTS":
      ```
      ============================================================
      PRE-GENERATION VALIDATION CHECKLIST
      ============================================================
      Before generating code, verify:
      1. All color constants are valid Manim CE colors (no CYAN)
      2. No duplicate parameters in any function call
      3. All Tex/MathTex strings use raw strings (r"...") or double backslashes
      4. All imports are correct: `from manim import *`
      5. Class name matches: `Scene{scene_id}`
      ```
    - _Requirements: 2.2, 2.3, 2.4_

  - [ ] 4.4 Enhance retry prompt with error pattern matching
    - Locate the retry prompt construction (when `request.error_log and request.previous_code`)
    - Add new section after "ERROR LOG:":
      ```
      ============================================================
      ERROR CORRECTION GUIDANCE
      ============================================================
      CRITICAL: Read the error log carefully and fix the EXACT issue mentioned.
      
      Common error patterns and fixes:
      - "NameError: name 'CYAN' is not defined" → Replace CYAN with BLUE
      - "NameError: name 'X' is not defined" → Check imports and use valid Manim constants
      - "TypeError: got multiple values for argument 'color'" → Remove duplicate parameters
      - "SyntaxWarning: invalid escape sequence" → Use raw strings: r"..." or double backslashes
      - "LaTeX Error: File 'X' not found" → Simplify LaTeX or use basic commands
      
      Fix strategy:
      1. Identify the exact line number and error type from the log
      2. Apply the specific fix for that error pattern
      3. Verify no other instances of the same error exist in the code
      ```
    - _Requirements: 1.5, 2.5_

  - [ ] 4.5 Verify bug condition exploration tests now pass for API syntax
    - **Property 1: Expected Behavior** - Manim API Syntax Correctness
    - **IMPORTANT**: Re-run the SAME tests from tasks 1.2, 1.3, 1.4 - do NOT write new tests
    - Run color constant validity test from step 1.2
    - **EXPECTED OUTCOME**: Test PASSES (confirms CYAN bug is fixed)
    - Run parameter uniqueness test from step 1.3
    - **EXPECTED OUTCOME**: Test PASSES (confirms duplicate parameter bug is fixed)
    - Run string escape sequence test from step 1.4
    - **EXPECTED OUTCOME**: Test PASSES (confirms escape sequence bug is fixed)
    - _Requirements: 2.2, 2.3, 2.4_

  - [ ] 4.6 Verify retry mechanism test now passes
    - **Property 1: Expected Behavior** - Retry Mechanism Recovery
    - **IMPORTANT**: Re-run the SAME test from task 1.5 - do NOT write a new test
    - Run retry mechanism effectiveness test from step 1.5
    - **EXPECTED OUTCOME**: Test PASSES (confirms retry mechanism recovers within 3 attempts)
    - _Requirements: 2.5_

- [ ] 5. Add parallel execution support to orchestrator

  - [ ] 5.1 Add execution mode configuration to shared/config.py
    - Open `shared/config.py`
    - Add new configuration parameter after SERVICE_HTTP_TIMEOUT_SECONDS:
      ```python
      # ── Pipeline Execution Mode ───────────────────────────────────────────
      EXECUTION_MODE: str = os.getenv("EXECUTION_MODE", "serial")  # serial | parallel
      ```
    - Add validation in Settings class `__init__` or using Pydantic validator:
      ```python
      @field_validator('EXECUTION_MODE')
      def validate_execution_mode(cls, v):
          if v not in ['serial', 'parallel']:
              raise ValueError('EXECUTION_MODE must be "serial" or "parallel"')
          return v
      ```
    - _Bug_Condition: Pipeline processes scenes sequentially even when they could be processed concurrently_
    - _Expected_Behavior: Configurable execution modes with serial as default_
    - _Preservation: Existing configuration structure remains unchanged (3.2)_
    - _Requirements: 1.6, 2.6, 3.2_

  - [ ] 5.2 Implement parallel code generation in orchestrator
    - Open `services/orchestrator/app/core/graph.py`
    - Locate `code_generator_node` function
    - Add import at top: `import asyncio`
    - Refactor code generation logic to support parallel execution:
      ```python
      async def code_generator_node(state: LangGraphState):
          logger.info("Executing Code Generator Node")
          try:
              script = state["script"]
              job_id = state["job_id"]
              new_code_paths = state.get("code_paths", {})
              
              # Collect scenes that need generation
              scenes_to_generate = []
              for scene in script["scenes"]:
                  scene_id = scene["scene_id"]
                  if scene_id not in state.get("render_paths", {}) and state.get("retry_counts", {}).get(scene_id, 0) < 3:
                      scenes_to_generate.append(scene)
              
              # Process based on execution mode
              if settings.EXECUTION_MODE == "parallel":
                  # Parallel execution using asyncio.gather
                  tasks = []
                  for scene in scenes_to_generate:
                      request_data = {
                          "scene": scene,
                          "job_id": job_id,
                          "error_log": state.get("error_logs", {}).get(scene["scene_id"]),
                          "previous_code": state.get("previous_code", {}).get(scene["scene_id"])
                      }
                      tasks.append(_post(f"{settings.CODE_GENERATOR_URL}/generate", request_data))
                  
                  results = await asyncio.gather(*tasks, return_exceptions=True)
                  
                  # Process results
                  for scene, result in zip(scenes_to_generate, results):
                      if isinstance(result, Exception):
                          logger.error(f"Code generation failed for scene {scene['scene_id']}: {result}")
                          continue
                      
                      scene_id = scene["scene_id"]
                      new_code_paths[scene_id] = result["code_path"]
                      
                      # Keep track of generated code
                      with open(result["code_path"], "r") as f:
                          code_content = f.read()
                      if "previous_code" not in state:
                          state["previous_code"] = {}
                      state["previous_code"][scene_id] = code_content
              else:
                  # Serial execution (original behavior)
                  for scene in scenes_to_generate:
                      scene_id = scene["scene_id"]
                      request_data = {
                          "scene": scene,
                          "job_id": job_id,
                          "error_log": state.get("error_logs", {}).get(scene_id),
                          "previous_code": state.get("previous_code", {}).get(scene_id)
                      }
                      res = await _post(f"{settings.CODE_GENERATOR_URL}/generate", request_data)
                      new_code_paths[scene_id] = res["code_path"]
                      
                      with open(res["code_path"], "r") as f:
                          code_content = f.read()
                      if "previous_code" not in state:
                          state["previous_code"] = {}
                      state["previous_code"][scene_id] = code_content
              
              return {"code_paths": new_code_paths, "status": "code_generation"}
          except Exception as e:
              logger.error(f"Code Generator failed: {e}")
              return {"status": "failed", "overall_error": str(e) or f"{type(e).__name__}"}
      ```
    - _Bug_Condition: Sequential processing causes unnecessary delays_
    - _Expected_Behavior: Parallel processing when mode is "parallel", serial when mode is "serial"_
    - _Preservation: Serial mode behavior remains unchanged (3.6)_
    - _Requirements: 1.6, 2.6, 2.7, 3.6_

  - [ ] 5.3 Implement parallel validation in orchestrator
    - In the same file, locate `validator_node` function
    - Refactor validation logic to support parallel execution:
      ```python
      async def validator_node(state: LangGraphState):
          logger.info("Executing Validator Node")
          try:
              job_id = state["job_id"]
              new_render_paths = state.get("render_paths", {})
              new_error_logs = state.get("error_logs", {})
              new_retry_counts = state.get("retry_counts", {})
              
              # Collect scenes that need validation
              scenes_to_validate = []
              for scene_id, code_path in state["code_paths"].items():
                  if scene_id not in new_render_paths and new_retry_counts.get(scene_id, 0) < 3:
                      scenes_to_validate.append((scene_id, code_path))
              
              # Process based on execution mode
              if settings.EXECUTION_MODE == "parallel":
                  # Parallel execution using asyncio.gather
                  tasks = []
                  for scene_id, code_path in scenes_to_validate:
                      req = {
                          "job_id": job_id,
                          "scene_id": scene_id,
                          "code_path": code_path
                      }
                      tasks.append(_post(f"{settings.VALIDATOR_URL}/validate", req))
                  
                  results = await asyncio.gather(*tasks, return_exceptions=True)
                  
                  # Process results
                  for (scene_id, code_path), result in zip(scenes_to_validate, results):
                      if isinstance(result, Exception):
                          logger.error(f"Validation failed for scene {scene_id}: {result}")
                          new_error_logs[scene_id] = str(result)
                          new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
                          continue
                      
                      if result["success"]:
                          new_render_paths[scene_id] = result["render_path"]
                          if scene_id in new_error_logs:
                              del new_error_logs[scene_id]
                      else:
                          new_error_logs[scene_id] = result["error_log"]
                          new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
              else:
                  # Serial execution (original behavior)
                  for scene_id, code_path in scenes_to_validate:
                      req = {
                          "job_id": job_id,
                          "scene_id": scene_id,
                          "code_path": code_path
                      }
                      res = await _post(f"{settings.VALIDATOR_URL}/validate", req)
                      
                      if res["success"]:
                          new_render_paths[scene_id] = res["render_path"]
                          if scene_id in new_error_logs:
                              del new_error_logs[scene_id]
                      else:
                          new_error_logs[scene_id] = res["error_log"]
                          new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
              
              return {
                  "render_paths": new_render_paths,
                  "error_logs": new_error_logs,
                  "retry_counts": new_retry_counts,
                  "status": "validation"
              }
          except Exception as e:
              logger.error(f"Validator failed: {e}")
              return {"status": "failed", "overall_error": str(e)}
      ```
    - _Requirements: 2.6, 2.7, 3.6_

  - [ ] 5.4 Add execution mode to environment configuration
    - Open `.env.template` and add new variable:
      ```
      # Pipeline Execution Mode (serial | parallel)
      EXECUTION_MODE=serial
      ```
    - Open `.env` and add the same variable
    - Document in comments: "Use 'serial' for debugging (sequential processing), 'parallel' for production (concurrent processing)"
    - _Requirements: 2.6_

  - [ ] 5.5 Test parallel execution mode
    - Set `EXECUTION_MODE=parallel` in `.env`
    - Run full pipeline with multiple scenes
    - Verify all scenes are processed concurrently (check logs for parallel execution)
    - Verify final output is identical to serial mode
    - Measure execution time improvement
    - _Requirements: 2.6, 2.7, 3.6_

  - [ ] 5.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Pipeline Execution Consistency
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run all preservation tests from Phase 2
    - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions)
    - Verify tests pass in both serial and parallel modes
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

---

## Phase 4: Integration Testing and Validation

- [ ] 6. Integration testing and final validation

  - [ ] 6.1 Test full pipeline with previously failing scenes
    - Run full pipeline with scenes 1, 3, and 4 (previously failing)
    - Verify all scenes render successfully without LaTeX, syntax, or escape errors
    - Check that render_paths are populated for all scenes
    - Verify video files exist and are valid
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

  - [ ] 6.2 Test full pipeline with all scenes
    - Run full pipeline with all 5 scenes
    - Verify scenes 2 and 5 continue to render successfully (preservation)
    - Verify scenes 1, 3, and 4 now render successfully (bug fixes)
    - Check final video assembly completes successfully
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1_

  - [ ] 6.3 Test retry mechanism with intentional errors
    - Modify code generator to produce correctable errors
    - Verify retry mechanism recovers within 3 attempts
    - Verify error feedback loop provides sufficient context
    - Check that error_logs are properly captured and passed
    - _Requirements: 1.5, 2.5, 3.3_

  - [ ] 6.4 Test parallel vs serial execution consistency
    - Run same pipeline in serial mode and parallel mode
    - Verify both modes produce identical final output
    - Verify both modes handle errors identically
    - Measure and document execution time improvement in parallel mode
    - _Requirements: 2.6, 2.7, 3.6_

  - [ ] 6.5 Test Docker container builds
    - Run `make build` to rebuild all Docker images
    - Verify all containers start successfully
    - Verify validator container has LaTeX packages installed
    - Test LaTeX compilation in validator: `docker exec <validator-container> pdflatex --version`
    - _Requirements: 2.1, 3.4_

  - [ ] 6.6 Run all property-based tests
    - Run all bug condition exploration tests (should now PASS)
    - Run all preservation tests (should still PASS)
    - Verify no test failures or regressions
    - Document any counterexamples found
    - _Requirements: All requirements_

- [ ] 7. Checkpoint - Ensure all tests pass
  - Verify all bug condition exploration tests pass (Phase 1 tests now pass after fixes)
  - Verify all preservation tests pass (Phase 2 tests still pass)
  - Verify all integration tests pass (Phase 4 tests)
  - Confirm no regressions in existing functionality
  - Confirm all three bug categories are resolved:
    - LaTeX compilation errors fixed
    - Manim API syntax errors fixed
    - Python string escape sequence errors fixed
  - Confirm parallel execution mode works correctly
  - Ask the user if questions arise

---

## Notes

- **LaTeX Packages**: The base Docker image already includes `texlive-latex-extra`, so task 3.1 is primarily verification
- **Prompt Engineering**: The main fixes are in the code generator prompt to prevent errors at generation time
- **Parallel Execution**: Implemented as opt-in feature with serial mode as default for backward compatibility
- **Testing Strategy**: Follows observation-first methodology for preservation tests
- **Error Recovery**: Enhanced retry prompt provides specific guidance for common error patterns

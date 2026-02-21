# Jelly
Test driven AI agent programming development.

THIS IS WHERE THE REQUIREMENTS SHOULD BE KEPT UP TO DATE. IF AGENTS OR USERS LEARN OF UPDATES TO THE REQURIEMENTS THEY SHOULD EDIT THEM HERE.

What we want to achieve:
1. Testing agent tests the code and keeps giving feedback and iterating based on performance until the code works well.
2. On beginning of execution, the builder should run a hybrid capability gate (deterministic preflight + LLM assessment) to decide whether it can produce and test a working solution for the requirements with its current setup.
   - If capable, run the normal build/test/refine loop.
   - If not capable, call a "pregnancy" system that duplicates this repo into a child folder and runs a child builder there. Recursion is bounded by configurable max depth (default 3).
   - Child runs return task outputs/artifacts back to the parent user flow (task-output only; no automatic parent self-modification).
   - Filesystem and browser MCP baselines should be checked and reported up front; by default they are recommended diagnostics, not hard blockers.
3. We shift from a history based context paradigm to a documentation based context paradigm to be more model effective and efficient. This entails always asking an agent, one every new prompt if the docuemntation is still up to date or if we need to update it, and to do so if needed. We also need to ask upon testing code if the documentaiton is up to date or if we need to record a difficult issue. Upon any research we should update the documentation as well. Essentially after every user prompt we should check to update an agent_requirements.md (initially a duplicate of the requirements we start executing) and then after every agent completion we should check to see if a agent_learnings.md needs updating.

What is Done Thus Far:
Inspired from AgentCoder (https://arxiv.org/pdf/2312.13010 in the root directory). Currently implements 5 agents:
1. planner.py ⁠ (⁠ Planner ⁠): interactive requirements-gathering agent. It runs a multi-turn conversation with the user, then can generate a structured requirements doc and suggest implementation approaches.
2.⁠ judge.py ⁠ (⁠ Judge ⁠): requirements quality scorer. It evaluates specs across 5 dimensions (specificity, edge cases, API surface, testability, completeness), returns a normalized score out of 100, and gives improvement suggestions.
3. programmer.py ⁠ (⁠ Programmer ⁠): code generator/refiner. It turns requirements into source files (expects one file per fenced block with ⁠ # src/<file> ⁠), then iteratively fixes code based on test failure feedback.
4. test_designer.py ⁠ (⁠ TestDesigner ⁠): test authoring agent. It generates spec-driven tests (basic, edge, large-scale), can adapt tests to actual generated code names/imports, and can build MCP-based test plans (including selecting/installing MCP servers).
5. test_executor.py ⁠ (⁠ TestExecutor ⁠): execution engine for tests (minimal LLM use). It runs sandboxed unit tests, can run MCP test steps, merges results, and formats failures for the programmer loop.

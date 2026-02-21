# Jelly
Test driven AI agent programming development.

What we want to achieve:
1. Agent automatically configures required prompts and mcp's. (We should give a list of recommended ones, then give links to markets then tell it to make the MCP's itself). It needs to be able to test the specific thing it makes.
2. Testing agent tests the code and keeps giving feedback and iterating based on performance until the code works well.
3. We shift from a history based context paradigm to a documentation based context paradigm to be more model effective and efficient.

What is Done Thus Far:
Inspired from AgentCoder (https://arxiv.org/pdf/2312.13010 in the root directory). Currently implements 5 agents:
1. planner.py ⁠ (⁠ Planner ⁠): interactive requirements-gathering agent. It runs a multi-turn conversation with the user, then can generate a structured requirements doc and suggest implementation approaches.
2.⁠ judge.py ⁠ (⁠ Judge ⁠): requirements quality scorer. It evaluates specs across 5 dimensions (specificity, edge cases, API surface, testability, completeness), returns a normalized score out of 100, and gives improvement suggestions.
3. programmer.py ⁠ (⁠ Programmer ⁠): code generator/refiner. It turns requirements into source files (expects one file per fenced block with ⁠ # src/<file> ⁠), then iteratively fixes code based on test failure feedback.
4. test_designer.py ⁠ (⁠ TestDesigner ⁠): test authoring agent. It generates spec-driven tests (basic, edge, large-scale), can adapt tests to actual generated code names/imports, and can build MCP-based test plans (including selecting/installing MCP servers).
5. test_executor.py ⁠ (⁠ TestExecutor ⁠): execution engine for tests (minimal LLM use). It runs sandboxed unit tests, can run MCP test steps, merges results, and formats failures for the programmer loop.

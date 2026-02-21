# Jelly
Test driven AI agent programming development.

THIS IS WHERE THE REQUIREMENTS SHOULD BE KEPT UP TO DATE. IF AGENTS OR USERS LEARN OF UPDATES TO THE REQURIEMENTS THEY SHOULD EDIT THEM HERE.

What we want to achieve:
1. Testing agent tests the code and keeps giving feedback and iterating based on performance until the code works well.
2. An agent should, on beginning of execution, ask weather or not the current system is capable of producing and testing a working solution for the requirements. If it isn't, it should call a "pregnancy" system which duplicates this jelly repo into a child folder, from there a set of requirements for an agent that can complete the tasks (or produce a child recursively until it can etc) and use the same editing and testing loop on this child until it works. Typically this will involve the setup and testing of mcp's and tailored prompts. Once the child is working it should run the child with the requirements and then pass back the output to the initial user.a
3. We shift from a history based context paradigm to a documentation based context paradigm to be more model effective and efficient. This entails always asking an agent, one every new prompt if the docuemntation is still up to date or if we need to update it, and to do so if needed. We also need to ask upon testing code if the documentaiton is up to date or if we need to record a difficult issue. Upon any research we should update the documentation as well. Essentially after every user prompt we should check to update an agent_requirements.md (initially a duplicate of the requirements we start executing) and then after every agent completion we should check to see if a agent_learnings.md needs updating.

What is Done Thus Far:
Inspired from AgentCoder (https://arxiv.org/pdf/2312.13010 in the root directory). Currently implements 5 agents:
1. planner.py ⁠ (⁠ Planner ⁠): interactive requirements-gathering agent. It runs a multi-turn conversation with the user, then can generate a structured requirements doc and suggest implementation approaches.
2.⁠ judge.py ⁠ (⁠ Judge ⁠): requirements quality scorer. It evaluates specs across 5 dimensions (specificity, edge cases, API surface, testability, completeness), returns a normalized score out of 100, and gives improvement suggestions.
3. programmer.py ⁠ (⁠ Programmer ⁠): code generator/refiner. It turns requirements into source files (expects one file per fenced block with ⁠ # src/<file> ⁠), then iteratively fixes code based on test failure feedback.
4. test_designer.py ⁠ (⁠ TestDesigner ⁠): test authoring agent. It generates spec-driven tests (basic, edge, large-scale), can adapt tests to actual generated code names/imports, and can build MCP-based test plans (including selecting/installing MCP servers).
5. test_executor.py ⁠ (⁠ TestExecutor ⁠): execution engine for tests (minimal LLM use). It runs sandboxed unit tests, can run MCP test steps, merges results, and formats failures for the programmer loop.

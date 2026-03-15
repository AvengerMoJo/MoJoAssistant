"""Prompt-based Planning Workflow with Versioning."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class PlanningPrompt:
    """A versioned planning prompt for agentic workflows."""

    def __init__(
        self,
        name: str,
        content: str,
        version: str = "1.0.0",
        author: str = "system",
        description: str = "",
        tags: List[str] = None,
        created_at: str = None,
    ):
        self.name = name
        self.content = content
        self.version = version
        self.author = author
        self.description = description
        self.tags = tags or []
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningPrompt":
        return cls(
            name=data["name"],
            content=data["content"],
            version=data.get("version", "1.0.0"),
            author=data.get("author", "system"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at"),
        )


class PlanningPromptManager:
    """Manage versioned planning prompts for agentic workflows."""

    def __init__(self, prompts_path: str = None):
        config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        self.prompts_path = prompts_path or os.path.join(config_dir, "planning_prompts.json")
        self.example_prompts_path = os.path.join(
            config_dir, "examples", "planning_prompts.example.json"
        )
        self._prompts: Dict[str, Dict[str, PlanningPrompt]] = {}
        self._ensure_prompts_seeded()
        self._load_prompts()
        self._load_default_prompts()

    def _ensure_prompts_seeded(self):
        """Seed runtime prompts from example template if runtime file is missing."""
        if os.path.exists(self.prompts_path):
            return
        try:
            os.makedirs(os.path.dirname(self.prompts_path), exist_ok=True)
            if os.path.exists(self.example_prompts_path):
                with open(self.example_prompts_path, "r", encoding="utf-8") as src:
                    data = json.load(src)
                with open(self.prompts_path, "w", encoding="utf-8") as dst:
                    json.dump(data, dst, indent=2)
        except Exception as e:
            print(f"Failed to seed planning prompts from template: {e}")

    def _load_prompts(self):
        """Load prompts from file."""
        if os.path.exists(self.prompts_path):
            try:
                with open(self.prompts_path, "r") as f:
                    data = json.load(f)
                    for name, versions in data.get("prompts", {}).items():
                        self._prompts[name] = {}
                        for ver, prompt_data in versions.items():
                            prompt = PlanningPrompt.from_dict(prompt_data)
                            self._prompts[name][ver] = prompt
            except Exception as e:
                print(f"Failed to load planning prompts: {e}")

    def _save_prompts(self):
        """Save prompts to file."""
        try:
            os.makedirs(os.path.dirname(self.prompts_path), exist_ok=True)
            data = {
                "last_updated": datetime.now().isoformat(),
                "prompts": {
                    name: {ver: prompt.to_dict() for ver, prompt in versions.items()}
                    for name, versions in self._prompts.items()
                },
            }
            with open(self.prompts_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save planning prompts: {e}")

    def _load_default_prompts(self):
        """Load default planning prompts if not exists."""
        default_prompts = self._get_default_prompts()
        for name, prompt_content in default_prompts.items():
            if name not in self._prompts or "1.0.0" not in self._prompts[name]:
                prompt = PlanningPrompt(
                    name=name,
                    content=prompt_content["content"],
                    version="1.0.0",
                    description=prompt_content["description"],
                    tags=prompt_content["tags"],
                )
                self.add_prompt(prompt)

    def _get_default_prompts(self) -> Dict[str, Dict[str, str]]:
        """Get default planning prompts."""
        return {
            "agentic_planning": {
                "description": "Standard agentic task planning workflow",
                "tags": ["agentic", "planning", "general"],
                "content": """You are an autonomous agent working on a task. Follow this planning workflow:

## Phase 1: Understand the Task
- Analyze the goal and requirements
- Identify what information or tools are needed
- Check for dependencies or prerequisites
- Ask clarifying questions if needed

## Phase 2: Plan the Execution
- Break the task into clear, sequential steps
- For each step, identify:
  - What action to take
  - What tools or resources needed
  - Expected output or result
  - How to verify success
- Order the steps logically
- Estimate time/resources for each step

## Phase 3: Execute Step by Step
- Execute one step at a time
- After each step:
  - Verify the result
  - Provide progress update
  - Adjust plan if issues arise
- Continue until all steps complete

## Phase 4: Final Validation
- Review all completed steps
- Verify the original goal is achieved
- Provide final answer or results
- Run a final quality gate before completion:
  - Ensure output format exactly matches requirements
  - Ensure required tokens/fields are present
  - Ensure no planning boilerplate appears in FINAL_ANSWER

## Progress Updates
- After each significant step, provide:
  - What was just done
  - What was achieved
  - What's coming next
  - Any issues encountered

## Completion
- When goal is achieved, wrap final answer in <FINAL_ANSWER> tags
- Include summary of what was accomplished
- Note any issues or warnings
- If exact text is requested, FINAL_ANSWER must contain only that exact text

Remember: Work systematically, verify each step, and communicate progress clearly.
""",
            },
            "documentation_update": {
                "description": "Specialized planning for documentation updates",
                "tags": ["documentation", "files", "markdown"],
                "content": """You are updating documentation (README, docs, etc.). Follow this workflow:

## Phase 1: Understand the Update
- Read the existing documentation file
- Identify all sections that need updates
- Note the structure and formatting style
- List specific changes required

## Phase 2: Plan the Changes
- Create a checklist of updates:
  - Version badges
  - Architecture sections
  - Feature descriptions
  - Installation instructions
  - Configuration examples
  - Troubleshooting guides
- Determine update order
- Plan to preserve existing content

## Phase 3: Execute Updates
- Read the complete file content
- Make each change systematically
- Preserve formatting and structure
- Ensure all links and references are valid
- Verify no content is accidentally removed

## Phase 4: Validation
- Read the updated file
- Verify all changes are applied
- Check for broken formatting
- Ensure consistency with existing style
- Confirm no unintended deletions

## Output Format
- When complete, provide the FULL updated file content
- Do NOT use placeholders like "...rest unchanged"
- Every line must be included in the final output
- Wrap in <FINAL_ANSWER> tags

Remember: Documentation must be complete, accurate, and consistent.
""",
            },
            "coding_task": {
                "description": "Planning for coding and development tasks",
                "tags": ["coding", "development", "git"],
                "content": """You are working on a coding task. Follow this workflow:

## Phase 1: Understand the Codebase
- Read relevant files to understand context
- Identify coding conventions and patterns
- Find similar implementations as reference
- Understand the project structure

## Phase 2: Plan the Changes
- Break down the coding task into sub-tasks
- Identify files to modify
- Plan tests to verify changes
- Consider edge cases and error handling
- Estimate complexity and time

## Phase 3: Implement Changes
- Make changes systematically
- Follow existing code conventions
- Add appropriate comments if needed
- Ensure backward compatibility
- Test each change as you go

## Phase 4: Validate
- Run existing tests
- Add new tests if needed
- Check for regressions
- Verify requirements are met
- Clean up any temporary code

## Git Workflow (if applicable)
- Create a feature branch
- Commit changes with clear messages
- Run linting and type checking
- Prepare for code review

## Completion
- Provide summary of changes
- List files modified
- Note any breaking changes
- Include test results

Remember: Code should be clean, tested, and maintainable.
""",
            },
            "assistant_workflow": {
                "description": "MoJo agentic assistant workflow — budget-aware autonomous task execution",
                "tags": ["assistant", "workflow", "budget", "mojo", "scheduler"],
                "content": """You are an autonomous agent running inside the MoJo Scheduler.
You are given a goal, a set of tools, and a fixed iteration budget.

## Iteration Budget Awareness
You will be told your iteration limit at the start. Work with this budget in mind:
- Phases 1–2 (understand + plan): use at most 20% of your budget
- Phase 3 (execute): use up to 70% of your budget
- Phase 4 (synthesise + wrap up): reserve the final 10% (at least 1 iteration)

If you realise mid-task that the goal cannot be fully achieved within the remaining budget:
- Stop gathering more data
- Wrap up with what you have
- State clearly what was completed and what remains

## FINAL_ANSWER Contract
When your work is done — or when you must wrap up due to budget — produce your answer inside
<FINAL_ANSWER> tags:

<FINAL_ANSWER>
**Completed:** (what was accomplished)
**Findings:** (key results or data gathered)
**Incomplete:** (what was not finished, if anything)
**Resume hint:** (brief note for the next run, if applicable)
</FINAL_ANSWER>

IMPORTANT: You will receive an explicit ⚠ ITERATION BUDGET WARNING message when only 1–2 iterations
remain. When you see that warning, stop all tool calls immediately and produce your FINAL_ANSWER.

## Workflow Phases

### Phase 1 — Understand (1–2 iterations)
- Parse the goal and identify required information
- Note what tools are available and which are relevant

### Phase 2 — Plan (1 iteration)
- List the concrete steps you will take
- Estimate how many iterations each step needs
- Confirm the plan fits within budget

### Phase 3 — Execute
- Run steps one at a time; verify each result before proceeding
- After each tool call, reassess whether you still need more calls or can conclude

### Phase 4 — Synthesise
- Combine all gathered information into a clear answer
- Do not call any more tools in this phase

## Rules
- Never repeat a tool call with the same arguments if it already succeeded
- If a tool fails twice, skip it and note the failure in your answer
- Prefer breadth over depth when time is short — a partial answer with clear gaps is better than no answer
""",
            },
            "debugging_task": {
                "description": "Planning for debugging and troubleshooting",
                "tags": ["debugging", "troubleshooting", "logs"],
                "content": """You are debugging an issue. Follow this workflow:

## Phase 1: Understand the Problem
- Read the error message or symptoms
- Identify when the issue occurs
- Understand expected vs actual behavior
- Gather relevant context

## Phase 2: Investigate
- Read relevant code sections
- Check logs and error traces
- Examine configuration files
- Search for similar issues

## Phase 3: Plan Fix Strategy
- Identify root cause
- Consider multiple fix approaches
- Choose the safest solution
- Plan testing to verify fix

## Phase 4: Implement and Test
- Apply the fix
- Test thoroughly
- Check for side effects
- Verify issue is resolved

## Phase 5: Document
- Document the root cause
- Explain the fix
- Add comments if needed
- Prevent similar issues

## Completion
- Summary of the issue
- Root cause analysis
- Fix implemented
- Test results

Remember: Thorough investigation leads to effective solutions.
""",
            },
        }

    def list_prompts(self) -> Dict[str, Dict[str, Dict]]:
        """List all prompts by name and version."""
        result = {}
        for name, versions in self._prompts.items():
            result[name] = {
                ver: {
                    "version": ver,
                    "description": prompt.description,
                    "tags": prompt.tags,
                    "author": prompt.author,
                    "created_at": prompt.created_at,
                }
                for ver, prompt in versions.items()
            }
        return result

    def get_prompt(
        self, name: str, version: str = "latest"
    ) -> Optional[PlanningPrompt]:
        """Get a prompt by name and version."""
        if name not in self._prompts:
            return None

        if version == "latest":
            versions = sorted(self._prompts[name].keys())
            if not versions:
                return None
            version = versions[-1]

        return self._prompts[name].get(version)

    def add_prompt(self, prompt: PlanningPrompt) -> bool:
        """Add a new prompt."""
        if prompt.name not in self._prompts:
            self._prompts[prompt.name] = {}
        self._prompts[prompt.name][prompt.version] = prompt
        self._save_prompts()
        return True

    def update_prompt(
        self, name: str, version: str, content: str, author: str = "mcp_client"
    ) -> bool:
        """Update an existing prompt content."""
        if name not in self._prompts or version not in self._prompts[name]:
            return False

        self._prompts[name][version].content = content
        self._prompts[name][version].author = author
        self._save_prompts()
        return True

    def create_new_version(
        self, name: str, content: str, new_version: str, author: str = "mcp_client"
    ) -> bool:
        """Create a new version of an existing prompt."""
        if name not in self._prompts:
            return False

        latest_prompt = self.get_prompt(name, "latest")
        if not latest_prompt:
            return False

        new_prompt = PlanningPrompt(
            name=name,
            content=content,
            version=new_version,
            author=author,
            description=latest_prompt.description,
            tags=latest_prompt.tags,
        )
        self._prompts[name][new_version] = new_prompt
        self._save_prompts()
        return True

    def delete_prompt(self, name: str, version: str = None) -> bool:
        """Delete a prompt or specific version."""
        if name not in self._prompts:
            return False

        if version:
            if version in self._prompts[name]:
                del self._prompts[name][version]
                if not self._prompts[name]:
                    del self._prompts[name]
                self._save_prompts()
                return True
        else:
            del self._prompts[name]
            self._save_prompts()
            return True

        return False

    def search_prompts(self, query: str) -> Dict[str, Dict[str, Dict]]:
        """Search prompts by name, tags, or content."""
        query_lower = query.lower()
        results = {}

        for name, versions in self._prompts.items():
            for ver, prompt in versions.items():
                matches = (
                    query_lower in name.lower()
                    or query_lower in prompt.description.lower()
                    or any(query_lower in tag.lower() for tag in prompt.tags)
                    or query_lower in prompt.content.lower()
                )
                if matches:
                    if name not in results:
                        results[name] = {}
                    results[name][ver] = {
                        "version": ver,
                        "description": prompt.description,
                        "tags": prompt.tags,
                        "author": prompt.author,
                    }

        return results

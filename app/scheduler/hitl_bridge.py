"""
HITL bridge for external coding agents (Claude Code, OpenCode, etc.).

External agents connected to MoJoAssistant via MCP can call
external_agent(action="ask_user") to pause and inject a question into
the HITL inbox, then poll external_agent(action="check_reply") until
the user replies via reply_to_task().

This module contains the pure queue operations so they can be tested
independently of the full ToolRegistry.

Physical flow:
  coding agent  →  ask_user(queue, task_id, question)
                   ├── creates/updates stub task (WAITING_FOR_INPUT)
                   └── returns {"status": "waiting", "poll_with": ...}

  user          →  reply_to_task(task_id, reply)
                   └── resume_task_with_reply detects ext_agent_hitl=True
                       sets config["ext_agent_reply"], keeps status RUNNING

  coding agent  →  check_reply(queue, task_id)
                   ├── {"status": "answered", "reply": "..."} and clears it
                   └── {"status": "pending"} if not yet answered
"""
# [hitl-orchestrator: generic]

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.scheduler.models import Task, TaskStatus, TaskType
from app.scheduler.queue import TaskQueue


def ask_user(
    queue: TaskQueue,
    task_id: str,
    question: str,
    options: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Register a question from an external agent in the HITL inbox.

    Creates a stub task if task_id is new; updates it if the agent
    asks a second question in the same session.
    """
    if not task_id:
        return {"status": "error", "message": "task_id is required"}
    if not question:
        return {"status": "error", "message": "question is required"}

    task = queue.get(task_id)
    if task is None:
        task = Task(
            id=task_id,
            type=TaskType.EXTERNAL_AGENT,
            status=TaskStatus.WAITING_FOR_INPUT,
            description=f"Ext-agent session: {task_id}",
            config={"ext_agent_hitl": True, "source": "external_agent"},
        )
        task.pending_question = question
        if options:
            task.config["pending_options"] = options
        queue.add(task)
    else:
        task.status = TaskStatus.WAITING_FOR_INPUT
        task.pending_question = question
        # Clear any stale reply from a previous round-trip
        task.config.pop("ext_agent_reply", None)
        task.config.pop("reply_to_question", None)
        if options:
            task.config["pending_options"] = options
        else:
            task.config.pop("pending_options", None)
        # Mark as ext_agent_hitl even if the task already existed
        task.config["ext_agent_hitl"] = True
        queue.update(task)

    return {
        "status": "waiting",
        "task_id": task_id,
        "message": (
            "Question submitted to HITL inbox. "
            "The user will see it in get_context() attention.blocking."
        ),
        "poll_with": f'external_agent(action="check_reply", task_id="{task_id}")',
        "user_reply_tool": f'reply_to_task(task_id="{task_id}", reply="...")',
    }


def check_reply(queue: TaskQueue, task_id: str) -> Dict[str, Any]:
    """
    Poll for user reply to a previous ask_user call.

    Returns {"status": "answered", "reply": "..."} when available,
    consuming the reply so it is only returned once.
    Returns {"status": "pending"} while still waiting.
    """
    if not task_id:
        return {"status": "error", "message": "task_id is required"}

    task = queue.get(task_id)
    if task is None:
        return {
            "status": "error",
            "message": (
                f"Task '{task_id}' not found. "
                "Call external_agent(action='ask_user', ...) first."
            ),
        }

    # Consume ext_agent_reply (set by resume_task_with_reply for ext_agent_hitl tasks)
    reply = task.config.pop("ext_agent_reply", None)
    if reply is not None:
        task.pending_question = None
        # Keep RUNNING so the agent can ask again; scheduler won't execute RUNNING tasks
        task.status = TaskStatus.RUNNING
        queue.update(task)
        return {"status": "answered", "reply": reply}

    if task.status == TaskStatus.WAITING_FOR_INPUT:
        return {
            "status": "pending",
            "question": task.pending_question,
        }

    # Task cancelled, failed, or completed — no reply expected
    return {
        "status": "no_reply",
        "task_status": task.status.value,
    }

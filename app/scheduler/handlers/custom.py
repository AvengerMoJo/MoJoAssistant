"""Custom task handler — user-defined shell commands, optionally via atd."""
from __future__ import annotations

import asyncio

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult


class CustomHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        command = task.config.get("command")
        use_atd = task.config.get("use_atd", False)
        at_delay = task.config.get("at_delay", 1)

        if not command:
            return TaskResult(
                success=False, error_message="Missing 'command' in task config"
            )

        ctx.log(f"Executing custom command: {command} (use_atd={use_atd})")

        try:
            if use_atd:
                ctx.log(f"Scheduling command via atd with {at_delay} minute delay")
                process = await asyncio.create_subprocess_shell(
                    f'echo "{command}" | at now + {at_delay}min',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    at_job_id = None
                    output = stdout.decode()
                    if "job" in output:
                        try:
                            at_job_id = output.split("job ")[1].split()[0]
                        except Exception:
                            pass

                    return TaskResult(
                        success=True,
                        metrics={
                            "return_code": process.returncode,
                            "scheduled_via": "atd",
                            "at_job_id": at_job_id,
                            "at_delay_minutes": at_delay,
                            "at_output": output,
                        },
                    )
                else:
                    return TaskResult(
                        success=False,
                        error_message=stderr.decode() if stderr else "Failed to schedule atd job",
                    )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    return TaskResult(
                        success=True,
                        metrics={
                            "return_code": process.returncode,
                            "stdout_length": len(stdout),
                            "stdout": stdout.decode()[:1000],
                        },
                    )
                else:
                    return TaskResult(
                        success=False,
                        error_message=stderr.decode() if stderr else "Command failed",
                    )

        except Exception as e:
            return TaskResult(
                success=False, error_message=f"Failed to execute command: {e}"
            )

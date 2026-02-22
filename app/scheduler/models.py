"""
Scheduler Data Models

Defines task structures and enums for the scheduler system.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum


class TaskStatus(Enum):
    """Task execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task priority levels"""

    CRITICAL = "critical"  # System tasks, must run immediately
    HIGH = "high"  # User-initiated, urgent
    MEDIUM = "medium"  # Scheduled maintenance
    LOW = "low"  # Background, non-urgent


class TaskType(Enum):
    """Types of tasks the scheduler can execute"""

    DREAMING = "dreaming"  # Memory consolidation (A→B→C→D pipeline)
    SCHEDULED = "scheduled"  # User calendar events
    AGENT = "agent"  # OpenCode/OpenClaw operations
    CUSTOM = "custom"  # User-defined tasks


@dataclass
class TaskResources:
    """Resource requirements and limits for a task"""

    llm_provider: Optional[str] = None  # local|openai|anthropic
    max_tokens: Optional[int] = None
    max_duration_seconds: Optional[int] = None
    requires_gpu: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResources":
        return cls(**data)


@dataclass
class Schedule:
    """Task schedule - can be datetime or cron expression"""

    when: Optional[datetime] = None  # When to run (None = immediate)
    cron_expression: Optional[str] = None  # Recurring schedule (e.g., "0 3 * * *")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Schedule":
        """Create Schedule instance from dictionary"""
        return cls(
            when=datetime.fromisoformat(data.get("when")) if data.get("when") else None,
            cron_expression=data.get("cron_expression"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {}
        if self.when:
            result["when"] = self.when.isoformat()
        if self.cron_expression:
            result["cron_expression"] = self.cron_expression
        return result



@dataclass
class TaskResult:
    """Result of task execution"""

    success: bool
    output_file: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["created_at"] = self.created_at.isoformat() if self.created_at else None
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        if "created_at" in data and data["created_at"]:
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class Task:
    """Scheduled task with metadata and execution state"""

    # Required fields
    id: str
    type: TaskType

    # Scheduling
    schedule: Optional[datetime] = None  # When to run (None = immediate)
    cron_expression: Optional[str] = None  # Recurring schedule (e.g., "0 3 * * *")

    # Status and priority
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM

    # Configuration
    config: Dict[str, Any] = field(default_factory=dict)  # Task-specific config
    resources: TaskResources = field(default_factory=TaskResources)

    # Execution tracking
    result: Optional[TaskResult] = None
    retry_count: int = 0
    max_retries: int = 3

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # User context
    created_by: str = "system"
    description: Optional[str] = None

    def is_due(self) -> bool:
        """Check if task is due to run"""
        if self.status != TaskStatus.PENDING:
            return False

        if self.schedule is None:
            return True  # Immediate execution

        return datetime.now() >= self.schedule

    def can_retry(self) -> bool:
        """Check if task can be retried after failure"""
        return self.retry_count < self.max_retries

    def mark_started(self):
        """Mark task as started"""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()

    def mark_completed(self, result: TaskResult):
        """Mark task as completed with result"""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now()
        self.result = result

    def mark_failed(self, error_message: str):
        """Mark task as failed"""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.result = TaskResult(success=False, error_message=error_message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = {
            "id": self.id,
            "type": self.type.value,
            "schedule": self.schedule.isoformat() if self.schedule else None,
            "cron_expression": self.cron_expression,
            "status": self.status.value,
            "priority": self.priority.value,
            "config": self.config,
            "resources": self.resources.to_dict(),
            "result": self.result.to_dict() if self.result else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "created_by": self.created_by,
            "description": self.description,
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create task from dictionary"""
        # Convert enums
        data["type"] = TaskType(data["type"])
        data["status"] = TaskStatus(data["status"])
        data["priority"] = TaskPriority(data["priority"])

        # Convert datetime strings
        if "schedule" in data and data["schedule"]:
            data["schedule"] = datetime.fromisoformat(data["schedule"])
        if "created_at" in data:
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "started_at" in data and data["started_at"]:
            data["started_at"] = datetime.fromisoformat(data["started_at"])
        if "completed_at" in data and data["completed_at"]:
            data["completed_at"] = datetime.fromisoformat(data["completed_at"])

        # Convert nested objects
        if "resources" in data and isinstance(data["resources"], dict):
            data["resources"] = TaskResources.from_dict(data["resources"])
        if "result" in data and data["result"]:
            data["result"] = TaskResult.from_dict(data["result"])

        return cls(**data)

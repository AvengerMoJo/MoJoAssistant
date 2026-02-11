"""
Trigger System for Scheduler

Handles time-based and event-based task triggering.
Supports cron-like expressions for recurring tasks.
"""

from datetime import datetime, timedelta
from typing import Optional, List
import re


class CronTrigger:
    """
    Simple cron-like trigger for recurring tasks

    Format: "minute hour day_of_month month day_of_week"
    Examples:
        "0 3 * * *"      - Every day at 3:00 AM
        "30 14 * * 1-5"  - Weekdays at 2:30 PM
        "0 */6 * * *"    - Every 6 hours
        "15 0 1 * *"     - First day of month at 12:15 AM
    """

    def __init__(self, expression: str):
        """
        Initialize cron trigger

        Args:
            expression: Cron expression string
        """
        self.expression = expression
        self.parts = expression.split()

        if len(self.parts) != 5:
            raise ValueError(
                f"Invalid cron expression: '{expression}'. "
                "Expected format: 'minute hour day month day_of_week'"
            )

        self.minute, self.hour, self.day, self.month, self.weekday = self.parts

    def matches(self, dt: datetime) -> bool:
        """
        Check if datetime matches the cron expression

        Args:
            dt: Datetime to check

        Returns:
            True if datetime matches cron pattern
        """
        # Check minute
        if not self._matches_field(self.minute, dt.minute, 0, 59):
            return False

        # Check hour
        if not self._matches_field(self.hour, dt.hour, 0, 23):
            return False

        # Check day of month
        if not self._matches_field(self.day, dt.day, 1, 31):
            return False

        # Check month
        if not self._matches_field(self.month, dt.month, 1, 12):
            return False

        # Check day of week (0=Sunday, 6=Saturday)
        # Python weekday(): 0=Monday, 6=Sunday
        # Convert to cron format
        cron_weekday = (dt.weekday() + 1) % 7
        if not self._matches_field(self.weekday, cron_weekday, 0, 6):
            return False

        return True

    def _matches_field(self, field: str, value: int, min_val: int, max_val: int) -> bool:
        """
        Check if a value matches a cron field pattern

        Supports:
        - * (any value)
        - specific value (e.g., "3")
        - range (e.g., "1-5")
        - step (e.g., "*/6")
        - list (e.g., "1,3,5")

        Args:
            field: Cron field pattern
            value: Value to check
            min_val: Minimum valid value
            max_val: Maximum valid value

        Returns:
            True if value matches pattern
        """
        # Any value
        if field == "*":
            return True

        # Step values (e.g., "*/6")
        if "/" in field:
            base, step = field.split("/")
            step = int(step)

            if base == "*":
                return value % step == 0
            else:
                base_val = int(base)
                return value >= base_val and (value - base_val) % step == 0

        # Range (e.g., "1-5")
        if "-" in field:
            start, end = field.split("-")
            return int(start) <= value <= int(end)

        # List (e.g., "1,3,5")
        if "," in field:
            values = [int(v) for v in field.split(",")]
            return value in values

        # Specific value
        return value == int(field)

    def get_next_run_time(self, after: datetime = None) -> datetime:
        """
        Calculate next time this cron expression will trigger

        Args:
            after: Calculate next run after this time (default: now)

        Returns:
            Next datetime when trigger will fire
        """
        if after is None:
            after = datetime.now()

        # Start from next minute
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Check up to 366 days ahead
        max_iterations = 366 * 24 * 60
        for _ in range(max_iterations):
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)

        raise RuntimeError(
            f"Could not find next run time for cron expression: {self.expression}"
        )


def parse_cron_expression(expression: str) -> CronTrigger:
    """
    Parse cron expression into trigger

    Args:
        expression: Cron expression string

    Returns:
        CronTrigger instance

    Raises:
        ValueError: If expression is invalid
    """
    return CronTrigger(expression)


def create_daily_trigger(hour: int, minute: int = 0) -> CronTrigger:
    """
    Create trigger that fires daily at specific time

    Args:
        hour: Hour (0-23)
        minute: Minute (0-59)

    Returns:
        CronTrigger for daily execution
    """
    return CronTrigger(f"{minute} {hour} * * *")


def create_hourly_trigger(minute: int = 0) -> CronTrigger:
    """
    Create trigger that fires every hour

    Args:
        minute: Minute past the hour (0-59)

    Returns:
        CronTrigger for hourly execution
    """
    return CronTrigger(f"{minute} * * * *")


def create_weekly_trigger(weekday: int, hour: int, minute: int = 0) -> CronTrigger:
    """
    Create trigger that fires weekly on specific day

    Args:
        weekday: Day of week (0=Sunday, 6=Saturday)
        hour: Hour (0-23)
        minute: Minute (0-59)

    Returns:
        CronTrigger for weekly execution
    """
    return CronTrigger(f"{minute} {hour} * * {weekday}")


# Predefined common triggers
TRIGGERS = {
    'daily_3am': create_daily_trigger(3, 0),        # 3:00 AM daily
    'daily_midnight': create_daily_trigger(0, 0),   # Midnight daily
    'hourly': create_hourly_trigger(0),             # Top of every hour
    'monday_morning': create_weekly_trigger(1, 9, 0),  # Monday 9:00 AM
}

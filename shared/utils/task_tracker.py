"""
Task Tracker Utility - Async Task Management with Exception Handling

Provides centralized management for asyncio tasks with automatic exception logging,
task cleanup, and graceful cancellation support.
"""

import asyncio
from typing import Coroutine, Optional, Set

from shared.logging import get_logger

logger = get_logger(__name__)


class TaskTracker:
    """
    Tracks and manages asyncio tasks with automatic exception handling.

    Features:
    - Automatic task cleanup when completed
    - Exception logging for failed tasks
    - Graceful cancellation of all tracked tasks
    - Task naming for easier debugging

    Usage:
        tracker = TaskTracker()
        tracker.create_task(some_coroutine(), name="my_task")
        await tracker.cancel_all()  # Graceful shutdown
    """

    def __init__(self, name: str = "default"):
        """
        Initialize TaskTracker.

        Args:
            name: Tracker name for logging purposes
        """
        self.name = name
        self.tasks: Set[asyncio.Task] = set()
        logger.info(f"TaskTracker '{name}' initialized")

    def create_task(
        self,
        coro: Coroutine,
        name: Optional[str] = None
    ) -> asyncio.Task:
        """
        Create and track an asyncio task with automatic cleanup.

        Args:
            coro: Coroutine to execute
            name: Optional task name for debugging

        Returns:
            Created asyncio.Task instance
        """
        task = asyncio.create_task(coro, name=name)
        self.tasks.add(task)

        # Automatic cleanup when task completes
        task.add_done_callback(self._on_task_done)

        task_name = name or f"task-{id(task)}"
        logger.debug(f"[{self.name}] Created task: {task_name}")

        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        """
        Callback when task completes - handles cleanup and exception logging.

        Args:
            task: Completed task
        """
        # Remove from tracking set
        self.tasks.discard(task)

        task_name = task.get_name()

        # Log exceptions if task failed
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.error(
                    f"[{self.name}] Task '{task_name}' failed with exception",
                    exc_info=exc
                )
            else:
                logger.debug(f"[{self.name}] Task '{task_name}' completed successfully")
        else:
            logger.debug(f"[{self.name}] Task '{task_name}' was cancelled")

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """
        Cancel all tracked tasks gracefully.

        Args:
            timeout: Maximum time to wait for task cancellation (seconds)
        """
        if not self.tasks:
            logger.info(f"[{self.name}] No tasks to cancel")
            return

        task_count = len(self.tasks)
        logger.info(f"[{self.name}] Cancelling {task_count} tasks...")

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for cancellation with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.tasks, return_exceptions=True),
                timeout=timeout
            )
            logger.info(f"[{self.name}] All tasks cancelled successfully")
        except asyncio.TimeoutError:
            logger.warning(
                f"[{self.name}] Timeout waiting for task cancellation "
                f"({task_count} tasks)"
            )

    def get_task_count(self) -> int:
        """
        Get number of currently tracked tasks.

        Returns:
            Number of active tasks
        """
        return len(self.tasks)

    def get_task_names(self) -> list[str]:
        """
        Get names of all tracked tasks.

        Returns:
            List of task names
        """
        return [task.get_name() for task in self.tasks]


# Global task tracker instance for convenience
_global_tracker: Optional[TaskTracker] = None


def get_task_tracker(name: str = "global") -> TaskTracker:
    """
    Get or create global task tracker instance.

    Args:
        name: Tracker name (default: "global")

    Returns:
        TaskTracker instance
    """
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TaskTracker(name=name)
    return _global_tracker


def create_tracked_task(
    coro: Coroutine,
    name: Optional[str] = None,
    tracker: Optional[TaskTracker] = None
) -> asyncio.Task:
    """
    Convenience function to create a tracked task.

    Args:
        coro: Coroutine to execute
        name: Optional task name
        tracker: Optional tracker instance (uses global if None)

    Returns:
        Created asyncio.Task
    """
    if tracker is None:
        tracker = get_task_tracker()
    return tracker.create_task(coro, name=name)

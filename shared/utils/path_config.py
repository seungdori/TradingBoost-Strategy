"""Centralized PYTHONPATH configuration for TradingBoost-Strategy monorepo.

This module provides a single, reusable function to configure the Python path
for all entry points (main.py, celery_app.py, etc.) in the monorepo.

Usage:
    from shared.utils.path_config import configure_pythonpath
    configure_pythonpath()
"""
import sys
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def configure_pythonpath() -> Path:
    """
    Configure PYTHONPATH for the TradingBoost-Strategy monorepo.

    Automatically detects the project root directory by looking for the 'shared'
    directory and 'setup.py' file, then adds it to sys.path if not already present.

    This function is idempotent - it's safe to call multiple times.

    Returns:
        Path: The project root directory path.

    Raises:
        RuntimeError: If the project root cannot be located.

    Examples:
        >>> from shared.utils.path_config import configure_pythonpath
        >>> project_root = configure_pythonpath()
        >>> print(f"Project root: {project_root}")
    """
    # Start from the current file and walk up the directory tree
    current = Path(__file__).resolve()

    while current.parent != current:  # Stop at filesystem root
        # Look for markers that indicate project root
        if (current / 'shared').exists() and (current / 'setup.py').exists():
            # Add to sys.path if not already present
            project_root_str = str(current)
            if project_root_str not in sys.path:
                sys.path.insert(0, project_root_str)

            return current

        current = current.parent

    # If we reach here, we couldn't find the project root
    raise RuntimeError(
        "Could not locate project root directory. "
        "Expected to find 'shared/' and 'setup.py' in a parent directory."
    )


def get_project_root() -> Path:
    """
    Get the project root directory without modifying sys.path.

    This is useful when you only need the path for file operations,
    not for imports.

    Returns:
        Path: The project root directory path.

    Raises:
        RuntimeError: If the project root cannot be located.
    """
    current = Path(__file__).resolve()

    while current.parent != current:
        if (current / 'shared').exists() and (current / 'setup.py').exists():
            return current
        current = current.parent

    raise RuntimeError(
        "Could not locate project root directory. "
        "Expected to find 'shared/' and 'setup.py' in a parent directory."
    )

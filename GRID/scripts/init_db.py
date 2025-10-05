"""
GRID Database Initialization Script

Creates all database tables and initializes default data.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from GRID.infra.database_pg import init_grid_db
from shared.logging import get_logger

logger = get_logger(__name__)


async def main():
    """Initialize GRID database"""
    try:
        logger.info("Starting GRID database initialization...")

        # Initialize tables
        await init_grid_db()

        logger.info("✅ GRID database initialization completed successfully")

    except Exception as e:
        logger.error(
            "❌ GRID database initialization failed",
            exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

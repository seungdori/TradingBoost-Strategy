"""
Job Repository

Handles all database operations related to Celery jobs.
"""

from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from GRID.models.user import Job
from shared.logging import get_logger

logger = get_logger(__name__)


class JobRepository:
    """Repository for Job model operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user(
        self, user_id: int, exchange_name: str
    ) -> Optional[Job]:
        """
        Get job by user ID and exchange name.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            Job object or None if not found
        """
        stmt = select(Job).where(
            Job.user_id == user_id,
            Job.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_job_id(
        self, user_id: int, exchange_name: str
    ) -> Optional[str]:
        """
        Get job ID for user.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            Job ID string or None
        """
        job = await self.get_by_user(user_id, exchange_name)
        return job.job_id if job else None

    async def get_job_status(
        self, user_id: int, exchange_name: str
    ) -> Optional[Tuple[str, str]]:
        """
        Get job status and ID for user.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            Tuple of (status, job_id) or None
        """
        job = await self.get_by_user(user_id, exchange_name)
        return (job.status, job.job_id) if job else None

    async def save_job(
        self,
        user_id: int,
        exchange_name: str,
        job_id: str,
        status: str = "running"
    ) -> Job:
        """
        Create or update job.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            job_id: Celery job ID
            status: Job status

        Returns:
            Job object
        """
        job = await self.get_by_user(user_id, exchange_name)

        if job:
            job.job_id = job_id
            job.status = status
            job.start_time = datetime.utcnow()
            job.updated_at = datetime.utcnow()
        else:
            job = Job(
                user_id=user_id,
                exchange_name=exchange_name,
                job_id=job_id,
                status=status,
                start_time=datetime.utcnow()
            )
            self.session.add(job)

        await self.session.flush()
        logger.info(
            f"Saved job {job_id} for user {user_id} with status {status}"
        )
        return job

    async def update_job_status(
        self,
        user_id: int,
        exchange_name: str,
        status: str,
        job_id: Optional[str] = None
    ) -> Optional[Job]:
        """
        Update job status.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            status: New job status
            job_id: Optional job ID (if creating new job)

        Returns:
            Updated Job object or None
        """
        job = await self.get_by_user(user_id, exchange_name)

        if job:
            # Update existing job
            if job_id:
                job.job_id = job_id
            job.status = status
            job.updated_at = datetime.utcnow()
            await self.session.flush()
            logger.info(
                f"Updated job status for user {user_id}: {status}"
            )
            return job
        elif job_id:
            # Create new job
            return await self.save_job(user_id, exchange_name, job_id, status)
        else:
            logger.warning(
                f"Cannot update job status for user {user_id}: "
                f"job not found and job_id not provided"
            )
            return None

    async def delete_job(
        self, user_id: int, exchange_name: str
    ) -> bool:
        """
        Delete job.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            True if deleted, False if not found
        """
        stmt = delete(Job).where(
            Job.user_id == user_id,
            Job.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)

        if result.rowcount > 0:
            logger.info(f"Deleted job for user {user_id}")
            return True
        return False

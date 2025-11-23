"""
유지보수 관련 Celery 태스크
로그 정리, 데이터베이스 정리 등 주기적인 유지보수 작업을 처리합니다.
"""

import gzip
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

from celery import shared_task
from celery.utils.log import get_task_logger

from HYPERRSI.src.core.logger import error_logger

logger = get_task_logger(__name__)


@shared_task(name='maintenance_tasks.cleanup_old_logs')
def cleanup_old_logs() -> Dict[str, Any]:
    """
    오래된 로그 파일을 자동으로 정리합니다.

    - 7일 이상 된 로그 파일 압축
    - 30일 이상 된 압축 파일 삭제
    - 100MB 이상 로그 파일 즉시 압축

    Returns:
        Dict[str, Any]: 정리 결과 통계
    """
    try:
        logger.info("🧹 로그 정리 작업 시작")

        # 로그 디렉토리 경로
        base_dir = Path(__file__).parent.parent.parent
        log_dir = base_dir / 'logs'

        if not log_dir.exists():
            logger.warning(f"로그 디렉토리가 존재하지 않습니다: {log_dir}")
            return {'success': False, 'error': 'Log directory not found'}

        # 설정
        COMPRESS_DAYS = 7
        DELETE_DAYS = 30
        MAX_SIZE_MB = 100

        stats = {
            'compressed_count': 0,
            'deleted_count': 0,
            'space_freed_mb': 0,
            'errors': []
        }

        # 1. 큰 로그 파일 즉시 압축 (100MB 이상)
        logger.info(f"📦 1단계: {MAX_SIZE_MB}MB 이상 로그 파일 압축")
        for log_file in log_dir.rglob('*.log'):
            try:
                size_mb = log_file.stat().st_size / (1024 * 1024)
                if size_mb >= MAX_SIZE_MB:
                    logger.info(f"  압축 중: {log_file.name} ({size_mb:.1f}MB)")
                    compress_file(log_file)
                    stats['compressed_count'] += 1
                    stats['space_freed_mb'] += size_mb * 0.7  # 약 70% 압축률
            except Exception as e:
                error_msg = f"파일 압축 실패 ({log_file.name}): {str(e)}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)

        # 2. 오래된 로그 파일 압축 (7일 이상)
        logger.info(f"📦 2단계: {COMPRESS_DAYS}일 이상 로그 파일 압축")
        cutoff_date = datetime.now() - timedelta(days=COMPRESS_DAYS)

        for log_file in log_dir.rglob('*.log'):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff_date:
                    size_mb = log_file.stat().st_size / (1024 * 1024)
                    logger.debug(f"  압축 중: {log_file.name} ({size_mb:.1f}MB)")
                    compress_file(log_file)
                    stats['compressed_count'] += 1
                    stats['space_freed_mb'] += size_mb * 0.7
            except Exception as e:
                error_msg = f"파일 압축 실패 ({log_file.name}): {str(e)}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)

        # 3. 오래된 압축 파일 삭제 (30일 이상)
        logger.info(f"🗑️  3단계: {DELETE_DAYS}일 이상 압축 파일 삭제")
        delete_cutoff = datetime.now() - timedelta(days=DELETE_DAYS)

        for gz_file in log_dir.rglob('*.log.gz'):
            try:
                mtime = datetime.fromtimestamp(gz_file.stat().st_mtime)
                if mtime < delete_cutoff:
                    size_mb = gz_file.stat().st_size / (1024 * 1024)
                    logger.debug(f"  삭제 중: {gz_file.name} ({size_mb:.1f}MB)")
                    gz_file.unlink()
                    stats['deleted_count'] += 1
                    stats['space_freed_mb'] += size_mb
            except Exception as e:
                error_msg = f"파일 삭제 실패 ({gz_file.name}): {str(e)}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)

        # 4. 빈 디렉토리 정리
        logger.info("🧹 4단계: 빈 디렉토리 정리")
        empty_dirs_removed = 0
        for dirpath in log_dir.rglob('*'):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                try:
                    dirpath.rmdir()
                    empty_dirs_removed += 1
                    logger.debug(f"  빈 디렉토리 삭제: {dirpath.name}")
                except Exception as e:
                    logger.warning(f"디렉토리 삭제 실패 ({dirpath.name}): {str(e)}")

        stats['empty_dirs_removed'] = empty_dirs_removed

        # 최종 결과
        logger.info(
            f"✅ 로그 정리 완료: "
            f"압축 {stats['compressed_count']}개, "
            f"삭제 {stats['deleted_count']}개, "
            f"절약 {stats['space_freed_mb']:.1f}MB"
        )

        # 에러 로거에도 기록
        error_logger.info(
            f"로그 정리 작업 완료 - "
            f"압축: {stats['compressed_count']}, "
            f"삭제: {stats['deleted_count']}, "
            f"절약: {stats['space_freed_mb']:.1f}MB"
        )

        stats['success'] = True
        return stats

    except Exception as e:
        error_msg = f"로그 정리 작업 중 오류 발생: {str(e)}"
        logger.error(error_msg, exc_info=True)
        error_logger.error(error_msg, exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'compressed_count': stats.get('compressed_count', 0),
            'deleted_count': stats.get('deleted_count', 0),
            'space_freed_mb': stats.get('space_freed_mb', 0)
        }


def compress_file(file_path: Path) -> None:
    """
    파일을 gzip으로 압축합니다.

    Args:
        file_path: 압축할 파일 경로
    """
    gz_path = Path(str(file_path) + '.gz')

    # 이미 압축 파일이 존재하면 건너뛰기
    if gz_path.exists():
        logger.debug(f"압축 파일이 이미 존재합니다: {gz_path.name}")
        return

    try:
        with open(file_path, 'rb') as f_in:
            with gzip.open(gz_path, 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)

        # 원본 파일 삭제
        file_path.unlink()
        logger.debug(f"압축 완료: {file_path.name} → {gz_path.name}")

    except Exception as e:
        logger.error(f"파일 압축 중 오류 ({file_path.name}): {str(e)}")
        # 압축 실패 시 생성된 gz 파일 삭제
        if gz_path.exists():
            try:
                gz_path.unlink()
            except:
                pass
        raise


@shared_task(name='maintenance_tasks.analyze_logs_summary')
def analyze_logs_summary(days: int = 1) -> Dict[str, Any]:
    """
    로그를 분석하여 요약 통계를 반환합니다.

    Args:
        days: 분석할 기간 (일)

    Returns:
        Dict[str, Any]: 로그 분석 요약
    """
    try:
        import json
        from collections import Counter
        from datetime import datetime, timedelta

        logger.info(f"📊 최근 {days}일 로그 분석 시작")

        base_dir = Path(__file__).parent.parent.parent
        log_dir = base_dir / 'logs'
        orders_log = log_dir / 'orders' / 'trading_orders.log'

        if not orders_log.exists():
            logger.warning("주문 로그 파일이 없습니다")
            return {'success': False, 'error': 'No order logs found'}

        cutoff_date = datetime.now() - timedelta(days=days)

        action_types = Counter()
        symbols = Counter()
        total_orders = 0
        errors = 0

        with open(orders_log, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log_entry = json.loads(line)
                    log_time = datetime.fromisoformat(log_entry.get('timestamp', ''))

                    if log_time >= cutoff_date:
                        total_orders += 1
                        action_types[log_entry.get('action_type', 'unknown')] += 1
                        symbols[log_entry.get('symbol', 'unknown')] += 1

                        if log_entry.get('level') == 'ERROR':
                            errors += 1

                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

        summary = {
            'success': True,
            'period_days': days,
            'total_orders': total_orders,
            'errors': errors,
            'top_actions': dict(action_types.most_common(5)),
            'top_symbols': dict(symbols.most_common(5)),
            'timestamp': datetime.now().isoformat()
        }

        logger.info(
            f"📊 로그 분석 완료: "
            f"총 주문 {total_orders}개, "
            f"에러 {errors}개"
        )

        return summary

    except Exception as e:
        error_msg = f"로그 분석 중 오류: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {'success': False, 'error': str(e)}

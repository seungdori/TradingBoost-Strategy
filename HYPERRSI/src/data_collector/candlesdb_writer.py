#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CandlesDB Writer
PostgreSQL에 캔들 데이터 저장 (dual-write with Redis)
"""

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg2
from psycopg2.extras import execute_values
from psycopg2.pool import SimpleConnectionPool

from shared.logging import get_logger

logger = get_logger(__name__)


class CandlesDBWriter:
    """CandlesDB PostgreSQL Writer with connection pooling"""

    def __init__(self):
        """Initialize connection pool"""
        self.pool: SimpleConnectionPool | None = None
        self.enabled = False

        # 모니터링 카운터
        self.success_count = 0
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.last_health_check: float = 0

        # 설정
        self.max_retries = 3
        self.retry_delay_base = 1  # 초
        self.health_check_interval = 60  # 60초마다 health check

        self._init_pool()

    def _init_pool(self):
        """Initialize PostgreSQL connection pool"""
        try:
            # Get config from environment variables directly
            candles_host = os.getenv("CANDLES_HOST", "158.247.251.34")
            candles_port = int(os.getenv("CANDLES_PORT", "5432"))
            candles_db = os.getenv("CANDLES_DATABASE", "candlesdb")
            candles_user = os.getenv("CANDLES_USER", "tradeuser")
            candles_password = os.getenv("CANDLES_PASSWORD", "SecurePassword123")

            self.pool = SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                host=candles_host,
                port=candles_port,
                database=candles_db,
                user=candles_user,
                password=candles_password,
            )
            self.enabled = True
            logger.info(
                f"✅ CandlesDB connection pool initialized: {candles_host}:{candles_port}/{candles_db}"
            )
        except Exception as e:
            logger.error(f"❌ Failed to initialize CandlesDB pool: {e}")
            self.enabled = False

    def get_connection(self):
        """Get connection from pool"""
        if not self.pool:
            raise Exception("Connection pool not initialized")
        return self.pool.getconn()

    def put_connection(self, conn):
        """Return connection to pool"""
        if self.pool:
            self.pool.putconn(conn)

    def close_pool(self):
        """Close all connections in pool"""
        if self.pool:
            self.pool.closeall()
            logger.info("CandlesDB connection pool closed")

    def health_check(self) -> bool:
        """
        DB 연결 상태 확인 및 자동 복구

        Returns:
            True if healthy, False otherwise
        """
        now = time.time()

        # 너무 자주 체크하지 않도록 throttling
        if now - self.last_health_check < self.health_check_interval:
            return self.enabled

        self.last_health_check = now

        # 이미 활성화된 경우 간단한 ping 테스트
        if self.enabled and self.pool:
            try:
                conn = self.get_connection()
                cur = conn.cursor()
                cur.execute("SELECT 1;")
                cur.close()
                self.put_connection(conn)
                logger.debug("✅ CandlesDB health check: OK")
                return True
            except Exception as e:
                logger.warning(f"⚠️ CandlesDB health check failed: {e}")
                self.enabled = False
                # Fall through to reconnect attempt

        # 비활성화된 경우 재연결 시도
        if not self.enabled:
            logger.info("🔄 Attempting to reconnect to CandlesDB...")
            return self.reconnect()

        return False

    def reconnect(self) -> bool:
        """
        CandlesDB 재연결 시도

        Returns:
            True if reconnection successful, False otherwise
        """
        try:
            # 기존 pool이 있으면 닫기
            if self.pool:
                try:
                    self.pool.closeall()
                except Exception:
                    pass
                self.pool = None

            # 새로운 pool 초기화
            self._init_pool()

            if self.enabled:
                logger.info("✅ CandlesDB reconnection successful!")
                return True
            else:
                logger.warning("❌ CandlesDB reconnection failed")
                return False

        except Exception as e:
            logger.error(f"❌ CandlesDB reconnection error: {e}")
            self.enabled = False
            return False

    def _retry_operation(self, operation, *args, **kwargs):
        """
        Retry operation with exponential backoff

        Args:
            operation: Function to retry
            *args, **kwargs: Arguments for the operation

        Returns:
            Operation result or None if all retries failed
        """
        for attempt in range(self.max_retries):
            try:
                result = operation(*args, **kwargs)
                if attempt > 0:
                    logger.info(f"✅ Retry successful on attempt {attempt + 1}")
                return result

            except psycopg2.OperationalError as e:
                # 연결 관련 오류 - 재시도 가능
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay_base * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"⚠️ DB operation failed (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"❌ DB operation failed after {self.max_retries} attempts: {e}")
                    raise

            except Exception as e:
                # 다른 오류 - 재시도하지 않음
                logger.error(f"❌ DB operation error (non-retryable): {e}")
                raise

        return None

    @staticmethod
    def normalize_symbol(okx_symbol: str) -> str:
        """
        OKX 심볼 형식을 CandlesDB 테이블명으로 변환

        Examples:
            BTC-USDT-SWAP → btc_usdt
            ETH-USDT-SWAP → eth_usdt
            SOL-USDT-SWAP → sol_usdt
        """
        # Remove -SWAP suffix and convert to lowercase
        parts = okx_symbol.replace("-SWAP", "").split("-")
        return "_".join(parts).lower()

    @staticmethod
    def convert_timeframe(minutes: int) -> str:
        """
        분 단위 timeframe을 문자열로 변환

        Examples:
            1 → "1m"
            3 → "3m"
            5 → "5m"
            15 → "15m"
            30 → "30m"
            60 → "1h"
            240 → "4h"
        """
        if minutes < 60:
            return f"{minutes}m"
        elif minutes == 60:
            return "1h"
        elif minutes == 240:
            return "4h"
        elif minutes == 1440:
            return "1d"
        else:
            # Fallback for other timeframes
            hours = minutes // 60
            return f"{hours}h"

    @staticmethod
    def convert_candle_to_db_row(candle: dict[str, Any], timeframe_str: str) -> tuple:
        """
        Redis 캔들 데이터를 DB row로 변환

        Args:
            candle: Redis candle dict
            timeframe_str: Timeframe string (e.g., "1m", "1h")

        Returns:
            Tuple of values for DB insert
        """
        # timestamp (초) → PostgreSQL timestamptz
        ts = candle["timestamp"]
        time = datetime.fromtimestamp(ts, tz=timezone.utc)

        # Convert to Decimal for precision
        return (
            time,
            timeframe_str,
            Decimal(str(candle["open"])),
            Decimal(str(candle["high"])),
            Decimal(str(candle["low"])),
            Decimal(str(candle["close"])),
            Decimal(str(candle["volume"])),
            Decimal(str(candle.get("rsi", 0))) if candle.get("rsi") else None,  # rsi14
            Decimal(str(candle.get("atr14", 0))) if candle.get("atr14") else None,  # atr
            Decimal(str(candle.get("ema7", 0))) if candle.get("ema7") else None,  # ema7
            Decimal(str(candle.get("sma20", 0))) if candle.get("sma20") else None,  # ma20
            int(candle.get("trend_state", 0)) if candle.get("trend_state") is not None else None,  # trend_state
            int(candle.get("auto_trend_state", 0)) if candle.get("auto_trend_state") is not None else None,  # auto_trend_state
        )

    def _do_upsert(self, table_name: str, timeframe_str: str, rows: list[tuple]) -> bool:
        """
        실제 upsert 작업 수행 (retry 가능)

        Args:
            table_name: Table name
            timeframe_str: Timeframe string
            rows: Rows to upsert

        Returns:
            Success flag
        """
        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            # Upsert query with ON CONFLICT UPDATE
            upsert_query = f"""
                INSERT INTO {table_name} (
                    time, timeframe, open, high, low, close, volume,
                    rsi14, atr, ema7, ma20, trend_state, auto_trend_state
                )
                VALUES %s
                ON CONFLICT (time, timeframe)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    rsi14 = EXCLUDED.rsi14,
                    atr = EXCLUDED.atr,
                    ema7 = EXCLUDED.ema7,
                    ma20 = EXCLUDED.ma20,
                    trend_state = EXCLUDED.trend_state,
                    auto_trend_state = EXCLUDED.auto_trend_state;
            """

            # Execute batch upsert
            execute_values(cur, upsert_query, rows)
            conn.commit()

            logger.debug(
                f"✅ CandlesDB upsert: {table_name} ({timeframe_str}) - {len(rows)} candles"
            )
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            raise  # Re-raise for retry logic

        finally:
            if conn:
                cur.close()
                self.put_connection(conn)

    def upsert_candles(
        self, symbol: str, timeframe_minutes: int, candles: list[dict[str, Any]]
    ) -> bool:
        """
        캔들 데이터를 DB에 upsert (insert or update) with retry

        Args:
            symbol: OKX symbol (e.g., "BTC-USDT-SWAP")
            timeframe_minutes: Timeframe in minutes
            candles: List of candle dicts

        Returns:
            Success flag
        """
        if not self.enabled or not candles:
            return False

        table_name = self.normalize_symbol(symbol)
        timeframe_str = self.convert_timeframe(timeframe_minutes)

        try:
            # Prepare rows for batch insert
            rows = []
            for candle in candles:
                try:
                    row = self.convert_candle_to_db_row(candle, timeframe_str)
                    rows.append(row)
                except Exception as e:
                    logger.warning(f"Failed to convert candle: {candle} - {e}")
                    continue

            if not rows:
                logger.warning(f"No valid rows to insert for {table_name}")
                return False

            # Retry upsert operation with exponential backoff
            self._retry_operation(self._do_upsert, table_name, timeframe_str, rows)

            # 성공 카운터 증가
            self.success_count += len(rows)
            logger.info(
                f"✅ CandlesDB upsert: {table_name} ({timeframe_str}) - {len(rows)} candles "
                f"(success: {self.success_count}, failures: {self.failure_count})"
            )
            return True

        except Exception as e:
            # 실패 카운터 증가
            self.failure_count += len(candles)
            self.last_failure_time = time.time()

            logger.error(
                f"❌ CandlesDB upsert failed: {table_name} ({timeframe_str}) - {e} "
                f"(success: {self.success_count}, failures: {self.failure_count})"
            )
            return False

    def upsert_single_candle(
        self, symbol: str, timeframe_minutes: int, candle: dict[str, Any]
    ) -> bool:
        """
        단일 캔들 upsert (wrapper)

        Args:
            symbol: OKX symbol
            timeframe_minutes: Timeframe in minutes
            candle: Single candle dict

        Returns:
            Success flag
        """
        return self.upsert_candles(symbol, timeframe_minutes, [candle])

    def get_stats(self) -> dict[str, Any]:
        """
        모니터링 통계 반환

        Returns:
            Dictionary with monitoring stats
        """
        stats = {
            "enabled": self.enabled,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.success_count + self.failure_count,
            "success_rate": (
                self.success_count / (self.success_count + self.failure_count) * 100
                if (self.success_count + self.failure_count) > 0
                else 0.0
            ),
            "last_failure_time": self.last_failure_time,
            "last_health_check": self.last_health_check,
        }
        return stats

    def log_stats(self):
        """통계 로그 출력"""
        stats = self.get_stats()
        logger.info(
            f"📊 CandlesDB Stats: "
            f"enabled={stats['enabled']}, "
            f"success={stats['success_count']}, "
            f"failure={stats['failure_count']}, "
            f"rate={stats['success_rate']:.1f}%"
        )


# Singleton instance
_candlesdb_writer: CandlesDBWriter | None = None


def get_candlesdb_writer() -> CandlesDBWriter:
    """Get singleton CandlesDB writer instance"""
    global _candlesdb_writer
    if _candlesdb_writer is None:
        _candlesdb_writer = CandlesDBWriter()
    return _candlesdb_writer


# Cleanup on module exit
import atexit


def cleanup_candlesdb():
    """Cleanup CandlesDB connections on exit"""
    global _candlesdb_writer
    if _candlesdb_writer:
        _candlesdb_writer.close_pool()


atexit.register(cleanup_candlesdb)

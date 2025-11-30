#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
okx_candles_* 테이블에서 CandlesDB로 데이터 마이그레이션

기존 BACKTEST 시스템의 okx_candles_* 테이블 데이터를
HYPERRSI/BACKTEST 공통 CandlesDB 테이블로 이전합니다.

사용법:
    python -m BACKTEST.scripts.migrate_okx_candles_to_candlesdb

환경 변수 필요:
    - TIMESCALE_* (기존 okx_candles 테이블 소스)
    - CANDLES_* (대상 CandlesDB)
"""

import asyncio
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger(__name__)

# 마이그레이션 대상 심볼 매핑
# okx_candles_* 테이블의 symbol 값 → candlesdb 테이블명
SYMBOL_MAPPING = {
    "BTC-USDT-SWAP": "btc_usdt",
    "ETH-USDT-SWAP": "eth_usdt",
    "SOL-USDT-SWAP": "sol_usdt",
    "XRP-USDT-SWAP": "xrp_usdt",
    "DOGE-USDT-SWAP": "doge_usdt",
    "ADA-USDT-SWAP": "ada_usdt",
    "AVAX-USDT-SWAP": "avax_usdt",
    "LINK-USDT-SWAP": "link_usdt",
    "DOT-USDT-SWAP": "dot_usdt",
    "MATIC-USDT-SWAP": "matic_usdt",
}

# 마이그레이션 대상 timeframe
TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]


class MigrationManager:
    """okx_candles → CandlesDB 마이그레이션 매니저"""

    def __init__(self):
        self.settings = get_settings()
        self._source_engine = None
        self._source_session_factory = None
        self._target_engine = None
        self._target_session_factory = None

    async def _init_source_connection(self):
        """소스 DB (TimescaleDB with okx_candles) 연결 초기화"""
        if self._source_engine is None:
            # Check if TIMESCALE_* settings exist
            timescale_host = getattr(self.settings, 'TIMESCALE_HOST', None)
            if not timescale_host:
                logger.warning("TIMESCALE_* 설정이 없습니다. DATABASE_URL을 사용합니다.")
                # Fallback to DATABASE_URL
                if hasattr(self.settings, 'DATABASE_URL') and self.settings.DATABASE_URL:
                    source_url = self.settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
                else:
                    raise ValueError("소스 DB 연결 정보가 없습니다. TIMESCALE_* 또는 DATABASE_URL을 설정하세요.")
            else:
                source_url = (
                    f"postgresql+asyncpg://{self.settings.TIMESCALE_USER}:{self.settings.TIMESCALE_PASSWORD}"
                    f"@{timescale_host}:{self.settings.TIMESCALE_PORT}/{self.settings.TIMESCALE_DATABASE}"
                )

            self._source_engine = create_async_engine(
                source_url,
                pool_size=3,
                max_overflow=5,
                pool_pre_ping=True,
                echo=False
            )
            self._source_session_factory = async_sessionmaker(
                self._source_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            logger.info(f"소스 DB 연결 초기화 완료")

    async def _init_target_connection(self):
        """대상 DB (CandlesDB) 연결 초기화"""
        if self._target_engine is None:
            target_url = (
                f"postgresql+asyncpg://{self.settings.CANDLES_USER}:{self.settings.CANDLES_PASSWORD}"
                f"@{self.settings.CANDLES_HOST}:{self.settings.CANDLES_PORT}/{self.settings.CANDLES_DATABASE}"
            )
            self._target_engine = create_async_engine(
                target_url,
                pool_size=3,
                max_overflow=5,
                pool_pre_ping=True,
                echo=False
            )
            self._target_session_factory = async_sessionmaker(
                self._target_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            logger.info(f"대상 DB (CandlesDB) 연결 초기화: {self.settings.CANDLES_HOST}:{self.settings.CANDLES_PORT}")

    async def close(self):
        """DB 연결 종료"""
        if self._source_engine:
            await self._source_engine.dispose()
        if self._target_engine:
            await self._target_engine.dispose()
        logger.info("DB 연결 종료")

    async def check_source_tables(self) -> dict:
        """소스 테이블 존재 여부 및 레코드 수 확인"""
        await self._init_source_connection()

        result = {}
        async with self._source_session_factory() as session:
            for tf in TIMEFRAMES:
                table_name = f"okx_candles_{tf}"
                try:
                    # Check if table exists
                    check_query = text(f"""
                        SELECT COUNT(*) as cnt FROM {table_name}
                    """)
                    res = await session.execute(check_query)
                    count = res.scalar()
                    result[table_name] = {"exists": True, "count": count}
                    logger.info(f"✅ {table_name}: {count:,} records")
                except Exception as e:
                    result[table_name] = {"exists": False, "error": str(e)}
                    logger.warning(f"❌ {table_name}: 테이블 없음 또는 오류 - {e}")

        return result

    async def check_target_tables(self) -> dict:
        """대상 테이블 존재 여부 확인"""
        await self._init_target_connection()

        result = {}
        async with self._target_session_factory() as session:
            for symbol, table_name in SYMBOL_MAPPING.items():
                try:
                    check_query = text(f"""
                        SELECT COUNT(*) as cnt FROM {table_name}
                    """)
                    res = await session.execute(check_query)
                    count = res.scalar()
                    result[table_name] = {"exists": True, "count": count}
                    logger.info(f"✅ {table_name}: {count:,} records")
                except Exception as e:
                    result[table_name] = {"exists": False, "error": str(e)}
                    logger.warning(f"❌ {table_name}: 테이블 없음 또는 오류 - {e}")

        return result

    async def migrate_timeframe(
        self,
        timeframe: str,
        symbol_filter: Optional[str] = None,
        dry_run: bool = False,
        batch_size: int = 1000
    ) -> dict:
        """
        특정 timeframe의 데이터를 마이그레이션

        Args:
            timeframe: 마이그레이션할 timeframe (e.g., "15m")
            symbol_filter: 특정 심볼만 마이그레이션 (None이면 전체)
            dry_run: True면 실제 INSERT 없이 카운트만
            batch_size: 배치 크기

        Returns:
            마이그레이션 결과 dict
        """
        await self._init_source_connection()
        await self._init_target_connection()

        source_table = f"okx_candles_{timeframe}"
        result = {"timeframe": timeframe, "migrated": 0, "skipped": 0, "errors": []}

        async with self._source_session_factory() as source_session:
            async with self._target_session_factory() as target_session:
                for okx_symbol, target_table in SYMBOL_MAPPING.items():
                    if symbol_filter and okx_symbol != symbol_filter:
                        continue

                    try:
                        # 소스에서 해당 심볼 데이터 조회
                        # okx_candles_* 테이블에 symbol 컬럼이 있는 경우
                        select_query = text(f"""
                            SELECT
                                time, open, high, low, close, volume,
                                rsi14, atr, ema7, ma20, trend_state,
                                COALESCE("CYCLE_Bull", cycle_bull) as cycle_bull,
                                COALESCE("CYCLE_Bear", cycle_bear) as cycle_bear,
                                COALESCE("BB_State", bb_state) as bb_state
                            FROM {source_table}
                            WHERE symbol = :symbol OR symbol IS NULL
                            ORDER BY time ASC
                        """)

                        try:
                            res = await source_session.execute(
                                select_query, {"symbol": okx_symbol}
                            )
                            rows = res.fetchall()
                        except Exception:
                            # symbol 컬럼이 없는 경우 - 테이블에 특정 심볼만 있다고 가정
                            select_query_no_symbol = text(f"""
                                SELECT
                                    time, open, high, low, close, volume,
                                    rsi14, atr, ema7, ma20, trend_state,
                                    COALESCE("CYCLE_Bull", cycle_bull, NULL) as cycle_bull,
                                    COALESCE("CYCLE_Bear", cycle_bear, NULL) as cycle_bear,
                                    COALESCE("BB_State", bb_state, NULL) as bb_state
                                FROM {source_table}
                                ORDER BY time ASC
                            """)
                            res = await source_session.execute(select_query_no_symbol)
                            rows = res.fetchall()

                        if not rows:
                            logger.info(f"  {okx_symbol} → {target_table}: 데이터 없음")
                            continue

                        logger.info(f"  {okx_symbol} → {target_table}: {len(rows):,} records 발견")

                        if dry_run:
                            result["migrated"] += len(rows)
                            continue

                        # 배치 단위로 INSERT
                        insert_query = text(f"""
                            INSERT INTO {target_table} (
                                time, timeframe, open, high, low, close, volume,
                                rsi14, atr, ema7, ma20, trend_state,
                                cycle_bull, cycle_bear, bb_state
                            ) VALUES (
                                :time, :timeframe, :open, :high, :low, :close, :volume,
                                :rsi14, :atr, :ema7, :ma20, :trend_state,
                                :cycle_bull, :cycle_bear, :bb_state
                            )
                            ON CONFLICT (time, timeframe) DO UPDATE SET
                                open = EXCLUDED.open,
                                high = EXCLUDED.high,
                                low = EXCLUDED.low,
                                close = EXCLUDED.close,
                                volume = EXCLUDED.volume,
                                rsi14 = COALESCE(EXCLUDED.rsi14, {target_table}.rsi14),
                                atr = COALESCE(EXCLUDED.atr, {target_table}.atr),
                                ema7 = COALESCE(EXCLUDED.ema7, {target_table}.ema7),
                                ma20 = COALESCE(EXCLUDED.ma20, {target_table}.ma20),
                                trend_state = COALESCE(EXCLUDED.trend_state, {target_table}.trend_state),
                                cycle_bull = COALESCE(EXCLUDED.cycle_bull, {target_table}.cycle_bull),
                                cycle_bear = COALESCE(EXCLUDED.cycle_bear, {target_table}.cycle_bear),
                                bb_state = COALESCE(EXCLUDED.bb_state, {target_table}.bb_state)
                        """)

                        total = len(rows)
                        for i in range(0, total, batch_size):
                            batch = rows[i:i + batch_size]

                            for row in batch:
                                await target_session.execute(insert_query, {
                                    'time': row.time,
                                    'timeframe': timeframe,
                                    'open': row.open,
                                    'high': row.high,
                                    'low': row.low,
                                    'close': row.close,
                                    'volume': row.volume,
                                    'rsi14': row.rsi14,
                                    'atr': row.atr,
                                    'ema7': row.ema7,
                                    'ma20': row.ma20,
                                    'trend_state': row.trend_state,
                                    'cycle_bull': row.cycle_bull,
                                    'cycle_bear': row.cycle_bear,
                                    'bb_state': row.bb_state
                                })

                            # Progress
                            processed = min(i + batch_size, total)
                            logger.info(f"    {processed}/{total} ({processed*100//total}%)")

                        await target_session.commit()
                        result["migrated"] += len(rows)
                        logger.info(f"  ✅ {okx_symbol} → {target_table}: {len(rows):,} records 마이그레이션 완료")

                    except Exception as e:
                        logger.error(f"  ❌ {okx_symbol} → {target_table}: 오류 - {e}")
                        result["errors"].append({"symbol": okx_symbol, "error": str(e)})
                        await target_session.rollback()

        return result

    async def migrate_all(
        self,
        timeframes: Optional[list] = None,
        dry_run: bool = False
    ) -> dict:
        """
        모든 timeframe 데이터 마이그레이션

        Args:
            timeframes: 마이그레이션할 timeframe 목록 (None이면 전체)
            dry_run: True면 실제 INSERT 없이 카운트만

        Returns:
            전체 마이그레이션 결과
        """
        if timeframes is None:
            timeframes = TIMEFRAMES

        logger.info(f"=== 마이그레이션 시작 (dry_run={dry_run}) ===")
        logger.info(f"대상 timeframes: {timeframes}")

        results = {}
        total_migrated = 0
        total_errors = 0

        for tf in timeframes:
            logger.info(f"\n--- {tf} 마이그레이션 ---")
            result = await self.migrate_timeframe(tf, dry_run=dry_run)
            results[tf] = result
            total_migrated += result["migrated"]
            total_errors += len(result["errors"])

        logger.info(f"\n=== 마이그레이션 완료 ===")
        logger.info(f"총 마이그레이션: {total_migrated:,} records")
        logger.info(f"총 오류: {total_errors} 건")

        return {
            "total_migrated": total_migrated,
            "total_errors": total_errors,
            "details": results
        }


async def main():
    """마이그레이션 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="okx_candles → CandlesDB 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 INSERT 없이 카운트만")
    parser.add_argument("--check-only", action="store_true", help="테이블 상태만 확인")
    parser.add_argument("--timeframe", "-t", type=str, help="특정 timeframe만 (e.g., 15m)")
    parser.add_argument("--symbol", "-s", type=str, help="특정 심볼만 (e.g., BTC-USDT-SWAP)")

    args = parser.parse_args()

    manager = MigrationManager()

    try:
        if args.check_only:
            logger.info("=== 소스 테이블 확인 ===")
            await manager.check_source_tables()

            logger.info("\n=== 대상 테이블 확인 ===")
            await manager.check_target_tables()
        else:
            timeframes = [args.timeframe] if args.timeframe else None

            if args.timeframe and args.symbol:
                # 특정 timeframe + symbol
                result = await manager.migrate_timeframe(
                    args.timeframe,
                    symbol_filter=args.symbol,
                    dry_run=args.dry_run
                )
                logger.info(f"결과: {result}")
            else:
                # 전체 또는 특정 timeframe 전체
                result = await manager.migrate_all(
                    timeframes=timeframes,
                    dry_run=args.dry_run
                )
                logger.info(f"결과: {result}")

    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())

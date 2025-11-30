#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CandlesDB의 auto_trend_state를 재계산하는 스크립트

수정된 add_auto_trend_state_to_candles 로직을 적용하여
모든 타임프레임의 auto_trend_state 값을 다시 계산합니다.

사용법:
    python recalculate_candlesdb_auto_trend_state.py --symbol BTC-USDT-SWAP --timeframe 1m --days 30
    python recalculate_candlesdb_auto_trend_state.py --symbol all --timeframe all --days 365

환경 변수 필요:
    - CANDLES_HOST, CANDLES_PORT, CANDLES_DATABASE, CANDLES_USER, CANDLES_PASSWORD
"""

import asyncio
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from shared.config import get_settings
from shared.logging import get_logger
from shared.indicators._all_indicators import add_auto_trend_state_to_candles

logger = get_logger(__name__)

# 지원 심볼 매핑 (OKX 심볼 → CandlesDB 테이블명)
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

# 타임프레임 매핑 (문자열 → 분)
TIMEFRAME_MAPPING = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def get_res_timeframe(current_minutes: int) -> str:
    """
    Pine Script Line 32: res_ 타임프레임 결정 (CYCLE용 MTF)

    res_ = ≤3분 → 15분, ≤30분 → 30분, <240분 → 60분, else → 480분
    """
    if current_minutes <= 3:
        return "15m"
    elif current_minutes <= 30:
        return "30m"
    elif current_minutes < 240:
        return "1h"
    else:
        return "8h"  # 480분 = 8시간


class CandlesDBRecalculator:
    """CandlesDB auto_trend_state 재계산 클래스"""

    def __init__(self):
        self.settings = get_settings()
        self._engine = None
        self._session_factory = None

    async def _init_connection(self):
        """DB 연결 초기화"""
        if self._engine is None:
            db_url = (
                f"postgresql+asyncpg://{self.settings.CANDLES_USER}:{self.settings.CANDLES_PASSWORD}"
                f"@{self.settings.CANDLES_HOST}:{self.settings.CANDLES_PORT}/{self.settings.CANDLES_DATABASE}"
            )
            self._engine = create_async_engine(
                db_url,
                pool_size=1,
                max_overflow=2,
                pool_pre_ping=True,
                pool_recycle=300,
                echo=False
            )
            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            logger.info(f"✅ CandlesDB 연결: {self.settings.CANDLES_HOST}:{self.settings.CANDLES_PORT}")

    async def close(self):
        """DB 연결 종료"""
        if self._engine:
            await self._engine.dispose()
            logger.info("DB 연결 종료")

    async def _get_candles(
        self,
        table_name: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> list[dict]:
        """
        CandlesDB에서 캔들 데이터 조회

        Args:
            table_name: 테이블명 (btc_usdt, eth_usdt 등)
            timeframe: 타임프레임 (1m, 15m 등)
            start_date: 시작 일시
            end_date: 종료 일시

        Returns:
            캔들 데이터 리스트 (dict 형태)
        """
        await self._init_connection()

        async with self._session_factory() as session:
            query = text(f"""
                SELECT
                    time, open, high, low, close, volume,
                    rsi14, atr, ema7, ma20, trend_state, auto_trend_state
                FROM {table_name}
                WHERE timeframe = :timeframe
                    AND time >= :start_date
                    AND time <= :end_date
                ORDER BY time ASC
            """)

            result = await session.execute(query, {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date
            })
            rows = result.fetchall()

            candles = []
            for row in rows:
                candles.append({
                    "timestamp": int(row.time.timestamp()),
                    "open": float(row.open) if row.open else 0,
                    "high": float(row.high) if row.high else 0,
                    "low": float(row.low) if row.low else 0,
                    "close": float(row.close) if row.close else 0,
                    "volume": float(row.volume) if row.volume else 0,
                    "time": row.time,  # datetime 객체 보존 (업데이트용)
                })

            return candles

    async def _update_auto_trend_state(
        self,
        table_name: str,
        timeframe: str,
        candles: list[dict],
        batch_size: int = 500
    ) -> int:
        """
        auto_trend_state 및 관련 지표 값들을 DB에 업데이트

        Args:
            table_name: 테이블명
            timeframe: 타임프레임
            candles: auto_trend_state가 계산된 캔들 리스트
            batch_size: 배치 크기

        Returns:
            업데이트된 행 수
        """
        await self._init_connection()

        # auto_trend_state만 업데이트 (cycle_bull, cycle_bear, bb_state 컬럼은 DB에 없음)
        update_query = text(f"""
            UPDATE {table_name}
            SET auto_trend_state = :auto_trend_state
            WHERE time = :time AND timeframe = :timeframe
        """)

        updated = 0
        async with self._session_factory() as session:
            total = len(candles)

            for i in range(0, total, batch_size):
                batch = candles[i:i + batch_size]

                for candle in batch:
                    await session.execute(update_query, {
                        "time": candle["time"],
                        "timeframe": timeframe,
                        "auto_trend_state": int(candle.get("auto_trend_state", 0)),
                    })
                    updated += 1

                await session.commit()

                progress = min(i + batch_size, total)
                logger.info(f"   진행: {progress}/{total} ({progress * 100 // total}%)")

        return updated

    async def recalculate(
        self,
        symbol: str,
        timeframe: str,
        days: int = 30,
        dry_run: bool = False
    ) -> dict:
        """
        특정 심볼/타임프레임의 auto_trend_state 재계산

        Args:
            symbol: OKX 심볼 (예: BTC-USDT-SWAP)
            timeframe: 타임프레임 (예: 1m)
            days: 재계산할 과거 데이터 일수
            dry_run: True면 실제 업데이트 없이 계산만

        Returns:
            결과 dict
        """
        await self._init_connection()

        table_name = SYMBOL_MAPPING.get(symbol)
        if not table_name:
            return {"success": False, "error": f"지원하지 않는 심볼: {symbol}"}

        timeframe_minutes = TIMEFRAME_MAPPING.get(timeframe)
        if not timeframe_minutes:
            return {"success": False, "error": f"지원하지 않는 타임프레임: {timeframe}"}

        logger.info("=" * 80)
        logger.info(f"🔄 auto_trend_state 재계산: {symbol} ({table_name}) {timeframe}")
        logger.info(f"   기간: 최근 {days}일, dry_run={dry_run}")
        logger.info("=" * 80)

        try:
            # 1. 기간 설정
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)

            # BB_State 계산을 위한 warm-up 기간 (pivot 배열 축적 필요)
            # - 100-bar MA 필요
            # - pivot array (50개) 축적에 최소 200-300바 필요
            warmup_days = 60  # 60일 추가 warm-up (15분봉 기준 약 5760개 캔들)
            warmup_start = start_date - timedelta(days=warmup_days)

            # 2. 현재 타임프레임 캔들 로드 (warm-up 포함)
            logger.info(f"\n1️⃣ {timeframe} 캔들 로드 중 (warm-up {warmup_days}일 포함)...")
            all_candles = await self._get_candles(table_name, timeframe, warmup_start, end_date)

            if not all_candles:
                return {"success": False, "error": f"데이터 없음: {table_name} {timeframe}"}

            logger.info(f"   ✅ {len(all_candles):,}개 캔들 로드 완료 (warm-up 포함)")

            # 3. CYCLE용 MTF 캔들 로드 (res_ 타임프레임)
            res_timeframe = get_res_timeframe(timeframe_minutes)
            logger.info(f"\n2️⃣ CYCLE MTF ({res_timeframe}) 캔들 로드 중...")

            # MTF 데이터도 warm-up 기간을 포함해야 함
            mtf_start = warmup_start - timedelta(days=30)  # 추가 30일 여유
            auto_trend_candles = await self._get_candles(table_name, res_timeframe, mtf_start, end_date)

            if not auto_trend_candles:
                logger.warning(f"   ⚠️ MTF 데이터 없음, 리샘플링 사용 예정")
                auto_trend_candles = None
            else:
                logger.info(f"   ✅ {len(auto_trend_candles):,}개 MTF 캔들 로드 완료")

            # 4. auto_trend_state 재계산 (warm-up 포함 전체 캔들에 대해)
            logger.info(f"\n3️⃣ auto_trend_state 재계산 중 (전체 {len(all_candles):,}개 캔들)...")

            result_candles = add_auto_trend_state_to_candles(
                candles=all_candles,  # warm-up 포함 전체 캔들 사용
                auto_trend_candles=auto_trend_candles if auto_trend_candles else [],
                current_timeframe_minutes=timeframe_minutes
            )

            logger.info(f"   ✅ {len(result_candles):,}개 캔들 계산 완료")

            # 5. 대상 기간 캔들만 필터링 (warm-up 기간 제외)
            target_candles = [
                c for c in result_candles
                if c["time"] >= start_date
            ]
            logger.info(f"   ✅ 대상 기간 캔들: {len(target_candles):,}개 (warm-up {len(result_candles) - len(target_candles):,}개 제외)")

            # 6. 통계 출력
            auto_states = [c.get("auto_trend_state", 0) for c in target_candles]
            count_2 = auto_states.count(2)
            count_0 = auto_states.count(0)
            count_minus2 = auto_states.count(-2)
            total = len(auto_states)

            logger.info(f"\n7️⃣ 재계산 통계 (대상 기간만):")
            logger.info(f"   - 강한 상승 (2): {count_2:,}개 ({count_2 * 100 / total:.1f}%)")
            logger.info(f"   - 중립 (0): {count_0:,}개 ({count_0 * 100 / total:.1f}%)")
            logger.info(f"   - 강한 하락 (-2): {count_minus2:,}개 ({count_minus2 * 100 / total:.1f}%)")

            # 8. 데이터베이스 업데이트 (대상 기간만)
            if dry_run:
                logger.info(f"\n8️⃣ [DRY RUN] 업데이트 건너뜀")
                updated = 0
            else:
                logger.info(f"\n8️⃣ 데이터베이스 업데이트 중 ({len(target_candles):,}개 캔들)...")
                updated = await self._update_auto_trend_state(
                    table_name, timeframe, target_candles  # warm-up 제외 대상 기간만
                )
                logger.info(f"   ✅ {updated:,}개 행 업데이트 완료")

            logger.info("\n" + "=" * 80)
            logger.info(f"✅ 재계산 완료: {symbol} {timeframe}")
            logger.info("=" * 80)

            return {
                "success": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "candles_processed": len(target_candles),  # 대상 기간 캔들 수
                "warmup_candles": len(result_candles) - len(target_candles),
                "rows_updated": updated,
                "stats": {
                    "strong_bull": count_2,
                    "neutral": count_0,
                    "strong_bear": count_minus2
                }
            }

        except Exception as e:
            logger.error(f"❌ 재계산 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="CandlesDB auto_trend_state 재계산",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 단일 심볼/타임프레임 재계산
  python recalculate_candlesdb_auto_trend_state.py --symbol BTC-USDT-SWAP --timeframe 1m --days 30

  # 모든 타임프레임 재계산
  python recalculate_candlesdb_auto_trend_state.py --symbol BTC-USDT-SWAP --timeframe all --days 365

  # 여러 심볼 재계산
  python recalculate_candlesdb_auto_trend_state.py --symbol all --timeframe 1m --days 30

  # 드라이런 (실제 업데이트 없이 확인)
  python recalculate_candlesdb_auto_trend_state.py --symbol BTC-USDT-SWAP --timeframe 1m --dry-run

지원 심볼: BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP, XRP-USDT-SWAP, DOGE-USDT-SWAP,
           ADA-USDT-SWAP, AVAX-USDT-SWAP, LINK-USDT-SWAP, DOT-USDT-SWAP, MATIC-USDT-SWAP

지원 타임프레임: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d
        """
    )
    parser.add_argument("--symbol", "-s", required=True,
                        help="심볼 (예: BTC-USDT-SWAP) 또는 'all'")
    parser.add_argument("--timeframe", "-t", required=True,
                        help="타임프레임 (예: 1m) 또는 'all'")
    parser.add_argument("--days", "-d", type=int, default=30,
                        help="재계산할 과거 데이터 일수 (기본: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 업데이트 없이 계산만 수행")

    args = parser.parse_args()

    recalculator = CandlesDBRecalculator()

    try:
        # 심볼 목록 결정
        if args.symbol.lower() == "all":
            symbols = list(SYMBOL_MAPPING.keys())
        else:
            symbols = [args.symbol]

        # 타임프레임 목록 결정
        if args.timeframe.lower() == "all":
            timeframes = list(TIMEFRAME_MAPPING.keys())
        else:
            timeframes = [args.timeframe]

        results = []
        total_updated = 0
        total_processed = 0

        for symbol in symbols:
            for timeframe in timeframes:
                result = await recalculator.recalculate(
                    symbol=symbol,
                    timeframe=timeframe,
                    days=args.days,
                    dry_run=args.dry_run
                )
                results.append(result)

                if result.get("success"):
                    total_updated += result.get("rows_updated", 0)
                    total_processed += result.get("candles_processed", 0)

        # 최종 요약
        logger.info("\n" + "=" * 80)
        logger.info("📊 전체 재계산 요약")
        logger.info("=" * 80)
        logger.info(f"   - 처리된 캔들: {total_processed:,}개")
        logger.info(f"   - 업데이트된 행: {total_updated:,}개")
        logger.info(f"   - 성공: {sum(1 for r in results if r.get('success'))}건")
        logger.info(f"   - 실패: {sum(1 for r in results if not r.get('success'))}건")
        logger.info("=" * 80)

    finally:
        await recalculator.close()


if __name__ == "__main__":
    asyncio.run(main())

"""
TimescaleDB의 모든 trend_state 값을 올바른 MTF 데이터로 다시 계산

목적: 리샘플링 대신 진짜 MTF 캔들 데이터를 사용하여 trend_state 재계산
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state
from sqlalchemy import text
from shared.logging import get_logger

logger = get_logger(__name__)


def parse_timeframe_to_minutes(timeframe: str) -> int:
    """타임프레임 문자열을 분 단위로 변환"""
    timeframe = timeframe.lower()
    if timeframe.endswith('m'):
        return int(timeframe[:-1])
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 1440
    else:
        raise ValueError(f"지원하지 않는 타임프레임 형식: {timeframe}")


async def recalculate_trend_state(symbol: str, timeframe: str, days: int = 30):
    """
    TimescaleDB의 trend_state를 올바른 MTF 데이터로 다시 계산하여 업데이트

    Args:
        symbol: 심볼 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (예: 1m, 5m, 15m)
        days: 재계산할 과거 데이터 일수
    """
    logger.info("=" * 100)
    logger.info(f"TimescaleDB trend_state 재계산: {symbol} {timeframe} (최근 {days}일)")
    logger.info("=" * 100)

    try:
        provider = TimescaleProvider()

        # 1. 데이터 기간 설정
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        logger.info(f"\n1️⃣ 데이터 로드 중...")
        logger.info(f"   기간: {start_date} ~ {end_date}")

        # 2. 현재 타임프레임 캔들 가져오기
        candles_raw = await provider.get_candles(symbol, timeframe, start_date, end_date)

        if not candles_raw:
            logger.error(f"❌ 데이터를 찾을 수 없습니다: {symbol} {timeframe}")
            return False

        logger.info(f"✅ {timeframe} 캔들: {len(candles_raw)}개")

        # Candle 객체를 dict로 변환
        candles = [{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles_raw]

        # 3. MTF 타임프레임 결정
        timeframe_minutes = parse_timeframe_to_minutes(timeframe)

        # Pine Script Line 32: res_ 결정
        if timeframe_minutes <= 3:
            res_minutes = 15
        elif timeframe_minutes <= 30:
            res_minutes = 30
        elif timeframe_minutes < 240:
            res_minutes = 60
        else:
            res_minutes = 480

        # Pine Script Line 355: bb_mtf 결정
        if timeframe_minutes <= 3:
            bb_mtf_minutes = 5
        elif timeframe_minutes <= 15:
            bb_mtf_minutes = 15
        else:
            bb_mtf_minutes = 60

        logger.info(f"\n2️⃣ MTF 데이터 로드 중...")
        logger.info(f"   CYCLE MTF: {res_minutes}분")
        logger.info(f"   BB_State MTF: {bb_mtf_minutes}분")
        logger.info(f"   CYCLE_2nd MTF: 240분")

        # 4. MTF 데이터 수집 (진짜 데이터!)
        res_tf = f"{res_minutes}m" if res_minutes < 60 else f"{res_minutes//60}h"
        bb_mtf_tf = f"{bb_mtf_minutes}m" if bb_mtf_minutes < 60 else f"{bb_mtf_minutes//60}h"

        candles_higher_tf_raw = await provider.get_candles(symbol, res_tf, start_date, end_date)
        candles_bb_mtf_raw = await provider.get_candles(symbol, bb_mtf_tf, start_date, end_date)
        candles_4h_raw = await provider.get_candles(symbol, "4h", start_date, end_date)

        # Candle 객체를 dict로 변환 (MTF)
        candles_higher_tf = [{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles_higher_tf_raw]

        candles_bb_mtf = [{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles_bb_mtf_raw]

        candles_4h = [{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles_4h_raw]

        logger.info(f"✅ {res_tf} 캔들: {len(candles_higher_tf)}개")
        logger.info(f"✅ {bb_mtf_tf} 캔들: {len(candles_bb_mtf)}개")
        logger.info(f"✅ 4h 캔들: {len(candles_4h)}개")

        # 5. trend_state 재계산 (진짜 MTF 데이터 전달!)
        logger.info(f"\n3️⃣ trend_state 재계산 중...")

        result_candles = compute_trend_state(
            candles=candles,
            use_longer_trend=False,
            use_custom_length=False,
            current_timeframe_minutes=timeframe_minutes,
            candles_higher_tf=candles_higher_tf,
            candles_bb_mtf=candles_bb_mtf,
            candles_4h=candles_4h,
            is_confirmed_only=True  # 백테스트 모드
        )

        logger.info(f"✅ trend_state 계산 완료: {len(result_candles)}개")

        # 6. 데이터베이스 업데이트
        logger.info(f"\n4️⃣ 데이터베이스 업데이트 중...")

        session = await provider._get_session()
        table_name = provider._get_table_name(timeframe)
        normalized_symbol = provider._normalize_symbol(symbol)

        update_query = f"""
            UPDATE {table_name}
            SET
                trend_state = :trend_state,
                cycle_bull = :cycle_bull,
                cycle_bear = :cycle_bear,
                bb_state = :bb_state
            WHERE symbol = :symbol
                AND time = :timestamp
        """

        batch_size = 1000
        total = len(result_candles)

        for i in range(0, total, batch_size):
            batch = result_candles[i:i + batch_size]

            for j, candle in enumerate(batch):
                await session.execute(text(update_query), {
                    'symbol': normalized_symbol,
                    'timestamp': candle['timestamp'],
                    'trend_state': candle.get('trend_state', 0),
                    'cycle_bull': candle.get('CYCLE_Bull', False),
                    'cycle_bear': candle.get('CYCLE_Bear', False),
                    'bb_state': candle.get('BB_State', 0)
                })

            await session.commit()

            progress = min(i + batch_size, total)
            logger.info(f"   진행: {progress}/{total} ({progress/total*100:.1f}%)")

        logger.info(f"✅ 데이터베이스 업데이트 완료")

        # 7. 통계 출력
        logger.info(f"\n5️⃣ 재계산 결과 통계:")

        trend_states = [c.get('trend_state', 0) for c in result_candles]
        logger.info(f"   - 강한 상승 (2): {trend_states.count(2)} 개 ({trend_states.count(2)/total*100:.1f}%)")
        logger.info(f"   - 중립 (0): {trend_states.count(0)} 개 ({trend_states.count(0)/total*100:.1f}%)")
        logger.info(f"   - 강한 하락 (-2): {trend_states.count(-2)} 개 ({trend_states.count(-2)/total*100:.1f}%)")

        logger.info("\n" + "=" * 100)
        logger.info("✅ **재계산 성공**: TimescaleDB trend_state가 올바른 MTF 데이터로 업데이트되었습니다!")
        logger.info("=" * 100)

        return True

    except Exception as e:
        logger.error(f"❌ 재계산 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("사용법: python recalculate_trend_state_db.py <symbol> <timeframe> [days]")
        print("예시: python recalculate_trend_state_db.py BTC-USDT-SWAP 1m 30")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    success = asyncio.run(recalculate_trend_state(symbol, timeframe, days))
    sys.exit(0 if success else 1)

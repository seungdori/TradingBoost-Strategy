"""
각 타임프레임의 BB_State를 계산해서 candle_history에 저장
"""

import asyncio
from datetime import datetime, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _calc_bb_state
from sqlalchemy import text


async def calculate_and_store_bb_state(symbol: str, timeframe: str, start_time: datetime = None, end_time: datetime = None):
    """
    특정 심볼/타임프레임의 BB_State 계산 후 DB 저장

    Args:
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (예: 1m, 5m, 15m)
        start_time: 시작 시간 (None이면 전체)
        end_time: 종료 시간 (None이면 현재까지)
    """

    print(f"=" * 100)
    print(f"BB_State 계산 및 저장: {symbol} {timeframe}")
    print(f"=" * 100)

    provider = TimescaleProvider()

    # 캔들 데이터 조회
    candles_raw = await provider.get_candles(symbol, timeframe, start_time, end_time)
    candles = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_raw
    ]

    print(f"\n📊 캔들 수: {len(candles)}개")

    if len(candles) == 0:
        print("⚠️  캔들 데이터가 없습니다.")
        return

    # BB_State 계산
    print(f"⚙️  BB_State 계산 중...")
    bb_state_list = _calc_bb_state(
        candles,
        length_bb=15,
        mult_bb=1.5,
        ma_length=100,
        is_confirmed_only=True
    )

    print(f"✅ BB_State 계산 완료: {len(bb_state_list)}개")

    # DB에 저장
    print(f"💾 DB에 저장 중...")

    from shared.database.session import create_async_engine
    from BACKTEST.config import get_shared_settings
    settings = get_shared_settings()

    # TimescaleDB URL 구성
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    update_count = 0
    batch_size = 1000

    async with engine.begin() as conn:
        for i in range(0, len(candles), batch_size):
            batch_candles = candles[i:i+batch_size]
            batch_bb_states = bb_state_list[i:i+batch_size]

            for candle, bb_state in zip(batch_candles, batch_bb_states):
                ts = candle['timestamp']

                await conn.execute(
                    text("""
                        UPDATE candle_history
                        SET bb_state = :bb_state
                        WHERE symbol = :symbol
                        AND timeframe = :timeframe
                        AND timestamp = :timestamp
                    """),
                    {
                        'bb_state': int(bb_state),
                        'symbol': symbol,
                        'timeframe': timeframe,
                        'timestamp': ts
                    }
                )
                update_count += 1

            print(f"   진행: {update_count}/{len(candles)} ({update_count/len(candles)*100:.1f}%)")

    print(f"✅ DB 저장 완료: {update_count}개 업데이트")

    # 검증: 일부 값 출력
    print(f"\n📊 검증 (최근 10개):")
    print(f"{'Timestamp':<20} {'Close':>10} {'BB_State':>10}")
    print("-" * 50)

    for i in range(max(0, len(candles) - 10), len(candles)):
        ts = candles[i]['timestamp']
        close = candles[i]['close']
        bb_state = bb_state_list[i]
        print(f"{str(ts)[:19]:<20} {close:>10.2f} {bb_state:>10}")


async def main():
    """메인 함수"""

    # 마이그레이션 실행
    print("🔧 마이그레이션 실행 중...")
    from shared.database.session import create_async_engine
    from BACKTEST.config import get_shared_settings
    settings = get_shared_settings()

    # TimescaleDB URL 구성
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        # 005 마이그레이션 읽기
        with open('/Users/seunghyun/TradingBoost-Strategy/migrations/backtest/005_add_bb_state_column.sql', 'r') as f:
            migration_sql = f.read()

        # 실행
        await conn.execute(text(migration_sql))
        print("✅ BB_State 컬럼 추가 완료")

    # BB_State 계산 및 저장
    symbol = "BTC-USDT-SWAP"

    # 각 타임프레임별로 계산
    timeframes = ["1m", "5m", "15m", "1h", "4h"]

    for tf in timeframes:
        await calculate_and_store_bb_state(symbol, tf)
        print("\n")


if __name__ == "__main__":
    asyncio.run(main())

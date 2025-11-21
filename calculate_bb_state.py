"""
각 타임프레임의 BB_State를 계산해서 candle_history에 저장
"""

import asyncio
from datetime import datetime
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _calc_bb_state
from sqlalchemy import text


async def calculate_and_store_bb_state(symbol: str, timeframe: str):
    """BB_State 계산 및 저장"""

    print(f"\n{'='*100}")
    print(f"BB_State 계산: {symbol} {timeframe}")
    print(f"{'='*100}")

    provider = TimescaleProvider()

    # 캔들 조회
    candles_raw = await provider.get_candles(symbol, timeframe, None, None)
    candles = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_raw
    ]

    print(f"📊 캔들: {len(candles)}개")

    if len(candles) == 0:
        print("⚠️  데이터 없음")
        return

    # BB_State 계산
    bb_state_list = _calc_bb_state(candles, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

    print(f"✅ 계산 완료: {len(bb_state_list)}개")

    # DB 저장
    from shared.database.session import create_async_engine
    from BACKTEST.config import get_shared_settings
    settings = get_shared_settings()

    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        for i, (candle, bb_state) in enumerate(zip(candles, bb_state_list)):
            await conn.execute(
                text("""
                    UPDATE candle_history
                    SET bb_state = :bb_state
                    WHERE symbol = :symbol AND timeframe = :timeframe AND timestamp = :timestamp
                """),
                {'bb_state': int(bb_state), 'symbol': symbol, 'timeframe': timeframe, 'timestamp': candle['timestamp']}
            )
            if (i + 1) % 1000 == 0:
                print(f"   {i+1}/{len(candles)}")

    print(f"✅ 저장 완료")


async def main():
    # 마이그레이션
    from shared.database.session import create_async_engine
    from BACKTEST.config import get_shared_settings
    settings = get_shared_settings()

    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        with open('/Users/seunghyun/TradingBoost-Strategy/migrations/backtest/005_add_bb_state_column.sql', 'r') as f:
            await conn.execute(text(f.read()))
        print("✅ BB_State 컬럼 추가")

    # 계산
    for tf in ["5m"]:  # 일단 5분봉만
        await calculate_and_store_bb_state("BTC-USDT-SWAP", tf)


if __name__ == "__main__":
    asyncio.run(main())

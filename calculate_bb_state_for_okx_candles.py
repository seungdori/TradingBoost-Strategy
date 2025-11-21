"""
각 타임프레임의 BB_State를 계산해서 okx_candles 테이블에 저장
"""

import asyncio
from datetime import datetime
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings
from shared.indicators._trend import _calc_bb_state


async def calculate_and_store_bb_state(symbol: str, timeframe: str, table_name: str):
    """BB_State 계산 및 저장"""

    print(f"\n{'='*100}")
    print(f"BB_State 계산: {symbol} {timeframe} ({table_name})")
    print(f"{'='*100}")

    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # 캔들 조회
    async with engine.begin() as conn:
        result = await conn.execute(
            text(f"""
                SELECT time, open, high, low, close, volume
                FROM {table_name}
                WHERE symbol = :symbol
                ORDER BY time ASC
            """),
            {'symbol': symbol}
        )

        rows = result.fetchall()

        if not rows:
            print("⚠️  데이터 없음")
            return

        candles = [
            {
                'timestamp': row[0],
                'open': float(row[1]),
                'high': float(row[2]),
                'low': float(row[3]),
                'close': float(row[4]),
                'volume': float(row[5])
            }
            for row in rows
        ]

        print(f"📊 캔들: {len(candles)}개")

        # BB_State 계산
        bb_state_list = _calc_bb_state(candles, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

        print(f"✅ 계산 완료: {len(bb_state_list)}개")

        # DB 저장
        update_count = 0
        for i, (candle, bb_state) in enumerate(zip(candles, bb_state_list)):
            await conn.execute(
                text(f"""
                    UPDATE {table_name}
                    SET bb_state = :bb_state
                    WHERE symbol = :symbol AND time = :time
                """),
                {'bb_state': int(bb_state), 'symbol': symbol, 'time': candle['timestamp']}
            )
            update_count += 1

            if (i + 1) % 1000 == 0:
                print(f"   {i+1}/{len(candles)} 저장 중...")

        print(f"✅ 저장 완료: {update_count}개")


async def main():
    # BTCUSDT 심볼로 각 타임프레임 계산
    timeframes = [
        ('1m', 'okx_candles_1m'),
        ('5m', 'okx_candles_5m'),
        ('15m', 'okx_candles_15m'),
        ('30m', 'okx_candles_30m'),
        ('1h', 'okx_candles_1h'),
        ('4h', 'okx_candles_4h'),
    ]

    for tf, table in timeframes:
        await calculate_and_store_bb_state("BTCUSDT", tf, table)


if __name__ == "__main__":
    asyncio.run(main())

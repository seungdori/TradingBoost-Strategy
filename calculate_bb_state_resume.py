"""
BB_State 계산을 이어서 진행 (이미 계산된 부분은 건너뜀)
"""

import asyncio
from datetime import datetime
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings
from shared.indicators._trend import _calc_bb_state


async def calculate_and_store_bb_state_resume(symbol: str, timeframe: str, table_name: str):
    """BB_State 계산 및 저장 (이미 계산된 부분 건너뜀)"""

    print(f"\n{'='*100}")
    print(f"BB_State 계산 재개: {symbol} {timeframe} ({table_name})")
    print(f"{'='*100}")

    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=5, max_overflow=0)

    # 전체 데이터 조회
    async with engine.begin() as conn:
        result = await conn.execute(
            text(f"""
                SELECT time, open, high, low, close, volume, bb_state
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

        candles = []
        already_calculated = []

        for row in rows:
            candle = {
                'timestamp': row[0],
                'open': float(row[1]),
                'high': float(row[2]),
                'low': float(row[3]),
                'close': float(row[4]),
                'volume': float(row[5])
            }
            candles.append(candle)

            # bb_state가 이미 계산되었는지 확인
            bb_state_existing = row[6]
            already_calculated.append(bb_state_existing is not None and bb_state_existing != 0)

        print(f"📊 전체 캔들: {len(candles)}개")
        print(f"✅ 이미 계산됨: {sum(already_calculated)}개")
        print(f"⏳ 남은 작업: {len(candles) - sum(already_calculated)}개")

    # BB_State 전체 계산 (forward fill을 위해 전체 계산 필요)
    bb_state_list = _calc_bb_state(candles, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)
    print(f"✅ 전체 계산 완료: {len(bb_state_list)}개")

    # 계산되지 않은 부분만 업데이트 (100개씩 배치)
    batch_size = 100
    total_updated = 0
    skipped = 0

    for i in range(0, len(candles), batch_size):
        batch_candles = candles[i:i+batch_size]
        batch_states = bb_state_list[i:i+batch_size]
        batch_existing = already_calculated[i:i+batch_size]

        # 이미 계산된 배치는 건너뜀
        updates = []
        for j, (candle, bb_state, is_calculated) in enumerate(zip(batch_candles, batch_states, batch_existing)):
            if not is_calculated:
                updates.append((candle, bb_state))

        if not updates:
            skipped += len(batch_candles)
            continue

        # 업데이트할 데이터가 있으면 저장
        try:
            async with engine.begin() as conn:
                for candle, bb_state in updates:
                    await conn.execute(
                        text(f"""
                            UPDATE {table_name}
                            SET bb_state = :bb_state
                            WHERE symbol = :symbol AND time = :time
                        """),
                        {'bb_state': int(bb_state), 'symbol': symbol, 'time': candle['timestamp']}
                    )

            total_updated += len(updates)
            skipped += len(batch_candles) - len(updates)

            if (total_updated + skipped) % 10000 == 0:
                print(f"   진행: {total_updated + skipped}/{len(candles)} (업데이트: {total_updated}, 건너뜀: {skipped})")

        except Exception as e:
            print(f"❌ 배치 {i}~{i+batch_size} 저장 실패: {e}")
            continue

    print(f"✅ 업데이트 완료: {total_updated}개")
    print(f"⏭️  건너뜀: {skipped}개")

    await engine.dispose()


async def main():
    # BTCUSDT 심볼로 각 타임프레임 계산
    timeframes = [
        ('1m', 'okx_candles_1m'),
        ('5m', 'okx_candles_5m'),
        ('15m', 'okx_candles_15m'),
    ]

    for tf, table in timeframes:
        await calculate_and_store_bb_state_resume("BTCUSDT", tf, table)


if __name__ == "__main__":
    asyncio.run(main())

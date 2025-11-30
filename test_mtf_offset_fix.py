"""
MTF 1-offset 제거 후 검증 테스트 스크립트

2025-11-28 14:00-20:00 구간에서 CYCLE_Bull 전환 시점 개선 확인
- 기대: 16:15-17:15 구간에서 auto_trend_state=0 (이전에는 2)
- 목표: 80.9% → 90%+ 일치율 개선
"""

import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from shared.config import get_settings
from shared.indicators._all_indicators import add_auto_trend_state_to_candles


async def test_mtf_offset_fix():
    """MTF offset 제거 후 테스트"""

    print("=" * 80)
    print("MTF 1-offset 제거 효과 검증 테스트")
    print("=" * 80)
    print()

    # DB 연결 초기화
    settings = get_settings()
    db_url = (
        f"postgresql+asyncpg://{settings.CANDLES_USER}:{settings.CANDLES_PASSWORD}"
        f"@{settings.CANDLES_HOST}:{settings.CANDLES_PORT}/{settings.CANDLES_DATABASE}"
    )
    engine = create_async_engine(
        db_url,
        pool_size=1,
        max_overflow=2,
        pool_pre_ping=True,
        echo=False
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with session_factory() as session:
        try:
            # 1. 테스트 구간 설정 (2025-11-28 14:00 - 20:00)
            test_start = datetime(2025, 11, 28, 14, 0, 0, tzinfo=timezone.utc)
            test_end = datetime(2025, 11, 28, 20, 0, 0, tzinfo=timezone.utc)

            print(f"📊 테스트 구간: {test_start} ~ {test_end}")
            print()

            # 2. 15m 데이터 조회 (warm-up 포함: 2일 = 약 200 캔들)
            warmup_start = test_start - timedelta(days=2)

            query_15m = text("""
                SELECT time, open, high, low, close, volume, trend_state, auto_trend_state
                FROM btc_usdt
                WHERE timeframe = '15m'
                  AND time >= :warmup_start
                  AND time <= :end
                ORDER BY time ASC
            """)
            result_15m = await session.execute(query_15m, {"warmup_start": warmup_start, "end": test_end})
            rows_15m = result_15m.fetchall()

            # dict 형식으로 변환
            candles_15m = []
            for row in rows_15m:
                candles_15m.append({
                    "timestamp": int(row.time.timestamp()),
                    "open": float(row.open) if row.open else 0,
                    "high": float(row.high) if row.high else 0,
                    "low": float(row.low) if row.low else 0,
                    "close": float(row.close) if row.close else 0,
                    "volume": float(row.volume) if row.volume else 0,
                    "time": row.time,
                    "trend_state": row.trend_state if row.trend_state is not None else -1,
                    "auto_trend_state_old": row.auto_trend_state if row.auto_trend_state is not None else -1,
                })

            print(f"✅ 15m 캔들: {len(candles_15m)}개 (warm-up 포함)")

            # 3. 30m 데이터 조회 (MTF용, 추가 warm-up)
            mtf_start = warmup_start - timedelta(days=3)

            query_30m = text("""
                SELECT time, open, high, low, close, volume
                FROM btc_usdt
                WHERE timeframe = '30m'
                  AND time >= :mtf_start
                  AND time <= :end
                ORDER BY time ASC
            """)
            result_30m = await session.execute(query_30m, {"mtf_start": mtf_start, "end": test_end})
            rows_30m = result_30m.fetchall()

            # dict 형식으로 변환
            candles_30m = []
            for row in rows_30m:
                candles_30m.append({
                    "timestamp": int(row.time.timestamp()),
                    "open": float(row.open) if row.open else 0,
                    "high": float(row.high) if row.high else 0,
                    "low": float(row.low) if row.low else 0,
                    "close": float(row.close) if row.close else 0,
                    "volume": float(row.volume) if row.volume else 0,
                    "time": row.time,
                })

            print(f"✅ 30m 캔들: {len(candles_30m)}개 (MTF용)")
            print()

            # 4. auto_trend_state 재계산
            print("🔄 auto_trend_state 재계산 중...")

            result_candles = add_auto_trend_state_to_candles(
                candles=candles_15m,
                auto_trend_candles=candles_30m,
                current_timeframe_minutes=15
            )

            print(f"✅ 계산 완료: {len(result_candles)}개 값")
            print()

            # 5. 결과 비교 (테스트 구간만)
            print("=" * 100)
            print(f"{'시간':<20} | {'Close':>11} | {'CYCLE_Bull':>11} | {'TV':>8} | {'Old':>8} | {'New':>8} | {'일치':<4}")
            print("=" * 100)

            match_count = 0
            total_count = 0
            critical_period_matches = 0
            critical_period_total = 0

            # 비교 대상 시간 범위 (16:15-17:15)
            critical_start = datetime(2025, 11, 28, 16, 15, 0, tzinfo=timezone.utc)
            critical_end = datetime(2025, 11, 28, 17, 15, 0, tzinfo=timezone.utc)

            for candle in result_candles:
                candle_time = candle["time"]

                # 테스트 구간 내 데이터만 출력
                if candle_time < test_start or candle_time > test_end:
                    continue

                tv_state = candle["trend_state"]
                old_state = candle["auto_trend_state_old"]
                new_state = candle.get("auto_trend_state", -1)

                # CYCLE_Bull 추출 (trend_state bit 1: 0=False, 2=True)
                cycle_bull = bool(tv_state & 2)

                match = "✓" if tv_state == new_state else "✗"
                if tv_state == new_state:
                    match_count += 1
                total_count += 1

                # 16:15-17:15 구간 추가 집계
                if critical_start <= candle_time <= critical_end:
                    if tv_state == new_state:
                        critical_period_matches += 1
                    critical_period_total += 1

                print(f"{candle_time} | {candle['close']:>11.2f} | {str(cycle_bull):>11} | "
                      f"{tv_state:>8} | {old_state:>8} | {new_state:>8} | {match:<4}")

            print("=" * 100)
            print()

            # 4. 통계 출력
            match_rate = (match_count / total_count * 100) if total_count > 0 else 0
            critical_rate = (critical_period_matches / critical_period_total * 100) if critical_period_total > 0 else 0

            print(f"📊 전체 구간 일치율: {match_count}/{total_count} = {match_rate:.1f}%")
            print(f"🎯 핵심 구간 일치율 (16:15-17:15): {critical_period_matches}/{critical_period_total} = {critical_rate:.1f}%")
            print()

            # 5. 개선 효과 분석
            print("=" * 80)
            print("💡 분석 결과")
            print("=" * 80)

            if match_rate >= 90:
                print(f"✅ 목표 달성! 일치율 {match_rate:.1f}% (목표: 90%)")
                print("✅ 1-offset 제거로 MTF 시간 정렬 문제 해결됨")
            elif match_rate > 80.9:
                print(f"⚠️  개선됨: 80.9% → {match_rate:.1f}%")
                print("⚠️  추가 분석 필요")
            else:
                print(f"❌ 개선 없음: {match_rate:.1f}% (이전: 80.9%)")
                print("❌ 다른 원인 존재 가능")

            print()

            if critical_rate < 100:
                print(f"⚠️  16:15-17:15 구간 일치율: {critical_rate:.1f}%")
                print("   → CYCLE_Bull 전환 시점 여전히 불일치")
            else:
                print(f"✅ 16:15-17:15 구간 완벽 일치! ({critical_rate:.1f}%)")
                print("   → CYCLE_Bull 전환 시점 문제 해결됨")

            print()

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()

    # Engine cleanup
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_mtf_offset_fix())

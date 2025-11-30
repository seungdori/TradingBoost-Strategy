"""
auto_trend_state와 trend_state 일치율 검증 스크립트

재계산 후 TradingView와의 일치율 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from shared.config import get_settings


async def verify_match_rate(symbol_table: str, timeframe: str, days: int = 365):
    """일치율 검증"""

    print("=" * 80)
    print(f"📊 {symbol_table.upper()} {timeframe} 일치율 검증 (최근 {days}일)")
    print("=" * 80)
    print()

    # DB 연결
    settings = get_settings()
    db_url = (
        f"postgresql+asyncpg://{settings.CANDLES_USER}:{settings.CANDLES_PASSWORD}"
        f"@{settings.CANDLES_HOST}:{settings.CANDLES_PORT}/{settings.CANDLES_DATABASE}"
    )
    engine = create_async_engine(db_url, pool_size=1, max_overflow=2, pool_pre_ping=True, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        try:
            # 기간 설정
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)

            # 데이터 조회
            query = text(f"""
                SELECT
                    time,
                    close,
                    trend_state,
                    auto_trend_state
                FROM {symbol_table}
                WHERE timeframe = :timeframe
                  AND time >= :start_date
                  AND time <= :end_date
                  AND trend_state IS NOT NULL
                  AND auto_trend_state IS NOT NULL
                ORDER BY time ASC
            """)

            result = await session.execute(query, {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date
            })
            rows = result.fetchall()

            if not rows:
                print("❌ 데이터 없음")
                return

            print(f"✅ 총 {len(rows):,}개 캔들 조회")
            print()

            # 일치율 계산
            match_count = 0
            total_count = len(rows)
            mismatch_samples = []

            for row in rows:
                tv_state = row.trend_state
                auto_state = row.auto_trend_state

                if tv_state == auto_state:
                    match_count += 1
                else:
                    # 불일치 샘플 최대 10개 수집
                    if len(mismatch_samples) < 10:
                        mismatch_samples.append({
                            "time": row.time,
                            "close": row.close,
                            "tv": tv_state,
                            "auto": auto_state
                        })

            match_rate = (match_count / total_count * 100) if total_count > 0 else 0

            # 결과 출력
            print("=" * 80)
            print("📊 일치율 통계")
            print("=" * 80)
            print(f"총 캔들 수: {total_count:,}개")
            print(f"일치: {match_count:,}개")
            print(f"불일치: {total_count - match_count:,}개")
            print(f"일치율: {match_rate:.2f}%")
            print()

            # 불일치 샘플 출력
            if mismatch_samples:
                print("=" * 80)
                print("⚠️ 불일치 샘플 (최대 10개)")
                print("=" * 80)
                print(f"{'시간':<20} | {'Close':>11} | {'TV':>5} | {'Auto':>5}")
                print("-" * 80)
                for sample in mismatch_samples:
                    print(f"{sample['time']} | {float(sample['close']):>11.2f} | "
                          f"{sample['tv']:>5} | {sample['auto']:>5}")
                print()

            # 평가
            print("=" * 80)
            print("💡 평가")
            print("=" * 80)
            if match_rate >= 95:
                print(f"✅ 우수: {match_rate:.2f}% (목표: 90% 이상)")
            elif match_rate >= 90:
                print(f"✅ 양호: {match_rate:.2f}% (목표: 90% 이상)")
            elif match_rate >= 80:
                print(f"⚠️  개선 필요: {match_rate:.2f}% (목표: 90% 이상)")
            else:
                print(f"❌ 불량: {match_rate:.2f}% (목표: 90% 이상)")
            print()

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()

    await engine.dispose()


async def main():
    """메인 함수"""
    # BTC 15m 검증
    await verify_match_rate("btc_usdt", "15m", days=365)

    # BTC 다른 타임프레임 검증
    print("\n" + "=" * 80 + "\n")
    for tf in ["1m", "3m", "5m", "30m", "1h", "4h", "1d"]:
        await verify_match_rate("btc_usdt", tf, days=30)
        print()


if __name__ == "__main__":
    asyncio.run(main())

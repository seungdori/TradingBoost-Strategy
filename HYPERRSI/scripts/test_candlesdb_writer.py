#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CandlesDB Writer 테스트
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from HYPERRSI.src.data_collector.candlesdb_writer import CandlesDBWriter


def test_connection():
    """Connection pool 초기화 테스트"""
    print("=" * 80)
    print("Test 1: Connection Pool Initialization")
    print("=" * 80)

    writer = CandlesDBWriter()
    print(f"Connection pool initialized: {writer.enabled}")
    print(f"Pool: {writer.pool}")
    print()

    return writer


def test_symbol_conversion():
    """Symbol 변환 테스트"""
    print("=" * 80)
    print("Test 2: Symbol Conversion")
    print("=" * 80)

    test_cases = [
        ("BTC-USDT-SWAP", "btc_usdt"),
        ("ETH-USDT-SWAP", "eth_usdt"),
        ("SOL-USDT-SWAP", "sol_usdt"),
    ]

    for okx_symbol, expected in test_cases:
        result = CandlesDBWriter.normalize_symbol(okx_symbol)
        status = "✅" if result == expected else "❌"
        print(f"{status} {okx_symbol} → {result} (expected: {expected})")

    print()


def test_timeframe_conversion():
    """Timeframe 변환 테스트"""
    print("=" * 80)
    print("Test 3: Timeframe Conversion")
    print("=" * 80)

    test_cases = [
        (1, "1m"),
        (3, "3m"),
        (5, "5m"),
        (15, "15m"),
        (30, "30m"),
        (60, "1h"),
        (240, "4h"),
        (1440, "1d"),
    ]

    for minutes, expected in test_cases:
        result = CandlesDBWriter.convert_timeframe(minutes)
        status = "✅" if result == expected else "❌"
        print(f"{status} {minutes} min → {result} (expected: {expected})")

    print()


def test_single_candle_upsert(writer):
    """단일 캔들 upsert 테스트"""
    print("=" * 80)
    print("Test 4: Single Candle Upsert")
    print("=" * 80)

    if not writer.enabled:
        print("❌ Writer not enabled, skipping test")
        print()
        return

    # 테스트용 캔들 데이터
    test_candle = {
        "timestamp": int(datetime.now(tz=timezone.utc).timestamp()),
        "open": 50000.0,
        "high": 50100.0,
        "low": 49900.0,
        "close": 50050.0,
        "volume": 100.5,
        "rsi": 55.5,
        "atr": 200.0,
        "ma7": 50000.0,
        "ma20": 49950.0,
    }

    symbol = "BTC-USDT-SWAP"
    timeframe = 60  # 1시간

    print(f"Upserting candle: {symbol} ({timeframe}m)")
    print(f"  Time: {datetime.fromtimestamp(test_candle['timestamp'], tz=timezone.utc)}")
    print(f"  OHLC: {test_candle['open']}/{test_candle['high']}/{test_candle['low']}/{test_candle['close']}")
    print(f"  Volume: {test_candle['volume']}")
    print(f"  RSI: {test_candle['rsi']}, ATR: {test_candle['atr']}")

    success = writer.upsert_single_candle(symbol, timeframe, test_candle)

    if success:
        print("✅ Upsert successful!")
    else:
        print("❌ Upsert failed")

    print()


def test_batch_upsert(writer):
    """배치 upsert 테스트"""
    print("=" * 80)
    print("Test 5: Batch Candle Upsert")
    print("=" * 80)

    if not writer.enabled:
        print("❌ Writer not enabled, skipping test")
        print()
        return

    # 테스트용 캔들 데이터 (3개)
    base_ts = int(datetime.now(tz=timezone.utc).timestamp())
    test_candles = []

    for i in range(3):
        ts = base_ts - (i * 3600)  # 1시간씩 과거로
        candle = {
            "timestamp": ts,
            "open": 50000.0 + (i * 100),
            "high": 50100.0 + (i * 100),
            "low": 49900.0 + (i * 100),
            "close": 50050.0 + (i * 100),
            "volume": 100.5 + (i * 10),
            "rsi": 55.5 - (i * 2),
            "atr": 200.0,
            "ma7": 50000.0 + (i * 50),
            "ma20": 49950.0 + (i * 50),
        }
        test_candles.append(candle)

    symbol = "ETH-USDT-SWAP"
    timeframe = 60  # 1시간

    print(f"Upserting {len(test_candles)} candles: {symbol} ({timeframe}m)")
    for i, candle in enumerate(test_candles, 1):
        print(f"  {i}. {datetime.fromtimestamp(candle['timestamp'], tz=timezone.utc)}: {candle['close']}")

    success = writer.upsert_candles(symbol, timeframe, test_candles)

    if success:
        print("✅ Batch upsert successful!")
    else:
        print("❌ Batch upsert failed")

    print()


def test_data_verification(writer):
    """데이터 저장 확인"""
    print("=" * 80)
    print("Test 6: Data Verification")
    print("=" * 80)

    if not writer.enabled:
        print("❌ Writer not enabled, skipping test")
        print()
        return

    try:
        conn = writer.get_connection()
        cur = conn.cursor()

        # BTC 데이터 확인
        cur.execute("""
            SELECT time, timeframe, close, rsi14, ema7, ma20
            FROM btc_usdt
            ORDER BY time DESC
            LIMIT 3;
        """)

        rows = cur.fetchall()

        print(f"BTC_USDT 최근 데이터 ({len(rows)}개):")
        for row in rows:
            time, tf, close, rsi, ema7, ma20 = row
            print(f"  {time} ({tf}): close={close}, rsi={rsi}, ema7={ema7}, ma20={ma20}")

        print()

        # ETH 데이터 확인
        cur.execute("""
            SELECT time, timeframe, close, rsi14, ema7, ma20
            FROM eth_usdt
            ORDER BY time DESC
            LIMIT 3;
        """)

        rows = cur.fetchall()

        print(f"ETH_USDT 최근 데이터 ({len(rows)}개):")
        for row in rows:
            time, tf, close, rsi, ema7, ma20 = row
            print(f"  {time} ({tf}): close={close}, rsi={rsi}, ema7={ema7}, ma20={ma20}")

        print("✅ Data verification successful!")

        cur.close()
        writer.put_connection(conn)

    except Exception as e:
        print(f"❌ Data verification failed: {e}")

    print()


def main():
    print("\n")
    print("🧪 CandlesDB Writer Test Suite")
    print("=" * 80)
    print()

    # Test 1: Connection
    writer = test_connection()

    # Test 2: Symbol conversion
    test_symbol_conversion()

    # Test 3: Timeframe conversion
    test_timeframe_conversion()

    # Test 4: Single candle upsert
    test_single_candle_upsert(writer)

    # Test 5: Batch upsert
    test_batch_upsert(writer)

    # Test 6: Data verification
    test_data_verification(writer)

    # Cleanup
    writer.close_pool()

    print("=" * 80)
    print("✅ All tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()

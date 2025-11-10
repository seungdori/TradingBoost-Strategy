#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CandlesDB Schema Checker
테이블 구조 확인 및 필요한 컬럼 검증
"""

import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from psycopg2.extras import RealDictCursor


def get_candlesdb_connection():
    """CandlesDB PostgreSQL 연결"""
    return psycopg2.connect(
        host=os.getenv("CANDLES_HOST", "158.247.251.34"),
        port=int(os.getenv("CANDLES_PORT", "5432")),
        database=os.getenv("CANDLES_DATABASE", "candlesdb"),
        user=os.getenv("CANDLES_USER", "tradeuser"),
        password=os.getenv("CANDLES_PASSWORD", "SecurePassword123")
    )


def get_table_columns(conn, table_name, schema="public"):
    """테이블의 컬럼 정보 조회"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """, (schema, table_name))
        return cur.fetchall()


def list_candle_tables(conn, schema="public"):
    """모든 캔들 테이블 목록 조회"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = %s
            ORDER BY tablename;
        """, (schema,))
        rows = cur.fetchall()
        return [row[0] for row in rows] if rows else []


def check_required_columns(existing_columns):
    """필요한 컬럼이 모두 있는지 확인"""
    # Redis에서 저장하는 데이터 구조 기반
    required_columns = {
        "timestamp": "timestamptz or bigint",
        "timeframe": "varchar or text",
        "open": "numeric or float8",
        "high": "numeric or float8",
        "low": "numeric or float8",
        "close": "numeric or float8",
        "volume": "numeric or float8",
        "rsi": "numeric or float8 (nullable)",
        "atr": "numeric or float8 (nullable)",
        "ma7": "numeric or float8 (nullable)",  # EMA
        "ma20": "numeric or float8 (nullable)",  # SMA
        "human_time": "varchar or text (nullable)",
        "human_time_kr": "varchar or text (nullable)",
    }

    existing_column_names = {col['column_name'].lower() for col in existing_columns}

    missing_columns = []
    for col_name, col_type in required_columns.items():
        if col_name not in existing_column_names:
            missing_columns.append((col_name, col_type))

    return missing_columns


def main():
    print("=" * 80)
    print("CandlesDB Schema Checker")
    print("=" * 80)

    try:
        conn = get_candlesdb_connection()
        print("✅ CandlesDB 연결 성공\n")

        # 1. 모든 캔들 테이블 목록 조회
        print("📊 캔들 테이블 목록:")
        print("-" * 80)
        tables = list_candle_tables(conn)
        for table in tables:
            print(f"  - {table}")
        print(f"\n총 {len(tables)}개 테이블 발견\n")

        # 2. btc_usdt 테이블 스키마 확인 (대표 테이블)
        if "btc_usdt" in tables:
            print("🔍 btc_usdt 테이블 스키마:")
            print("-" * 80)
            columns = get_table_columns(conn, "btc_usdt")

            for col in columns:
                nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
                default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
                print(f"  {col['column_name']:<20} {col['data_type']:<20} {nullable}{default}")

            print()

            # 3. 필요한 컬럼 체크
            print("✅ 필수 컬럼 확인:")
            print("-" * 80)
            missing = check_required_columns(columns)

            if not missing:
                print("  모든 필수 컬럼이 존재합니다! ✅")
            else:
                print("  ⚠️  누락된 컬럼:")
                for col_name, col_type in missing:
                    print(f"    - {col_name} ({col_type})")
                print(f"\n  총 {len(missing)}개 컬럼 추가 필요")
        else:
            print("⚠️  btc_usdt 테이블을 찾을 수 없습니다.")

        # 4. 샘플 데이터 확인
        if "btc_usdt" in tables:
            print("\n📈 샘플 데이터 (최근 5개):")
            print("-" * 80)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT time, timeframe, open, high, low, close, volume, rsi14, ema7, ma20, atr
                    FROM btc_usdt
                    ORDER BY time DESC
                    LIMIT 5;
                """)

                rows = cur.fetchall()
                if rows:
                    for row in rows:
                        print(f"  {dict(row)}")
                else:
                    print("  데이터 없음")

        conn.close()
        print("\n" + "=" * 80)
        print("Schema 확인 완료!")
        print("=" * 80)

    except psycopg2.Error as e:
        print(f"❌ 데이터베이스 오류: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

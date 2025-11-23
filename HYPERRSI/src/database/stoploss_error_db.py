"""
Stop Loss Error Database Management

스탑로스 관련 에러 로깅 시스템.
errordb의 stoploss_error_logs 테이블에 스탑로스 업데이트 중 발생하는 에러를 저장합니다.
"""

import asyncio
import traceback
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config.settings import settings
from shared.database.error_db_session import ErrorDatabaseConfig, init_error_db, get_error_db_transactional
from shared.logging import get_logger

logger = get_logger(__name__)


async def create_stoploss_error_table():
    """
    스탑로스 에러 전용 테이블 생성.

    테이블명: stoploss_error_logs
    위치: errordb database
    """
    engine = ErrorDatabaseConfig.get_engine()

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS stoploss_error_logs (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP NOT NULL DEFAULT NOW(),

        -- 사용자 정보
        user_id VARCHAR(255),
        telegram_id BIGINT,

        -- 에러 정보
        error_type VARCHAR(100) NOT NULL,
        severity VARCHAR(20) NOT NULL DEFAULT 'ERROR',
        error_message TEXT NOT NULL,
        error_details JSONB,

        -- 발생 위치
        module VARCHAR(255),
        function_name VARCHAR(255),
        file_path VARCHAR(512),
        line_number INTEGER,
        traceback TEXT,

        -- 거래/포지션 관련 정보
        symbol VARCHAR(50),
        side VARCHAR(10),
        order_side VARCHAR(10),

        -- 스탑로스 관련 정보
        new_sl_price DECIMAL(20, 8),
        current_price DECIMAL(20, 8),
        position_qty DECIMAL(20, 8),
        position_side VARCHAR(10),
        algo_type VARCHAR(20),
        order_type VARCHAR(50),

        -- 포지션 및 주문 정보
        position_info JSONB,
        old_sl_data JSONB,

        -- 실패 원인 분석
        failure_reason VARCHAR(255),
        should_close_at_market BOOLEAN,

        -- 메타데이터
        metadata JSONB,
        request_id VARCHAR(100),

        -- 해결 여부
        resolved BOOLEAN NOT NULL DEFAULT FALSE,
        resolved_at TIMESTAMP,
        resolved_by VARCHAR(255),
        resolution_notes TEXT
    );
    """

    # 인덱스 생성
    create_indexes_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_timestamp ON stoploss_error_logs(timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_user_id ON stoploss_error_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_telegram_id ON stoploss_error_logs(telegram_id)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_error_type ON stoploss_error_logs(error_type)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_severity ON stoploss_error_logs(severity)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_symbol ON stoploss_error_logs(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_resolved ON stoploss_error_logs(resolved)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_request_id ON stoploss_error_logs(request_id)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_timestamp_user ON stoploss_error_logs(timestamp DESC, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_timestamp_severity ON stoploss_error_logs(timestamp DESC, severity)",
        "CREATE INDEX IF NOT EXISTS idx_stoploss_errors_failure_reason ON stoploss_error_logs(failure_reason)",
    ]

    try:
        async with engine.begin() as conn:
            # 테이블 생성
            await conn.execute(text(create_table_sql))
            logger.info("✅ stoploss_error_logs table created (or already exists)")

            # 인덱스 생성
            for idx_sql in create_indexes_sqls:
                await conn.execute(text(idx_sql))
            logger.info(f"✅ stoploss_error_logs indexes created ({len(create_indexes_sqls)} indexes)")

        print("✅ Stop Loss error table initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to create stoploss_error_logs table: {e}")
        print(f"❌ Failed to initialize Stop Loss error table: {e}")
        return False


async def log_stoploss_error(
    error: Exception,
    error_type: str,
    user_id: Optional[str] = None,
    telegram_id: Optional[int] = None,
    severity: str = "ERROR",
    module: Optional[str] = None,
    function_name: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    order_side: Optional[str] = None,
    new_sl_price: Optional[float] = None,
    current_price: Optional[float] = None,
    position_qty: Optional[float] = None,
    position_side: Optional[str] = None,
    algo_type: Optional[str] = None,
    order_type: Optional[str] = None,
    position_info: Optional[Dict[str, Any]] = None,
    old_sl_data: Optional[Dict[str, Any]] = None,
    failure_reason: Optional[str] = None,
    should_close_at_market: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Optional[int]:
    """
    스탑로스 에러를 errordb의 stoploss_error_logs 테이블에 기록.

    Args:
        error: Exception 객체
        error_type: 에러 타입 (예: "StopLossUpdateError", "OrderCreationError", "ValidationError")
        user_id: 사용자 ID
        telegram_id: 텔레그램 ID
        severity: 심각도 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        module: 에러 발생 모듈
        function_name: 에러 발생 함수명
        symbol: 거래 심볼
        side: 포지션 방향
        order_side: 주문 방향
        new_sl_price: 새로운 SL 가격
        current_price: 현재가
        position_qty: 포지션 수량
        position_side: 포지션 사이드
        algo_type: 알고 타입
        order_type: 주문 타입
        position_info: 포지션 정보 (dict)
        old_sl_data: 기존 SL 데이터 (dict)
        failure_reason: 실패 원인
        should_close_at_market: 시장가 청산 여부
        metadata: 추가 메타데이터 (dict)
        request_id: 요청 ID

    Returns:
        int: 생성된 에러 로그 ID (실패 시 None)
    """
    try:
        # 트레이스백 정보 추출
        tb = traceback.extract_tb(error.__traceback__)
        last_frame = tb[-1] if tb else None

        file_path = last_frame.filename if last_frame else None
        line_number = last_frame.lineno if last_frame else None
        traceback_text = ''.join(traceback.format_exception(type(error), error, error.__traceback__))

        # SQL INSERT
        insert_sql = text("""
            INSERT INTO stoploss_error_logs (
                timestamp, user_id, telegram_id, error_type, severity,
                error_message, error_details, module, function_name,
                file_path, line_number, traceback,
                symbol, side, order_side,
                new_sl_price, current_price, position_qty, position_side,
                algo_type, order_type,
                position_info, old_sl_data,
                failure_reason, should_close_at_market,
                metadata, request_id
            ) VALUES (
                NOW(), :user_id, :telegram_id, :error_type, :severity,
                :error_message, CAST(:error_details AS jsonb), :module, :function_name,
                :file_path, :line_number, :traceback,
                :symbol, :side, :order_side,
                :new_sl_price, :current_price, :position_qty, :position_side,
                :algo_type, :order_type,
                CAST(:position_info AS jsonb), CAST(:old_sl_data AS jsonb),
                :failure_reason, :should_close_at_market,
                CAST(:metadata AS jsonb), :request_id
            ) RETURNING id
        """)

        import json
        from decimal import Decimal

        # Decimal을 포함한 dict를 JSON으로 안전하게 변환하는 헬퍼 함수
        def safe_json_dumps(obj):
            """Decimal, datetime 등을 포함한 dict를 JSON으로 안전하게 변환"""
            if obj is None:
                return None

            def default_handler(o):
                if isinstance(o, Decimal):
                    return float(o)
                elif hasattr(o, 'isoformat'):  # datetime objects
                    return o.isoformat()
                else:
                    return str(o)

            try:
                return json.dumps(obj, default=default_handler)
            except Exception as e:
                # JSON 변환 실패 시 문자열로 변환
                logger.warning(f"JSON serialization failed, converting to string: {e}")
                return str(obj)

        params = {
            "user_id": user_id,
            "telegram_id": telegram_id,
            "error_type": error_type,
            "severity": severity,
            "error_message": str(error),
            "error_details": safe_json_dumps({
                "error_class": error.__class__.__name__,
                "error_args": str(error.args) if hasattr(error, 'args') else None,
            }),
            "module": module,
            "function_name": function_name,
            "file_path": file_path,
            "line_number": line_number,
            "traceback": traceback_text,
            "symbol": symbol,
            "side": side,
            "order_side": order_side,
            "new_sl_price": new_sl_price,
            "current_price": current_price,
            "position_qty": position_qty,
            "position_side": position_side,
            "algo_type": algo_type,
            "order_type": order_type,
            "position_info": safe_json_dumps(position_info),
            "old_sl_data": safe_json_dumps(old_sl_data),
            "failure_reason": failure_reason,
            "should_close_at_market": should_close_at_market,
            "metadata": safe_json_dumps(metadata),
            "request_id": request_id,
        }

        engine = ErrorDatabaseConfig.get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(insert_sql, params)
            error_id = result.scalar()

        logger.info(f"✅ Stop Loss error logged to errordb: ID={error_id}, type={error_type}, symbol={symbol}")
        return error_id

    except Exception as e:
        # 에러 로깅 실패 시 파일 로그만 남김
        logger.error(f"❌ Failed to log stop loss error to errordb: {e}")
        logger.error(f"Original error: {error}")
        return None


async def get_recent_stoploss_errors(
    limit: int = 100,
    user_id: Optional[str] = None,
    telegram_id: Optional[int] = None,
    severity: Optional[str] = None,
    error_type: Optional[str] = None,
    symbol: Optional[str] = None,
    resolved: Optional[bool] = None,
    since: Optional[datetime] = None,
) -> list:
    """
    최근 스탑로스 에러 조회.

    Args:
        limit: 조회 개수
        user_id: 특정 사용자 에러만 조회
        telegram_id: 텔레그램 ID로 조회
        severity: 특정 심각도만 조회
        error_type: 에러 타입으로 조회
        symbol: 심볼로 조회
        resolved: 해결 여부 필터
        since: 시작 시간 (이 시간 이후의 에러만 조회)

    Returns:
        list: 에러 로그 리스트 (dict)
    """
    try:
        conditions = []
        params = {"limit": limit}

        if since:
            conditions.append("timestamp >= :since")
            params["since"] = since

        if user_id:
            conditions.append("user_id = :user_id")
            params["user_id"] = user_id

        if telegram_id:
            conditions.append("telegram_id = :telegram_id")
            params["telegram_id"] = telegram_id

        if severity:
            conditions.append("severity = :severity")
            params["severity"] = severity

        if error_type:
            conditions.append("error_type = :error_type")
            params["error_type"] = error_type

        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol

        if resolved is not None:
            conditions.append("resolved = :resolved")
            params["resolved"] = resolved

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query_sql = text(f"""
            SELECT id, timestamp, user_id, telegram_id, error_type, severity,
                   error_message, error_details, module, function_name,
                   file_path, line_number, traceback,
                   symbol, side, order_side,
                   new_sl_price, current_price, position_qty, position_side,
                   algo_type, order_type,
                   position_info, old_sl_data,
                   failure_reason, should_close_at_market,
                   metadata, request_id,
                   resolved, resolved_at, resolved_by, resolution_notes
            FROM stoploss_error_logs
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT :limit
        """)

        engine = ErrorDatabaseConfig.get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(query_sql, params)
            rows = result.fetchall()

        errors = []
        for row in rows:
            errors.append({
                "id": row[0],
                "timestamp": row[1],
                "user_id": row[2],
                "telegram_id": row[3],
                "error_type": row[4],
                "severity": row[5],
                "error_message": row[6],
                "error_details": row[7],
                "module": row[8],
                "function_name": row[9],
                "file_path": row[10],
                "line_number": row[11],
                "traceback": row[12],
                "symbol": row[13],
                "side": row[14],
                "order_side": row[15],
                "new_sl_price": row[16],
                "current_price": row[17],
                "position_qty": row[18],
                "position_side": row[19],
                "algo_type": row[20],
                "order_type": row[21],
                "position_info": row[22],
                "old_sl_data": row[23],
                "failure_reason": row[24],
                "should_close_at_market": row[25],
                "metadata": row[26],
                "request_id": row[27],
                "resolved": row[28],
                "resolved_at": row[29],
                "resolved_by": row[30],
                "resolution_notes": row[31],
            })

        return errors

    except Exception as e:
        logger.error(f"Failed to get recent stop loss errors: {e}")
        return []


async def initialize_stoploss_error_db():
    """
    스탑로스 에러 DB 초기화 (서버 시작 시 호출).
    """
    try:
        # Error DB 연결 확인
        await init_error_db()

        # 스탑로스 에러 테이블 생성
        success = await create_stoploss_error_table()

        if success:
            logger.info("Stop Loss error database initialization completed")
            print("\n" + "="*60)
            print("✅ Stop Loss Error Database Initialization Complete")
            print("="*60)
            print(f"Database: errordb (separate pool)")
            print(f"Table: stoploss_error_logs")
            print("="*60 + "\n")
        else:
            raise Exception("Failed to create stoploss_error_logs table")

    except Exception as e:
        logger.error(f"Stop Loss error database initialization failed: {e}")
        print(f"\n❌ Stop Loss Error Database Initialization Failed: {e}")
        # 에러 DB 실패해도 서버는 계속 시작
        pass


if __name__ == "__main__":
    """
    스크립트로 직접 실행 시 스탑로스 에러 DB를 초기화합니다.

    Usage:
        python HYPERRSI/src/database/stoploss_error_db.py
    """
    async def main():
        try:
            await initialize_stoploss_error_db()

            # 테스트 에러 로깅
            try:
                raise ValueError("Test error for Stop Loss error logging")
            except Exception as e:
                await log_stoploss_error(
                    error=e,
                    error_type="TEST_ERROR",
                    user_id="test_user",
                    telegram_id=123456789,
                    severity="INFO",
                    module="stoploss_error_db",
                    function_name="main",
                    symbol="ETH-USDT-SWAP",
                    side="long",
                    order_side="buy",
                    new_sl_price=2500.0,
                    current_price=2550.0,
                    position_qty=1.0,
                    position_side="long",
                    failure_reason="Test failure",
                    metadata={"test": True}
                )

            # 최근 에러 조회
            recent_errors = await get_recent_stoploss_errors(limit=5)
            print(f"\n최근 스탑로스 에러 {len(recent_errors)}개:")
            for err in recent_errors:
                print(f"  - [{err['severity']}] {err['error_type']}: {err['error_message'][:50]}")

            from shared.database.error_db_session import close_error_db
            await close_error_db()

        except Exception as e:
            print(f"Test failed: {e}")

    asyncio.run(main())

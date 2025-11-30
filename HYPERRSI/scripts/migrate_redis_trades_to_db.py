#!/usr/bin/env python3
"""
Redis 거래 히스토리 → PostgreSQL 마이그레이션 스크립트

Redis의 user:*:history 데이터를 hyperrsi_trades 테이블로 마이그레이션합니다.

Usage:
    cd HYPERRSI
    python scripts/migrate_redis_trades_to_db.py [--dry-run] [--user USER_ID]

Options:
    --dry-run   : 실제 DB 저장 없이 마이그레이션 시뮬레이션
    --user      : 특정 사용자만 마이그레이션 (예: --user 586156710277369942)
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

# 프로젝트 루트 경로 설정
sys.path.insert(0, "/Users/seunghyun/TradingBoost-Strategy")

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger(__name__)


async def get_redis_client():
    """Redis 클라이언트 생성"""
    settings = get_settings()
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )


async def get_all_user_history_keys(redis_client) -> List[str]:
    """모든 user:*:history 키 조회"""
    keys = await redis_client.keys("user:*:history")
    return keys


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """타임스탬프 문자열을 datetime으로 변환"""
    if not ts_str:
        return None

    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S.%f',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue

    logger.warning(f"타임스탬프 파싱 실패: {ts_str}")
    return None


def map_close_type(redis_close_type: str) -> str:
    """Redis close_type을 DB close_type으로 매핑"""
    mapping = {
        "manual": "manual",
        "Manual": "manual",
        "take_profit": "take_profit",
        "take_profit_1": "take_profit_1",
        "take_profit_2": "take_profit_2",
        "take_profit_3": "take_profit_3",
        "tp1": "take_profit_1",
        "tp2": "take_profit_2",
        "tp3": "take_profit_3",
        "TP1": "take_profit_1",
        "TP2": "take_profit_2",
        "TP3": "take_profit_3",
        "stop_loss": "stop_loss",
        "sl": "stop_loss",
        "SL": "stop_loss",
        "break_even": "break_even",
        "trailing_stop": "trailing_stop",
        "trend_reversal": "trend_reversal",
        "signal": "signal",
    }
    return mapping.get(redis_close_type, "manual")


def parse_trade_record(trade_json: str, okx_uid: str) -> Optional[Dict[str, Any]]:
    """Redis 거래 기록을 DB 형식으로 변환"""
    try:
        trade = json.loads(trade_json)

        # 필수 필드 확인
        if trade.get("status") != "closed":
            return None

        # 타임스탬프 파싱
        entry_time = parse_timestamp(trade.get("timestamp", ""))
        exit_time = parse_timestamp(trade.get("exit_timestamp", ""))

        if not exit_time:
            exit_time = entry_time or datetime.now()
        if not entry_time:
            entry_time = exit_time

        # 수량 및 가격
        entry_price = float(trade.get("entry_price", 0) or 0)
        exit_price = float(trade.get("exit_price", 0) or 0)
        size = float(trade.get("size", 0) or 0)
        initial_size = float(trade.get("initial_size", size) or size)

        if entry_price <= 0 or exit_price <= 0 or size <= 0:
            logger.warning(f"유효하지 않은 거래 데이터: price={entry_price}/{exit_price}, size={size}")
            return None

        # PnL
        pnl = float(trade.get("pnl", 0) or 0)
        pnl_percent = float(trade.get("pnl_percent", 0) or 0)

        # 수수료
        fee_data = trade.get("fee", {})
        if isinstance(fee_data, dict):
            total_fee = float(fee_data.get("cost", 0) or 0)
        else:
            total_fee = float(fee_data or 0)

        # 레버리지
        leverage = int(float(trade.get("leverage", 1) or 1))

        # close_type 매핑
        close_type = map_close_type(trade.get("close_type", "manual"))

        # side 검증
        side = trade.get("side", "").lower()
        if side not in ["long", "short"]:
            logger.warning(f"유효하지 않은 side: {side}")
            return None

        return {
            "okx_uid": okx_uid,
            "symbol": trade.get("symbol", "UNKNOWN"),
            "side": side,
            "is_hedge": False,
            "entry_time": entry_time,
            "entry_price": entry_price,
            "entry_size": initial_size,
            "entry_value": entry_price * initial_size,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "exit_size": size,
            "exit_value": exit_price * size,
            "close_type": close_type,
            "leverage": leverage,
            "dca_count": 0,  # Redis에 DCA 정보가 없음
            "avg_entry_price": entry_price,  # 단일 진입으로 가정
            "realized_pnl": pnl,
            "realized_pnl_percent": pnl_percent,
            "entry_fee": total_fee / 2,  # 수수료 반반 분배 (추정)
            "exit_fee": total_fee / 2,
            "entry_order_id": None,
            "exit_order_id": trade.get("order_id"),
            "extra_data": {
                "source": "redis_migration",
                "original_data": {
                    "contracts_amount": trade.get("contracts_amount"),
                    "last_filled_price": trade.get("last_filled_price"),
                    "close_comment": trade.get("close_comment"),
                }
            }
        }
    except Exception as e:
        logger.error(f"거래 기록 파싱 오류: {e}")
        return None


async def insert_trade_to_db(trade_data: Dict[str, Any], dry_run: bool = False) -> bool:
    """거래 기록을 PostgreSQL에 삽입"""
    if dry_run:
        logger.info(f"[DRY-RUN] 삽입 예정: {trade_data['symbol']} {trade_data['side']} @ {trade_data['exit_time']}")
        return True

    try:
        from HYPERRSI.src.services.trade_record_service import get_trade_record_service

        service = get_trade_record_service()
        await service.record_trade(
            okx_uid=trade_data["okx_uid"],
            symbol=trade_data["symbol"],
            side=trade_data["side"],
            is_hedge=trade_data["is_hedge"],
            entry_time=trade_data["entry_time"],
            entry_price=trade_data["entry_price"],
            entry_size=trade_data["entry_size"],
            exit_time=trade_data["exit_time"],
            exit_price=trade_data["exit_price"],
            exit_size=trade_data["exit_size"],
            close_type=trade_data["close_type"],
            leverage=trade_data["leverage"],
            dca_count=trade_data["dca_count"],
            avg_entry_price=trade_data["avg_entry_price"],
            realized_pnl=trade_data["realized_pnl"],
            realized_pnl_percent=trade_data["realized_pnl_percent"],
            entry_fee=trade_data["entry_fee"],
            exit_fee=trade_data["exit_fee"],
            entry_order_id=trade_data["entry_order_id"],
            exit_order_id=trade_data["exit_order_id"],
            extra_data=trade_data["extra_data"],
        )
        return True
    except Exception as e:
        logger.error(f"DB 삽입 오류: {e}")
        return False


async def check_duplicate(okx_uid: str, exit_order_id: str, exit_time: datetime) -> bool:
    """중복 거래 확인"""
    try:
        from HYPERRSI.src.services.trade_record_service import get_trade_record_service

        service = get_trade_record_service()

        # exit_order_id로 중복 확인
        if exit_order_id:
            existing = await service.get_trade_by_order_id(okx_uid, exit_order_id)
            if existing:
                return True

        return False
    except Exception as e:
        logger.warning(f"중복 확인 중 오류 (계속 진행): {e}")
        return False


async def migrate_user_trades(
    redis_client,
    okx_uid: str,
    dry_run: bool = False
) -> Dict[str, int]:
    """특정 사용자의 거래 기록 마이그레이션"""
    stats = {"total": 0, "success": 0, "skipped": 0, "failed": 0, "duplicate": 0}

    history_key = f"user:{okx_uid}:history"

    # 전체 거래 수 확인
    total_count = await redis_client.llen(history_key)
    logger.info(f"📊 [{okx_uid}] 총 {total_count}건의 거래 기록 발견")

    if total_count == 0:
        return stats

    # 모든 거래 기록 조회
    trades = await redis_client.lrange(history_key, 0, -1)
    stats["total"] = len(trades)

    for i, trade_json in enumerate(trades):
        trade_data = parse_trade_record(trade_json, okx_uid)

        if not trade_data:
            stats["skipped"] += 1
            continue

        # 중복 확인
        is_dup = await check_duplicate(
            okx_uid,
            trade_data.get("exit_order_id"),
            trade_data["exit_time"]
        )

        if is_dup:
            stats["duplicate"] += 1
            logger.debug(f"[{i+1}/{total_count}] 중복 건너뜀: {trade_data['symbol']}")
            continue

        # DB 삽입
        success = await insert_trade_to_db(trade_data, dry_run)

        if success:
            stats["success"] += 1
            if (i + 1) % 10 == 0:
                logger.info(f"[{i+1}/{total_count}] 진행 중...")
        else:
            stats["failed"] += 1

    return stats


async def main(dry_run: bool = False, target_user: Optional[str] = None):
    """메인 마이그레이션 함수"""
    logger.info("=" * 60)
    logger.info("🚀 Redis → PostgreSQL 거래 기록 마이그레이션 시작")
    logger.info(f"   모드: {'DRY-RUN (실제 저장 없음)' if dry_run else '실제 마이그레이션'}")
    if target_user:
        logger.info(f"   대상 사용자: {target_user}")
    logger.info("=" * 60)

    redis_client = await get_redis_client()

    try:
        # 마이그레이션 대상 키 조회
        if target_user:
            history_keys = [f"user:{target_user}:history"]
        else:
            history_keys = await get_all_user_history_keys(redis_client)

        logger.info(f"📋 마이그레이션 대상: {len(history_keys)}명의 사용자")

        total_stats = {"total": 0, "success": 0, "skipped": 0, "failed": 0, "duplicate": 0}

        for key in history_keys:
            # user:XXXXX:history에서 user_id 추출
            parts = key.split(":")
            if len(parts) >= 2:
                okx_uid = parts[1]
            else:
                logger.warning(f"잘못된 키 형식: {key}")
                continue

            logger.info(f"\n👤 사용자 {okx_uid} 마이그레이션 시작...")

            stats = await migrate_user_trades(redis_client, okx_uid, dry_run)

            # 통계 누적
            for k, v in stats.items():
                total_stats[k] += v

            logger.info(f"   ✅ 성공: {stats['success']}, ⏭️ 건너뜀: {stats['skipped']}, "
                       f"🔄 중복: {stats['duplicate']}, ❌ 실패: {stats['failed']}")

        # 최종 결과
        logger.info("\n" + "=" * 60)
        logger.info("📊 마이그레이션 완료 - 최종 통계")
        logger.info("=" * 60)
        logger.info(f"   총 처리: {total_stats['total']}건")
        logger.info(f"   ✅ 성공: {total_stats['success']}건")
        logger.info(f"   ⏭️ 건너뜀 (유효하지 않은 데이터): {total_stats['skipped']}건")
        logger.info(f"   🔄 중복 (이미 존재): {total_stats['duplicate']}건")
        logger.info(f"   ❌ 실패: {total_stats['failed']}건")

        if dry_run:
            logger.info("\n⚠️ DRY-RUN 모드였습니다. 실제 저장은 수행되지 않았습니다.")
            logger.info("   실제 마이그레이션을 수행하려면 --dry-run 옵션 없이 실행하세요.")

    finally:
        await redis_client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Redis 거래 기록을 PostgreSQL로 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 없이 시뮬레이션")
    parser.add_argument("--user", type=str, help="특정 사용자만 마이그레이션")

    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, target_user=args.user))

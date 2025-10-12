#src/bot/command/account.py
import json
import os

import httpx
import pytz
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

from HYPERRSI.src.trading.stats import (
    generate_pnl_statistics_image,
    get_pnl_history,
    get_trade_history,
    get_user_trading_statistics,
)
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import get_contract_size

logger = get_logger(__name__)

async def get_okx_uid_from_telegram_id(telegram_id: str) -> str:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수
    
    Args:
        telegram_id: 텔레그램 ID
        
    Returns:
        str: OKX UID
    """
    try:
        # 텔레그램 ID로 OKX UID 조회
        okx_uid = await get_redis_client().get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            return okx_uid.decode() if isinstance(okx_uid, bytes) else okx_uid
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID를 OKX UID로 변환 중 오류: {str(e)}")
        return None

def get_redis_keys(user_id):
    """
    Redis 키를 생성하는 함수. user_id는 OKX UID로 변환된 값을 사용해야 합니다.
    """
    return {
        'positions': f"user:{user_id}:position",
        'history': f"user:{user_id}:trade_history",
        'api_keys': f"user:{user_id}:api:keys"
    }

def format_size(size: float, symbol: str) -> str:
    """거래 크기를 읽기 쉬운 형식으로 변환"""
    if size < 0.001:
        return f"{size:.5f} {symbol}"
    else:
        return f"{size:.4g} {symbol}"
allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267"]
def is_allowed_user(user_id):
    """허용된 사용자인지 확인"""
    return str(user_id) in allowed_uid
@router.message(Command("balance"))
async def balance_command(message: types.Message):
    """계좌 잔고 확인"""
    telegram_id = str(message.from_user.id)
    okx_uid = await get_redis_client().get(f"user:{telegram_id}:okx_uid")
    
    # 텔레그램 ID를 OKX UID로 변환
    okx_uid = await get_okx_uid_from_telegram_id(telegram_id)
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return
    if not okx_uid:
        await message.reply(
            "⚠️ 등록되지 않은 사용자입니다.\n"
            "📝 /register 명령어로 먼저 등록해주세요."
            "API 화이트 리스트는\n 아래의 IP를 복사해서 등록해주세요.\n\n"
            "158.247.206.127,2401:c080:1c02:7bd:5400:5ff:fe18:6dd"
        )
        return
        
    keys = get_redis_keys(okx_uid)
    api_keys = await get_redis_client().hgetall(keys['api_keys'])
    
    if not api_keys:
        await message.reply(
            "⚠️ 등록되지 않은 사용자입니다.\n"
            "📝 /register 명령어로 먼저 등록해주세요."
            "API 화이트 리스트는\n 아래의 IP를 복사해서 등록해주세요.\n\n"
            "158.247.206.127,2401:c080:1c02:7bd:5400:5ff:fe18:6dd"
        )
        return

    try:
        # API 서버에 잔고 조회 요청
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{API_BASE_URL}/account/balance",
                    params={"user_id": okx_uid}  # OKX UID 사용
                )
                # 401 에러 명시적 처리
                if response.status_code == 401:
                    logger.error(f"API Authentication error for user {okx_uid}: {response.text}")
                    await message.reply(
                        "⚠️ API 키가 만료되었거나 유효하지 않습니다.\n"
                        "📝 /register 명령어로 API 키를 다시 등록해주세요."
                    )
                    return
                    
                response.raise_for_status()
                balance_data = response.json()
            except httpx.ConnectError:
                logger.error("OKX 서버 연결 실패")
                await message.reply(
                    "⚠️ OKX 서버에 연결할 수 없습니다.\n"
                    "📌 OKX 서버가 다운되었거나 점검 중일 수 있습니다.\n"
                    "잠시 후 다시 시도해주세요."
                )
                return
            except httpx.ReadTimeout:
                logger.error("OKX 서버 응답 시간 초과")
                await message.reply(
                    "⚠️ OKX 서버 응답이 없습니다.\n"
                    "📌 서버가 과부하 상태이거나 점검 중일 수 있습니다.\n"
                    "잠시 후 다시 시도해주세요."
                )
                return
        msg = []
        
        # 포지션 정보
        if balance_data["positions"]:
            msg.append("📋 활성 포지션\n")
            for pos in balance_data["positions"]:
                
                size = float(pos["size"])
                direction = pos["side"]
                if direction == "long":
                    direction = "롱 📈"
                elif direction == "short":
                    direction = "숏 📉"
                else:
                    direction = "미정"
                size_abs = abs(size)
                unrealized_pnl = float(pos["unrealized_pnl"])
                pnl_emoji = "🟢" if unrealized_pnl > 0 else "🔴" if unrealized_pnl < 0 else "⚪"

                msg.extend([
                    f"🔸 {pos['instrument']}",
                    f"├ 방향: {direction}",
                    f"├ 크기: {size_abs:.4f}",
                    f"├ 진입가: {float(pos['entry_price']):.4f}",
                    f"├ 현재 가격: {float(pos['mark_price']):.4f}",
                    f"├ 미실현손익: {pnl_emoji} {unrealized_pnl:,.2f} USDT",
                    f"├ 청산가: {float(pos['liquidation_price']):.4f}",
                    f"└ 레버리지: {pos['leverage']}x\n"
                ])

        # 잔고 정보
        msg.extend([
            "💰 계좌 잔고\n",
            f"📍 총 자산: {balance_data['total_equity']:,.2f} {balance_data['currency']}",
            f"├ 사용 가능: {balance_data['available_margin']:,.2f} {balance_data['currency']}",
            f"├ 사용 중: {balance_data['used_margin']:.2f} {balance_data['currency']}",
            f"└ 마진 비율: {balance_data['margin_ratio']:.2f}%\n",
            f"ℹ️ {message.date.astimezone(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S')}"
        ])

        await message.reply("\n".join(msg))

    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching balance: {str(e)}")
        if e.response.status_code == 401:
            await message.reply(
                "⚠️ API 키가 만료되었거나 유효하지 않습니다.\n"
                "📝 /register 명령어로 API 키를 다시 등록해주세요."
            )
        else:
            await message.reply(
                "⚠️ API 서버 연결 오류가 발생했습니다.\n"
                f"상태 코드: {e.response.status_code}\n"
                "잠시 후 다시 시도해주세요."
            )
    except Exception as e:
        logger.error(f"Error fetching balance: [{type(e)}] {str(e)}")
        await message.reply(
            "⚠️ 정보 조회 중 오류가 발생했습니다.\n"
            "잠시 후 다시 시도해주세요."
        )

    
@router.message(Command("history"))
async def history_command(message: types.Message):
    """거래 내역 조회"""
    telegram_id = str(message.from_user.id)
    
    # 텔레그램 ID를 OKX UID로 변환
    okx_uid = await get_okx_uid_from_telegram_id(telegram_id)
    
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    if not okx_uid:
        await message.reply(
            "⚠️ 등록되지 않은 사용자입니다.\n"
            "📝 /register 명령어로 먼저 등록해주세요."
            "API 화이트 리스트는\n 아래의 IP를 복사해서 등록해주세요.\n\n"
            "158.247.206.127,2401:c080:1c02:7bd:5400:5ff:fe18:6dd"
        )
        return
        
    keys = get_redis_keys(okx_uid)
    trade_history_as_exchange = False
    # API 키 확인
    api_keys = await get_redis_client().hgetall(keys['api_keys'])
    if not api_keys:
        await message.reply(
            "⚠️ 등록되지 않은 사용자입니다.\n"
            "📝 /register 명령어로 먼저 등록해주세요."
            "API 화이트 리스트는\n 아래의 IP를 복사해서 등록해주세요.\n\n"
            "158.247.206.127,2401:c080:1c02:7bd:5400:5ff:fe18:6dd"
        )
        return
        
    try:
        # 거래 내역 조회 (최근 10개)
        try:
            trades = await get_pnl_history(okx_uid, limit=10)  # OKX UID 사용
            if not trades:
                await message.reply("📜 거래 내역이 없습니다.")
                return
        except Exception as e:
            trade_history_as_exchange = True
            logger.error(f"Error fetching PnL history: {str(e)}")
            
        stats = await get_user_trading_statistics(okx_uid)  # OKX UID 사용
        
        stats_msg = "📊 트레이딩 성과 요약\n"
        stats_msg += f"├ 총 수익: {'🟢' if stats['total_pnl'] >= 0 else '🔴'} "
        stats_msg += f"{'+' if stats['total_pnl'] >= 0 else ''}{stats['total_pnl']:.2f} USD\n"
        stats_msg += f"├ 총 거래: {stats['total_trades']}회\n"
        stats_msg += f"├ 승률: {stats['win_rate']:.1f}%\n"
        stats_msg += f"├ 최고 수익: +{stats['best_trade']['pnl']:.2f} USD\n"
        stats_msg += f"└ 최대 손실: {stats['worst_trade']['pnl']:.2f} USD\n\n"
        
        await message.reply(stats_msg)
        img_path = await generate_pnl_statistics_image(okx_uid)
        if img_path:
            await message.reply_photo(FSInputFile(img_path))
            os.unlink(img_path)  # 임시 파일 삭제
            
        #===============================================
        # 최근 거래 내역 조회(Redis 이용 )
        #===============================================
        history_msg = "📜 최근 거래 내역\n\n"
        if trade_history_as_exchange == False:
            for trade in trades:
                contract_size = await get_contract_size(trade['symbol'])
                symbol_str = trade['symbol'].split('-')[0]
                
                # tp_level 형식 확인 및 표시 방식 개선
                tp_display = trade['tp_level'].upper() if trade['tp_level'] != 'unknown' else "일반"
                if tp_display.startswith('TP'):
                    tp_display = tp_display  # 이미 TP로 시작하면 그대로 유지
                elif tp_display == 'SL':
                    tp_display = "손절(SL)"
                elif tp_display == 'BREAK_EVEN':
                    tp_display = "브레이크이븐"
                
                history_msg += (
                    f"🔸 {trade['timestamp']}\n"
                    f"├ 심볼: {symbol_str}\n"
                    f"├ 방향: {'롱 📈' if trade['side'] == 'long' else '숏 📉'}\n"
                    f"├ 크기: {format_size(float(trade['size']), symbol_str)}\n"
                    f"├ 유형: {tp_display}\n"
                    f"├ 진입가격: {float(trade['entry_price']):,.2f}\n"
                    f"├ 종료가격: {float(trade['exit_price']):,.2f}\n"
                )
                
                pnl = float(trade['pnl'])
                pnl_emoji = '🔴' if pnl < 0 else '🟢'
                closed_str = '수익' if pnl > 0 else '손실'
                plus_minus = '+' if pnl > 0 else ''
                
                # PnL 퍼센트 계산
                try:
                    if float(trade['entry_price']) > 0 and float(trade['size']) > 0:
                        contract_value = float(trade['size']) * float(contract_size)
                        position_value = float(trade['entry_price']) * contract_value
                        pnl_percent = (pnl / position_value) * 100 if position_value > 0 else 0
                    else:
                        pnl_percent = 0
                except Exception as e:
                    logger.error(f"Error calculating PnL percent: {str(e)}")
                    pnl_percent = 0
                
                history_msg += (
                    f"└ {closed_str}: {pnl_emoji} {plus_minus}{abs(pnl):.2f} USD "
                    f"({pnl_percent:.2f}%)\n\n"
                )
            
            await message.reply(history_msg)
            
        #===============================================
        # 최근 거래 내역 조회(거래소 기록 이용 )
        #===============================================
        if trade_history_as_exchange == True:
            try:
                history = await get_trade_history(okx_uid, limit=10)
            except httpx.ConnectError:
                logger.error("OKX 서버 연결 실패 - 거래 내역 조회")
                await message.reply(
                    "⚠️ OKX 서버에 연결할 수 없습니다.\n"
                    "📌 OKX 서버가 다운되었거나 점검 중일 수 있습니다.\n"
                    "잠시 후 다시 시도해주세요."
                )
                return
            except httpx.ReadTimeout:
                logger.error("OKX 서버 응답 시간 초과 - 거래 내역 조회")
                await message.reply(
                    "⚠️ OKX 서버 응답이 없습니다.\n"
                    "📌 서버가 과부하 상태이거나 점검 중일 수 있습니다.\n"
                    "잠시 후 다시 시도해주세요."
                )
                return
            
            if not history:
                await message.reply("📜 거래 내역이 없습니다.")
                return
            for trade in history:
                contract_size = await get_contract_size(trade['symbol'])
                status_emoji = "🔹" if trade['status'] == 'open' else "🔸"
                symbol_str = trade['symbol'].split('-')[0]
                history_msg += (
                    f"{status_emoji} {trade['timestamp']}\n"
                    f"├ 심볼: {symbol_str}\n"
                    f"├ 방향: {'롱 📈' if trade['side'] == 'long' else '숏 📉'}\n"
                    f"├ 크기: {format_size(float(trade['size']) * float(contract_size), symbol_str)}\n"
                    f"├ 레버리지: {trade['leverage']}x\n"
                    f"├ 진입가격: {float(trade['entry_price']):,.2f}\n"
                )
                if trade['status'] != 'open':
                    pnl_emoji = '🔴' if trade.get('pnl', 0) < 0 else '🟢'
                    closed_str = '수익' if trade.get('pnl', 0) > 0 else '손실'
                    plus_minus = '+' if trade.get('pnl', 0) > 0 else '-'
                    history_msg += (
                        f"├ 종료가격: {float(trade['exit_price']):,.2f}\n"
                        f"└ {closed_str}: {pnl_emoji} {plus_minus}{abs(float(trade.get('pnl', 0))):,.2f} USD "
                        f"({trade.get('pnl_percent', 0):.2f}%)\n\n"
                    )
                else:
                    history_msg += f"└ 상태: 진행중\n\n"
                    
            await message.reply(history_msg)
        
    except Exception as e:
        logger.error(f"Error fetching trade history: {str(e)}")
        await message.reply("⚠️ 거래 내역 조회 중 오류가 발생했습니다.")
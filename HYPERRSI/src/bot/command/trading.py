# src/bot/commands/trading.py

import datetime as dt
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
import ccxt.async_support as ccxt
import httpx
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message

from HYPERRSI.src.api.dependencies import get_user_api_keys
from HYPERRSI.src.core.celery_task import celery_app
from HYPERRSI.src.trading.trading_service import round_to_tick_size
from shared.database.redis_helper import get_redis_client

router = Router()
logger = logging.getLogger(__name__)

from HYPERRSI.src.core.error_handler import log_error
import os

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api")
allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267","586156710277369942"]
def is_allowed_user(user_id: Optional[str]) -> bool:
    """허용된 사용자인지 확인"""
    if user_id is None:
        return False
    return str(user_id) in allowed_uid

def get_redis_keys(user_id: str, symbol: Optional[str] = None, side: Optional[str] = None) -> Dict[str, str]:
    keys = {
        'status': f"user:{user_id}:trading:status",
        'api_keys': f"user:{user_id}:api:keys",
        'stats': f"user:{user_id}:stats",
    }

    if symbol is not None and side is not None:
        keys['position'] = f"user:{user_id}:position:{symbol}:{side}"

    return keys

async def get_telegram_id(identifier: str) -> Optional[int]:
    """
    식별자가 okx_uid인지 telegram_id인지 확인하고 적절한 telegram_id를 반환합니다.

    Args:
        identifier: 확인할 식별자 (okx_uid 또는 telegram_id)

    Returns:
        Optional[int]: 텔레그램 ID
    """
    # 13자리 미만이면 telegram_id로 간주
    if len(identifier) < 13:
        return int(identifier)

    # 13자리 이상이면 okx_uid로 간주하고 텔레그램 ID 조회
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/user/okx/{identifier}/telegram") as response:
                if response.status == 200:
                    data: Dict[str, Any] = await response.json()
                    return data.get("primary_telegram_id")
                else:
                    logger.error(f"OKX UID {identifier}에 대한 텔레그램 ID 조회 실패: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"OKX UID {identifier}에 대한 텔레그램 ID 조회 중 오류: {str(e)}")
        return None

# 텔레그램 ID를 OKX UID로 변환하는 함수 직접 구현
async def get_okx_uid_from_telegram_id(telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환합니다.

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        Optional[str]: OKX UID
    """
    try:
        redis = await get_redis_client()
        # Redis에서 OKX UID 조회
        okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            # bytes 타입인 경우에만 decode 수행
            if isinstance(okx_uid, bytes):
                return okx_uid.decode('utf-8')
            return str(okx_uid)

        # Redis에 없으면 API 호출
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/user/telegram/{telegram_id}/okx")
            if response.status_code == 200:
                data: Dict[str, Any] = response.json()
                okx_uid_result = data.get("okx_uid")
                if okx_uid_result:
                    # Redis에 저장
                    await redis.set(f"user:{telegram_id}:okx_uid", str(okx_uid_result))
                    return str(okx_uid_result)

        logger.error(f"텔레그램 ID {telegram_id}에 대한 OKX UID를 찾을 수 없습니다.")
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID {telegram_id}를 OKX UID로 변환 중 오류 발생: {str(e)}")
        return None

@router.message(Command("stop"))
async def stop_command(message: types.Message) -> None:
    """트레이딩 강제 중지 명령어"""
    redis = await get_redis_client()
    if message.from_user is None:
        return
    user_id = message.from_user.id
    okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
    okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    # OKX UID로 키 생성
    keys = get_redis_keys(okx_uid if okx_uid else str(user_id))
    
    try:
        # 텔레그램 ID를 OKX UID로 변환
        okx_uid = await get_okx_uid_from_telegram_id(str(user_id))
        if not is_allowed_user(okx_uid):
            await message.reply("⛔ 접근 권한이 없습니다.")
            return
        
        # 현재 상태 확인 (텔레그램 ID와 OKX UID 모두 확인)
        current_status = await redis.get(keys['status'])
        
        # OKX UID가 있는 경우 해당 상태도 확인
        okx_status = None
        if okx_uid:
            okx_keys = get_redis_keys(okx_uid)
            okx_status = await redis.get(okx_keys['status'])
        
        # 둘 다 running이 아니면 실행 중인 트레이딩이 없음
        if current_status != "running" and (not okx_uid or okx_status != "running"):
            await message.reply("현재 실행 중인 트레이딩이 없습니다.")
            return
        
        # 확인 버튼 추가
        confirm_keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="예", callback_data="confirm_stop"),
                    types.InlineKeyboardButton(text="아니오", callback_data="cancel_stop")
                ]
            ]
        )
        
        await message.reply(
            "⚠️ 정말로 트레이딩을 중지하시겠습니까?",
            reply_markup=confirm_keyboard
        )

    except Exception as e:
        logger.error(f"Error checking trading status for user {user_id}: {str(e)}")
        await message.reply("❌ 상태 확인 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

@router.callback_query(F.data == "confirm_stop")
async def confirm_stop(callback: types.CallbackQuery) -> None:
    """트레이딩 중지 확인"""
    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None:
        return
    try:
        user_id = callback.from_user.id
        okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
        okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
        if not is_allowed_user(okx_uid):
            print("접근 권한 없음. trading.py", okx_uid)
            await callback.message.reply("⛔ 접근 권한이 없습니다.")
            return

        # OKX UID로 키 생성
        keys = get_redis_keys(okx_uid if okx_uid else str(user_id))

        # 텔레그램 ID를 OKX UID로 변환
        okx_uid = await get_okx_uid_from_telegram_id(str(user_id))
        
        # 현재 상태 확인 (텔레그램 ID와 OKX UID 모두 확인)
        current_status = await redis.get(keys['status'])
        
        # OKX UID가 있는 경우 해당 상태도 확인
        okx_status = None
        if okx_uid:
            okx_keys = get_redis_keys(okx_uid)
            okx_status = await redis.get(okx_keys['status'])
        
        # 둘 다 running이 아니면 실행 중인 트레이딩이 없음
        if current_status != "running" and (not okx_uid or okx_status != "running"):
            await callback.message.edit_text("현재 실행 중인 트레이딩이 없습니다.")
            await callback.answer("실행 중인 트레이딩이 없습니다.")
            return
        
        # FastAPI 엔드포인트 호출
        client = httpx.AsyncClient()
        try:
            # 텔레그램 ID가 running이면 텔레그램 ID로 API 호출
            if current_status == "running":
                request_data = {
                    "okx_uid": str(user_id)
                }
                
                response = await client.post(
                    f"{API_BASE_URL}/trading/stop",
                    json=request_data
                )
                response.raise_for_status()
                logger.info(f"텔레그램 ID {user_id}로 트레이딩 중지 API 호출 성공")
            
            # OKX UID가 running이면 OKX UID로 API 호출
            if okx_uid and okx_status == "running":
                request_data = {
                    "okx_uid": okx_uid
                }
                
                response = await client.post(
                    f"{API_BASE_URL}/trading/stop",
                    json=request_data
                )
                response.raise_for_status()
                logger.info(f"OKX UID {okx_uid}로 트레이딩 중지 API 호출 성공")
            
            # 성공 메시지 전송
            await callback.message.edit_text(
                "✅ 트레이딩이 중지되었습니다.\n"
                "다시 시작하려면 /start 명령어를 사용하세요."
            )
            await callback.answer("트레이딩이 중지되었습니다.")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Error stopping trading via API for user {user_id}: {e}")
            await callback.answer("트레이딩 중지 중 오류가 발생했습니다.")
            return
        finally:
            await client.aclose()
            
    except Exception as e:
        logger.error(f"Error in confirm_stop: {e}")
        await callback.answer("트레이딩 중지 중 오류가 발생했습니다.")

@router.callback_query(F.data == "cancel_stop")

async def cancel_stop(callback: types.CallbackQuery) -> None:
    """트레이딩 중지 취소"""
    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text("✅ 트레이딩 중지가 취소되었습니다.")
    await callback.answer()


@router.callback_query(F.data == "cancel_stop_return")
async def cancel_stop_return(callback: types.CallbackQuery) -> None:
    """트레이딩 중지 취소"""
    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text("취소되었습니다.")
    await callback.answer()
    

    
@router.message(Command("trade"))
async def trade_command(message: types.Message) -> None:
    """트레이딩 제어 명령어"""
    redis = await get_redis_client()
    if message.from_user is None:
        return
    user_id = message.from_user.id
    okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
    okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
    if not is_allowed_user(okx_uid):
        print("접근 권한 없음. trading.py", okx_uid)
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    # OKX UID로 키 생성
    keys = get_redis_keys(okx_uid if okx_uid else str(user_id))

    # API 키 확인
    api_keys = await redis.hgetall(keys['api_keys'])
    if not api_keys:
        await message.reply(
            "API 키 정보가 없습니다.\n"
            "/register 명령어로 API 키를 등록해주세요."
        )
        return

    # 텔레그램 ID를 OKX UID로 변환
    okx_uid = await get_okx_uid_from_telegram_id(str(user_id))
    
    # 현재 트레이딩 상태 확인 (텔레그램 ID)
    trading_status = await redis.get(f"user:{user_id}:trading:status")
    
    # 바이트 문자열을 디코딩
    if isinstance(trading_status, bytes):
        trading_status = trading_status.decode('utf-8')
    
    # OKX UID가 있는 경우 해당 상태도 확인
    okx_trading_status = None
    if okx_uid:
        okx_keys = get_redis_keys(okx_uid)
        okx_trading_status = await redis.get(okx_keys['status'])
        
        # 바이트 문자열을 디코딩
        if isinstance(okx_trading_status, bytes):
            okx_trading_status = okx_trading_status.decode('utf-8')
    
    # 둘 중 하나라도 running이면 실행 중으로 간주
    is_trading = trading_status == "running" or (okx_uid and okx_trading_status == "running")
    
    ## 추가: stop_signal 확인
    #stop_signal = None
    #if okx_uid:
    #    stop_signal = await redis_client.get(f"user:{okx_uid}:stop_signal")
    #if not stop_signal:
    #    stop_signal = await redis_client.get(f"user:{user_id}:stop_signal")
    
    # stop_signal이 있으면 실행 중이 아님
    #if stop_signal:
    #    is_trading = False

    # OKX UID로 preference 조회
    preference = await redis.hgetall(f"user:{okx_uid if okx_uid else user_id}:preferences")
    selected_symbol = preference.get("symbol")
    selected_timeframe = preference.get("timeframe")
    
    if is_trading:
        # 실행 중인 경우의 키보드
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="⛔️ 중지",
                    callback_data="trade_stop",
                    disabled=False
                )
            ],
            [types.InlineKeyboardButton(
                text="취소",
                callback_data="cancel_stop_return"
            )]
        ])
        
        await message.reply(
            f"트레이딩 제어\n"
            f"현재 상태: 🟢 실행 중\n"
            f"실행 중인 심볼: {selected_symbol}\n"
            f"타임프레임: {selected_timeframe}\n\n"
            f"원하시는 작업을 선택해주세요:",
            reply_markup=keyboard
        )
        
    else:
        # 종목 선택 키보드만 먼저 표시
        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        
        symbol_buttons = []
        for symbol in symbols:
            # 선택된 종목에 체크표시 추가
            text = f"{'✅ ' if selected_symbol and selected_symbol == symbol else ''}{symbol}"
            symbol_buttons.append([
                types.InlineKeyboardButton( 
                    text=text,
                    callback_data=f"select_symbol_{symbol}"
                )
            ])
            
        # 선택된 종목이 있는 경우 타임프레임 선택 추가
        if selected_symbol:
            timeframes = ['1m', '3m', '5m', '15m', '30m', '1H', '4H']
            timeframe_buttons = []
            for tf in timeframes:
                text = f"{'✅ ' if selected_timeframe and selected_timeframe == tf else ''}{tf}"
                timeframe_buttons.append([
                    types.InlineKeyboardButton(
                        text=text,
                        callback_data=f"select_timeframe_{tf}"
                    )
                ])
            
            # 시작 버튼 추가 (둘 다 선택된 경우만 활성화)
            start_button = [
                types.InlineKeyboardButton(
                    text="✅ 트레이딩 시작",
                    callback_data="trade_start",
                    disabled=not (selected_symbol and selected_timeframe)
                )
            ]
            
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="⌛ 타임프레임 선택", callback_data="dummy", disabled=True)],
                *timeframe_buttons,
                start_button,
                [types.InlineKeyboardButton(
                    text="🔄 처음부터 다시 설정",
                    callback_data="trade_reset"
                )]
            ])
            
            status_text = (
                f"📊 트레이딩 설정\n\n"
                f"1️⃣ 거래할 종목을 선택해주세요:\n"
                f"현재 선택: {selected_symbol if selected_symbol else '없음'}\n\n"
                f"2️⃣ 타임프레임을 선택해주세요:\n"
                f"현재 선택: {selected_timeframe if selected_timeframe else '없음'}"
            )
            
        else:
            # 종목만 선택하는 초기 화면
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=symbol_buttons)
            status_text = (
                "📊 트레이딩 설정\n\n"
                "1️⃣ 거래할 종목을 선택해주세요:"
            )
        
        await message.reply(
            status_text,
            reply_markup=keyboard
        )
@router.callback_query(lambda c: c.data.startswith('select_symbol_'))

async def handle_symbol_selection(callback: types.CallbackQuery) -> None:

    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None or callback.data is None:
        return
    try:
        user_id = callback.from_user.id

        # OKX UID 조회
        okx_uid = await get_okx_uid_from_telegram_id(str(user_id))

        symbol = callback.data.replace('select_symbol_', '')

        # 선택된 심볼 저장
        await redis.set(f"user:{user_id}:selected_symbol", symbol)

        # OKX UID로 preference 저장
        preference_key = f"user:{okx_uid if okx_uid else user_id}:preferences"
        await redis.hset(preference_key, mapping={
            "symbol": symbol
        })

        selected_timeframe = await redis.get(f"user:{user_id}:selected_timeframe")
        
        
        
        
        
        
        # 모든 심볼 버튼 생성 (현재 선택된 것 체크표시)
        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        symbol_buttons = []
        for sym in symbols:
            text = f"{'✅ ' if sym == symbol else ''}{sym}"
            symbol_buttons.append([
                types.InlineKeyboardButton(
                    text=text,
                    callback_data=f"select_symbol_{sym}"
                )
            ])
        
        # 타임프레임 버튼 생성
        timeframes = ['1m', '3m', '5m', '15m', '30m', '1H', '4H']
        timeframe_buttons = []
        for tf in timeframes:
            text = f"{'✅ ' if selected_timeframe and selected_timeframe == tf else ''}{tf}"
            timeframe_buttons.append([
                types.InlineKeyboardButton(
                    text=text,
                    callback_data=f"select_timeframe_{tf}"
                )
            ])
        
        # 시작 버튼 (둘 다 선택된 경우만 활성화)
        start_button = [
            types.InlineKeyboardButton(
                text="✅ 트레이딩 시작",
                callback_data="trade_start",
                disabled=not (symbol and selected_timeframe)
            )
        ]
        
        # 전체 키보드 구성
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            *symbol_buttons,
            [types.InlineKeyboardButton(text="⌛ 타임프레임 선택", callback_data="dummy", disabled=True)],
            *timeframe_buttons,
            start_button,
            [types.InlineKeyboardButton(
                text="🔄 처음부터 다시 설정",
                callback_data="trade_reset"
            )]
        ])
        
        await callback.message.edit_text(
            f"📊 트레이딩 설정\n\n"
            f"1️⃣ 거래할 종목을 선택해주세요:\n"
            f"현재 선택: {symbol}\n\n"
            f"2️⃣ 타임프레임을 선택해주세요:\n"
            f"현재 선택: {selected_timeframe if selected_timeframe else '없음'}",
            reply_markup=keyboard
        )
        
        await callback.answer(f"{symbol} 선택됨")
        
    except Exception as e:
        logger.error(f"Error in symbol selection: {str(e)}")
        await callback.answer("오류가 발생했습니다. 다시 시도해주세요.")

@router.callback_query(lambda c: c.data == "back_to_symbol")
async def handle_back_to_symbol(callback: types.CallbackQuery) -> None:
    """종목 선택으로 돌아가기"""
    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None:
        return
    try:
        user_id = callback.from_user.id

        # 선택된 심볼 초기화
        await redis.delete(f"user:{user_id}:selected_symbol")

        # 종목 선택 키보드 생성
        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        symbol_buttons = []
        
        for symbol in symbols:
            symbol_buttons.append([
                types.InlineKeyboardButton(
                    text=f"📊 {symbol}",
                    callback_data=f"select_symbol_{symbol}"
                )
            ])
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=symbol_buttons)
        
        await callback.message.edit_text(
            "📊 트레이딩 설정\n\n"
            "1️⃣ 거래할 종목을 선택해주세요:",
            reply_markup=keyboard
        )
        
        await callback.answer("종목 선택 화면으로 돌아갔습니다.")
        
    except Exception as e:
        logger.error(f"Error in back to symbol handler: {str(e)}")
        await callback.answer("오류가 발생했습니다. 다시 시도해주세요.")

@router.callback_query(lambda c: c.data.startswith('select_timeframe_'))

async def handle_timeframe_selection(callback: types.CallbackQuery) -> None:

    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None or callback.data is None:
        return
    user_id = callback.from_user.id

    # OKX UID 조회
    okx_uid = await get_okx_uid_from_telegram_id(str(user_id))

    timeframe = callback.data.replace('select_timeframe_', '')

    # OKX UID로 preference 키 생성
    preference_key = f"user:{okx_uid if okx_uid else user_id}:preferences"

    await redis.set(f"user:{user_id}:selected_timeframe", timeframe)
    await redis.hset(preference_key, mapping={
        "timeframe": timeframe
    })
    selected_symbol = await redis.get(f"user:{user_id}:selected_symbol")
    
    # 최종 확인 키보드
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="✅ 트레이딩 시작",
            callback_data="trade_start"
        )],
        [types.InlineKeyboardButton(
            text="⬅️ 타임프레임 다시 선택",
            callback_data="back_to_timeframe"
        )],
        [types.InlineKeyboardButton(
            text="🔄 처음부터 다시 설정",
            callback_data="trade_reset"
        )]
    ])
    
    await callback.message.edit_text(
        f"📊 트레이딩 설정 확인\n\n"
        f"📈 선택된 종목: {selected_symbol}\n"
        f"⏱ 타임프레임: {timeframe}\n\n"
        f"설정이 맞다면 '트레이딩 시작'을 눌러주세요.",
        reply_markup=keyboard
    )
@router.callback_query(lambda c: c.data in ["trade_start", "trade_stop"])
async def handle_trade_callback(callback: types.CallbackQuery) -> None:

    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None or callback.data is None:
        return
    try:
        user_id = callback.from_user.id
        action = callback.data.split('_')[1]
        
        # 텔레그램 ID를 OKX UID로 변환
        okx_uid = await get_okx_uid_from_telegram_id(str(user_id))

        if action == "start":
            # OKX UID로 preference 키 생성
            preference_key = f"user:{okx_uid if okx_uid else user_id}:preferences"
            preferences = await redis.hgetall(preference_key)
            selected_symbol = preferences.get("symbol")
            selected_timeframe = preferences.get("timeframe")

            if not (selected_symbol and selected_timeframe):
                await callback.answer("심볼과 타임프레임을 선택해주세요.")
                return

            # 선택된 설정을 preferences에 저장 (OKX UID 사용)
            await redis.hset(preference_key, mapping={
                "symbol": selected_symbol,
                "timeframe": selected_timeframe
            })

            ## 먼저 상태를 running으로 설정
            #await redis_client.set(f"user:{user_id}:trading:status", "running")
            #if okx_uid:
            #    await redis_client.set(f"user:{okx_uid}:trading:status", "running")

            request_body = {
                "user_id": user_id,
                "symbol": selected_symbol,
                "timeframe": selected_timeframe,
                "start_time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type": "start"
            }

            await redis.set(f"user:{user_id}:trading:request", json.dumps(request_body))

            # OKX UID가 있는 경우 해당 설정도 저장
            if okx_uid:
                okx_request_body = {
                    "user_id": okx_uid,
                    "symbol": selected_symbol,
                    "timeframe": selected_timeframe,
                    "start_time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "start"
                }

                await redis.set(f"user:{okx_uid}:trading:request", json.dumps(okx_request_body))

            # OKX UID로 settings 키 생성
            settings_key = f"user:{okx_uid if okx_uid else user_id}:settings"
            # 먼저 키의 타입을 확인
            settings_str = await redis.get(settings_key)
            settings = json.loads(settings_str) if settings_str else {}

            if selected_symbol == "BTC-USDT-SWAP":
                investment = settings.get("btc_investment")
            elif selected_symbol == "ETH-USDT-SWAP":
                investment = settings.get("eth_investment")
            elif selected_symbol == "SOL-USDT-SWAP":
                investment = settings.get("sol_investment")

            leverage = settings.get("leverage")

            actual_investment = float(investment) * float(leverage) if investment and leverage else 0.0
            min_notional = 200
            if actual_investment < min_notional:
                msg = (
                    f"⚠️ 최소 주문 금액 오류\n"
                    f"─────────────────────\n"
                    f"현재 설정된 금액이 최소 주문 금액보다 작습니다.\n"
                    f"• 현재(레버리지*투자금): {actual_investment:.2f} USDT\n"
                    f"• 최소 투자금: {min_notional:.2f} USDT\n"
                    f"설정을 수정하고 다시 시작해주세요."
                )
                await callback.message.edit_text(msg)
                await callback.answer()
                # 상태를 stopped로 변경
                await redis.set(f"user:{user_id}:trading:status", "stopped")
                print("22❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥 !!!")
                if okx_uid:
                    await redis.set(f"user:{okx_uid}:trading:status", "stopped")
                    print("33❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥 !!!")
                return
            
            # FastAPI 엔드포인트 호출 수정
            client = httpx.AsyncClient()
            try:
                # OKX UID가 있으면 OKX UID로, 없으면 텔레그램 ID로 API 호출
                api_user_id = okx_uid if okx_uid else user_id
                
                # 요청 본문 수정
                request_data = {
                    "user_id": api_user_id,
                    "symbol": selected_symbol,
                    "timeframe": selected_timeframe,
                    "start_time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "start"
                }
                
                response = await client.post(
                    f"{API_BASE_URL}/trading/start",
                    json=request_data
                )
                response.raise_for_status()
                
            except httpx.HTTPStatusError as e:
                # 이미 실행 중인 경우 (400 에러)는 성공으로 처리
                error_detail = ""
                try:
                    error_response = e.response.json()
                    error_detail = error_response.get("detail", "")
                except:
                    error_detail = str(e)

                if e.response.status_code == 400 and "이미 트레이딩 태스크가 실행 중입니다" in error_detail:
                    logger.info(f"Trading already running for user {user_id}, treating as success")
                    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(
                            text="🔒 시작 (실행 중)",
                            callback_data="trade_start",
                            disabled=True
                        )],
                        [types.InlineKeyboardButton(
                            text="⛔️ 중지",
                            callback_data="trade_stop",
                            disabled=False
                        )]
                    ])

                    await callback.message.edit_text(
                        f"📊 트레이딩 상태\n\n"
                        f"현재 상태: 🟢 실행 중\n"
                        f"거래 종목: {selected_symbol}\n"
                        f"타임프레임: {selected_timeframe}",
                        reply_markup=keyboard
                    )
                    await callback.answer("이미 트레이딩이 실행 중입니다!")
                    return

                # 다른 오류는 기존 처리 유지
                logger.error(f"Error starting trading task: {e}, detail: {error_detail}")
                await callback.answer(f"트레이딩 시작 중 오류: {error_detail[:100]}")
                # 오류 발생 시 상태를 stopped로 변경
                await redis.set(f"user:{user_id}:trading:status", "stopped")
                if okx_uid:
                    await redis.set(f"user:{okx_uid}:trading:status", "stopped")
                return
            finally:
                await client.aclose()  # 클라이언트 명시적 종료

            # 상태 업데이트 및 UI 수정
            #await redis_client.set(f"user:{user_id}:trading:status", "running")
            
            # OKX UID가 있는 경우 해당 상태도 업데이트
            #if okx_uid:
            #    await redis_client.set(f"user:{okx_uid}:trading:status", "running")
            
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="🔒 시작 (실행 중)",
                    callback_data="trade_start",
                    disabled=True
                )],
                [types.InlineKeyboardButton(
                    text="⛔️ 중지",
                    callback_data="trade_stop",
                    disabled=False
                )]
            ])

            await callback.message.edit_text(
                f"📊 트레이딩 상태\n\n"
                f"현재 상태: 🟢 실행 중\n"
                f"거래 종목: {selected_symbol}\n"
                f"타임프레임: {selected_timeframe}",
                reply_markup=keyboard
            )
            
            # 시작 알림 메시지
            await callback.answer("트레이딩이 시작되었습니다!")
            
        elif action == "stop":
            # FastAPI 엔드포인트를 통해 트레이딩 중지
            client = httpx.AsyncClient()
            try:
                # OKX UID로 stop API 호출
                request_data = {
                    "okx_uid": okx_uid if okx_uid else str(user_id)
                }

                response = await client.post(
                    f"{API_BASE_URL}/trading/stop",
                    params={"user_id": okx_uid if okx_uid else str(user_id)}
                )
                response.raise_for_status()
                logger.info(f"트레이딩 중지 API 호출 성공 (user_id: {user_id}, okx_uid: {okx_uid})")

            except httpx.HTTPStatusError as e:
                error_detail = ""
                try:
                    error_response = e.response.json()
                    error_detail = error_response.get("detail", "")
                except:
                    error_detail = str(e)

                logger.error(f"Error stopping trading: {e}, detail: {error_detail}")
                await callback.answer(f"중지 중 오류: {error_detail[:100]}")
                return
            finally:
                await client.aclose()
            
            # 종목 선택 화면으로 돌아가기
            symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            symbol_buttons = []
            for symbol in symbols:
                symbol_buttons.append([
                    types.InlineKeyboardButton(
                        text=f"📊 {symbol}",
                        callback_data=f"select_symbol_{symbol}"
                    )
                ])
            
            
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=symbol_buttons)

            await callback.message.edit_text(
                "📊 트레이딩 설정\n\n"
                "1️⃣ 거래할 종목을 선택해주세요:",
                reply_markup=keyboard
            )
            
            # 중지 알림 메시지
            
            await callback.answer("트레이딩이 중지되었습니다.")
            
    except Exception as e:
        logger.error(f"Error in trade callback for user {user_id}: {str(e)}")
        traceback.print_exc()
        await callback.answer("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
        
@router.callback_query(lambda c: c.data == "trade_reset")
async def handle_reset_callback(callback: types.CallbackQuery) -> None:
    """재설정 처리"""
    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None:
        return
    try:
        user_id = callback.from_user.id
        okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
        okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None

        # OKX UID로 키 생성
        keys = get_redis_keys(okx_uid if okx_uid else str(user_id))
        await redis.set(keys['status'], "stopped")
        print("RESETED!!!")
        # 선택 초기화 - OKX UID로 preference 삭제
        await redis.delete(f"user:{user_id}:selected_symbol")
        await redis.delete(f"user:{user_id}:selected_timeframe")
        await redis.delete(f"user:{okx_uid if okx_uid else user_id}:preferences")
        #await callback.message.answer("⛔ 트레이딩이 중지되었습니다.")
        # 선택 화면 직접 생성
        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        timeframes = [1, 3, 5, 15, 30, 60, 240]
        
        # 심볼 선택 버튼
        symbol_buttons = []
        for symbol in symbols:
            symbol_buttons.append([
                types.InlineKeyboardButton(
                    text=f"📊 {symbol}",
                    callback_data=f"select_symbol_{symbol}"
                )
            ])
        
        # 타임프레임 선택 버튼
        timeframe_buttons = []
        for tf in timeframes:
            timeframe_buttons.append([
                types.InlineKeyboardButton(
                    text=f"⏱ {tf}",
                    callback_data=f"select_timeframe_{tf}"
                )
            ])
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="✅ 시작 (심볼과 타임프레임 선택 필요)",
                callback_data="trade_start",
                disabled=True
            )],
            *symbol_buttons,
            [types.InlineKeyboardButton(
                text="🔒 중지 (미실행)",
                callback_data="trade_stop",
                disabled=True
            )]
        ])
        
        await callback.message.edit_text(
            f"트레이딩 제어\n"
            f"현재 상태: 🔴 중지됨\n\n"
            f"원하시는 작업을 선택해주세요:",
            reply_markup=keyboard
        )
        
        await callback.answer("설정이 초기화되었습니다.")
        
    except Exception as e:
        logger.error(f"Reset callback error for user {user_id}: {str(e)}")
        await callback.answer("재설정 중 오류가 발생했습니다.")
        
        
@router.message(Command("status"))
async def status_command(message: types.Message) -> None:
    """현재 트레이딩 상태와 통계 표시"""
    redis = await get_redis_client()
    if message.from_user is None:
        return
    user_id = message.from_user.id
    okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
    okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
    if not is_allowed_user(okx_uid):
        print("접근 권한 없음. trading.py", okx_uid)
        await message.reply("⛔ 접근 권한이 없습니다.")
        return
    tp_state = 0
    try:
        # 텔레그램 ID를 OKX UID로 변환
        okx_uid = await get_okx_uid_from_telegram_id(str(user_id))
        if not is_allowed_user(okx_uid):
            print("접근 권한 없음. trading.py", okx_uid)
            await message.reply("⛔ 접근 권한이 없습니다.")
            return
        
        # 1. 기본 트레이딩 상태 확인 (텔레그램 ID)
        trading_status = await redis.get(f"user:{user_id}:trading:status")
        
        # 바이트 문자열을 디코딩
        if isinstance(trading_status, bytes):
            trading_status = trading_status.decode('utf-8')
        
        # OKX UID가 있는 경우 해당 상태도 확인
        okx_trading_status = None
        if okx_uid:
            okx_trading_status = await redis.get(f"user:{okx_uid}:trading:status")
            
            # 바이트 문자열을 디코딩
            if isinstance(okx_trading_status, bytes):
                okx_trading_status = okx_trading_status.decode('utf-8')
        
        # 둘 중 하나라도 running이면 실행 중으로 간주
        status_emoji = "🟢" if (trading_status == "running" or (okx_uid and okx_trading_status == "running")) else "🔴"

        # 2. 현재 활성 심볼/타임프레임 조회 (OKX UID로 조회)
        active_key = f"user:{okx_uid if okx_uid else user_id}:preferences"
        preferences = await redis.hgetall(active_key)
        symbol = preferences.get('symbol', '')
        timeframe = preferences.get('timeframe', '')

        # 3. 현재 포지션 정보 조회 (롱과 숏 모두)
        position_info_list = []
        if symbol:
            # API 키 조회 (raise_on_missing=False로 설정하여 키가 없어도 None 반환)
            api_keys = await get_user_api_keys(str(user_id), raise_on_missing=False)
            if api_keys and all([api_keys.get('api_key'), api_keys.get('api_secret'), api_keys.get('passphrase')]):
                # OKX 클라이언트 생성
                client = ccxt.okx({
                    'apiKey': api_keys.get('api_key'),
                    'secret': api_keys.get('api_secret'),
                    'password': api_keys.get('passphrase'),
                    'enableRateLimit': True,
                    'options': {'defaultType': 'swap'}
                })

                try:
                    await client.load_markets()
                    positions = await client.fetch_positions([symbol], params={'instType': 'SWAP'})

                    # contracts > 0인 포지션만 필터링
                    active_positions = [pos for pos in positions if float(pos['contracts']) > 0]
                    logger.info(f"Active positions: {active_positions}")

                    for position in active_positions:
                        # Redis에 포지션 정보 저장/업데이트
                        position_key = f"user:{user_id}:position:{symbol}:{position['side']}"
                        dca_count_key = f"user:{user_id}:position:{symbol}:{position['side']}:dca_count"
                        
                        # Redis 키 타입 확인 및 디버깅
                        key_type = await redis.type(position_key)
                        existing_data = {}
                        # key_type이 문자열일 수도 있으므로 조건 수정
                        if key_type in [b'hash', 'hash']:
                            existing_data = await redis.hgetall(position_key)
                            
                            # bytes 타입 처리
                            existing_data = {
                                k.decode('utf-8') if isinstance(k, bytes) else k: 
                                v.decode('utf-8') if isinstance(v, bytes) else v 
                                for k, v in existing_data.items()
                            }
                        position_qty = float(position['contracts']) * float(position['contractSize'])
                        # 새로운 포지션 정보 구성
                        print(f"🔍 position: {position}")
                        try:
                                liquidation_price = float(position['liquidationPrice']) if position['liquidationPrice'] is not None else 0.0
                                rounded_liq_price = await round_to_tick_size(liquidation_price, float(position['markPrice']), symbol)
                        except Exception as e:
                            logger.error(f"청산가 계산 오류: {str(e)}")
                            liquidation_price = 0.0
                            rounded_liq_price = 0.0
                        position_data = {
                            'side': position['side'],
                            'size': str(float(position['contracts'])),
                            'contracts': str(float(position['contracts'])),
                            'contracts_amount': str(float(position['contracts'])),
                            'position_qty': str(position_qty),
                            'contractSize': str(float(position['contractSize'])),
                            'entry_price': str(float(position['entryPrice'])),
                            'mark_price': str(float(position['markPrice'])),
                            'unrealized_pnl': str(float(position['unrealizedPnl'])),
                            'leverage': str(float(position['leverage'])),
                            'liquidation_price': str(rounded_liq_price),
                            'margin_mode': position['marginMode'],
                            'updated_at': str(int(time.time()))
                        }

                        # position_info 객체 생성 전에 existing_data 확인
                        
                        position_info = {
                            'side': position['side'],
                            'size': float(position['contracts']),
                            'contracts': float(position['contracts']),
                            'contracts_amount': float(position['contracts']),
                            'position_qty': float(position_qty),
                            'contractSize': float(position['contractSize']),
                            'entry_price': float(position['entryPrice']),
                            'mark_price': float(position['markPrice']),
                            'unrealized_pnl': float(position['unrealizedPnl']),
                            'leverage': float(position['leverage']),
                            'liquidation_price': rounded_liq_price if rounded_liq_price else None,
                            'margin_mode': position['marginMode'],
                            'sl_price': existing_data.get('sl_price') if existing_data.get('sl_price') else None,
                            'sl_order_id': existing_data.get('sl_order_id', ''),
                            'tp_prices': existing_data.get('tp_data', '[]')
                        }
                        # closeOrderAlgo 정보 처리 추가

                        # TP/SL 정보 처리
                        if key_type == b'hash':
                            # TP 데이터 처리
                            tp_data = existing_data.get('tp_data')
                            if tp_data:
                                if isinstance(tp_data, bytes):
                                    tp_data = tp_data.decode('utf-8')
                                try:
                                    tp_info = json.loads(tp_data)
                                    position_info['tp_info'] = tp_info
                                except json.JSONDecodeError:
                                    pass
                                    
                            # SL 데이터 처리
                            sl_data = existing_data.get('sl_data')
                            if sl_data:
                                if isinstance(sl_data, bytes):
                                    sl_data = sl_data.decode('utf-8')
                                try:
                                    sl_info = json.loads(sl_data)
                                    position_info['sl_info'] = sl_info
                                except json.JSONDecodeError:
                                    pass
                        
                        position_info_list.append(position_info)
                        
                        # TP 상태 정보 가져오기
                        position_key = f"user:{user_id}:position:{symbol}:{position['side']}"
                        position_data = await redis.hgetall(position_key)
                        if position_data:
                            tp_state = position_data.get('tp_state', '0')
                            # 문자열을 bool로 변환
                            get_tp1 = position_data.get('get_tp1', 'false').lower() == 'true'
                            get_tp2 = position_data.get('get_tp2', 'false').lower() == 'true'
                            get_tp3 = position_data.get('get_tp3', 'false').lower() == 'true'
                            dca_count = await redis.get(dca_count_key)
                            print(f" 상태 출력 ! : {tp_state}, {get_tp1}, {get_tp2}, {get_tp3}, {dca_count}")

                except ccxt.PermissionDenied as e:
                    # IP 화이트리스트 오류 처리
                    error_message = str(e)
                    if "50110" in error_message or "IP whitelist" in error_message:
                        await message.reply(
                            "⚠️ API 접근 권한 오류\n"
                            "─────────────────────\n"
                            "귀하의 IP 주소가 OKX API 키의 화이트리스트에 등록되어 있지 않습니다.\n\n"
                            "해결 방법:\n"
                            "1. OKX 웹사이트에 로그인\n"
                            "2. API 관리 페이지로 이동\n"
                            "3. 해당 API 키의 IP 화이트리스트에 현재 IP 주소를 추가\n\n"
                            f"상세 오류: {error_message}"
                        )
                    else:
                        await message.reply(
                            f"⚠️ API 접근 권한 오류\n"
                            f"─────────────────────\n"
                            f"{error_message}"
                        )
                    logger.error(f"PermissionDenied error for user {user_id}: {error_message}")
                    return

                finally:
                    try:
                        await client.close()
                    except Exception as e:
                        logger.warning(f"CCXT 클라이언트 종료 중 오류 발생: {str(e)}")

        symbol_str = symbol.split('-')[0] if symbol else ""
        
        # 메시지 구성
        
        message_text = f"🔹 트레이딩 상태: {status_emoji}\n"
        message_text += f"🔹 심볼: {symbol_str}\n"
        message_text += f"🔹 타임프레임: {timeframe}\n\n"
        message_text += "-----------------------------------\n"
        for pos in position_info_list:
            main_position_side_key = f"user:{user_id}:position:{symbol}:main_position_direction"
            main_position_side = await redis.get(main_position_side_key)
            unrealized_pnl = float(pos['unrealized_pnl'])
            dca_key = f"user:{user_id}:position:{symbol}:{pos['side']}:dca_count"
            dca_count = await redis.get(dca_key)
            pnl_emoji = "📈" if unrealized_pnl > 0 else "📉"
            
            message_text += f"포지션: {pos['side'].upper()}\n\n"
            try:
                if main_position_side == pos['side']:
                    message_text += f"진입 회차: {dca_count}\n"
            except Exception as e:
                logger.error(f"진입 횟수 표시 오류: {str(e)}")
            message_text += f"수량: {float(pos['position_qty']):.4g} {symbol_str}\n"
            message_text += f"진입가: {float(pos['entry_price']):,.2f}\n"
            try:
                if pos['liquidation_price'] != '0' and pos['liquidation_price'] != '' and pos['liquidation_price'] != None:
                    message_text += f"청산가: {float(pos['liquidation_price']):,.2f}\n"
            except Exception as e:
                logger.error(f"청산가 표시 오류: {str(e)}")
            message_text += f"현재가: {float(pos['mark_price']):,.2f}\n"
            message_text += f"레버리지: {pos['leverage']}x\n"
            message_text += f"미실현 손익: {pnl_emoji} {float(unrealized_pnl):,.2f} USDT\n\n"
            
            # SL 정보 추가
            if pos.get('sl_price') and pos['sl_price'] != '':
                message_text += f"손절가: {float(pos['sl_price']):,.2f}\n"
            
            # TP 정보 추가
            tp_prices = pos.get('tp_prices', '')
            if tp_prices:
                try:
                    tp_list = json.loads(tp_prices)
                    for tp in tp_list:
                        tp_num = tp['level']
                        tp_status = "✅" if int(tp_state) >= int(tp_num) else "⏳"
                        message_text += f"TP{tp_num}: {tp['price']} {tp_status}\n"
                except json.JSONDecodeError:
                    logger.error(f"TP 가격 파싱 오류: {tp_prices}")
            
            message_text += "\n"
            message_text += "-----------------------------------\n"

        await message.reply(message_text)

    except Exception as e:
        logger.error(f"Status command error: {str(e)}")
        traceback.print_exc()
        await log_error(
            error=e,
            user_id=str(user_id),
            additional_info={
                "command": "status",
                "timestamp": datetime.now().isoformat()
            }
        )
        await message.reply(
            "⚠️ 상태 정보 조회 중 오류가 발생했습니다.\n"
            "잠시 후 다시 시도해주세요."
        )
        
@router.callback_query(lambda c: c.data.startswith('trade_'))
async def button_callback(callback: types.CallbackQuery) -> None:
    """인라인 버튼 콜백 처리"""
    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None or callback.data is None:
        return
    user_id = callback.from_user.id
    data = callback.data

    try:
        if data.startswith('trade_'):
            action = data.split('_')[1]
            if action == 'start':
                #await redis_client.set(f"user:{user_id}:trading:status", "running")
                await callback.answer("트레이딩을 시작합니다.")
                await callback.message.edit_text("자동 트레이딩이 시작되었습니다.")
            elif action == 'stop':
                await redis.set(f"user:{user_id}:trading:status", "stopped")
                await callback.answer("트레이딩을 중지합니다.")
                await callback.message.edit_text("자동 트레이딩이 중지되었습니다.")
        else:
            await callback.answer("알 수 없는 명령입니다.")
            
    except Exception as e:
        logger.error(f"콜백 처리 중 오류 발생: {str(e)}")
        await callback.answer("오류가 발생했습니다.")
        
        
@router.callback_query(lambda c: c.data == "back_to_timeframe")
async def handle_back_to_timeframe(callback: types.CallbackQuery) -> None:
    redis = await get_redis_client()
    if not isinstance(callback.message, Message):
        return
    if callback.from_user is None:
        return
    try:
        user_id = callback.from_user.id
        # 기존 선택된 타임프레임 삭제
        await redis.delete(f"user:{user_id}:selected_timeframe")
        
        # 이미 선택된 심볼 가져오기 (없으면 빈 문자열)
        selected_symbol = await redis.get(f"user:{user_id}:selected_symbol") or ""
        
        # 타임프레임 옵션 리스트
        timeframes = ['1m', '3m', '5m', '15m', '30m', '1H', '4H']
        timeframe_buttons = [
            [types.InlineKeyboardButton(text=tf, callback_data=f"select_timeframe_{tf}")]
            for tf in timeframes
        ]
        
        # 재설정 버튼 추가
        reset_button = [types.InlineKeyboardButton(text="🔄 처음부터 다시 설정", callback_data="trade_reset")]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=timeframe_buttons + [reset_button])
        
        # 타임프레임 선택 화면 표시
        await callback.message.edit_text(
            f"📊 타임프레임 재선택\n\n"
            f"선택된 종목: {selected_symbol}\n"
            "원하는 타임프레임을 선택해주세요:",
            reply_markup=keyboard
        )
        await callback.answer("타임프레임 선택 화면으로 이동합니다.")
        
    except Exception as e:
        logger.error(f"Error handling back_to_timeframe: {str(e)}")
        await callback.answer("타임프레임 선택 화면 전환 중 오류 발생")
        
        
# src/bot/commands/trading.py에 추가

@router.message(Command("sl"))
async def sl_command(message: types.Message) -> None:
    """SL 설정 명령어"""
    redis = await get_redis_client()
    if message.from_user is None or message.text is None:
        return
    user_id = message.from_user.id
    okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
    okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
    if not is_allowed_user(okx_uid):
        print("접근 권한 없음. trading.py", okx_uid)
        await message.reply("⛔ 접근 권한이 없습니다.")
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if not args:
        # 명령어 도움말 표시
        help_text = (
            "🛑 스탑로스(SL) 설정 명령어 사용법:\n\n"
            "1️⃣ SL 설정하기:\n"
            "/sl set [심볼] [방향] [가격]\n"
            "예: /sl set BTCUSDT long 38000\n\n"
            "2️⃣ SL 조회하기:\n"
            "/sl show [심볼] [방향]\n"
            "예: /sl show BTCUSDT long\n\n"
            "3️⃣ SL 삭제하기:\n"
            "/sl clear [심볼] [방향]\n"
            "예: /sl clear BTCUSDT long\n\n"
            "💡 방향은 'long' 또는 'short'로 입력해주세요."
        )
        await message.reply(help_text)
        return
    
    command = args[0].lower()
    
    if command == "set" and len(args) >= 4:
        # SL 설정
        symbol = args[1].upper()
        direction = args[2].lower()
        
        if direction not in ["long", "short"]:
            await message.reply("❌ 방향은 'long' 또는 'short'만 가능합니다.")
            return
        
        try:
            # SL 가격 파싱
            sl_price = float(args[3])
            
            # 방향에 따라 SL 가격 검증
            position_key = f"user:{user_id}:position:{symbol}:{direction}"
            position_data = await redis.hgetall(position_key)
            
            if not position_data:
                await message.reply(f"❌ {symbol}에 {direction} 포지션이 없습니다.")
                return
            
            entry_price = float(position_data.get("entry_price", "0"))
            
            if entry_price <= 0:
                await message.reply(f"❌ 진입가격을 확인할 수 없습니다.")
                return
            
            # 롱: SL은 진입가 이하이어야 함
            # 숏: SL은 진입가 이상이어야 함
            if direction == "long":
                if sl_price >= entry_price:
                    await message.reply(f"❌ 롱 포지션의 SL은 진입가({entry_price}) 이하여야 합니다.")
                    return
            else:  # short
                if sl_price <= entry_price:
                    await message.reply(f"❌ 숏 포지션의 SL은 진입가({entry_price}) 이상이어야 합니다.")
                    return
            
            # SL 정보 저장
            await redis.hset(position_key, "sl_price", str(sl_price))
            await redis.hset(position_key, "sl_triggered", "false")
            
            # 손실 계산
            loss_percent = 0.0
            if entry_price > 0:
                if direction == "long":
                    loss_percent = (entry_price - sl_price) / entry_price * 100
                else:
                    loss_percent = (sl_price - entry_price) / entry_price * 100
            
            # 응답 메시지
            response = (
                f"✅ {symbol} {direction} 포지션의 스탑로스 설정 완료!\n\n"
                f"진입가: {entry_price:.2f}\n"
                f"SL 가격: {sl_price:.2f}\n"
                f"예상 손실: {loss_percent:.2f}%"
            )
            
            await message.reply(response)
            
        except (ValueError, IndexError) as e:
            await message.reply(f"❌ SL 설정 중 오류가 발생했습니다: {str(e)}")
            return
            
    elif command == "show" and len(args) >= 3:
        # SL 조회
        symbol = args[1].upper()
        direction = args[2].lower()
        
        if direction not in ["long", "short"]:
            await message.reply("❌ 방향은 'long' 또는 'short'만 가능합니다.")
            return
        
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        position_data = await redis.hgetall(position_key)
        
        if not position_data:
            await message.reply(f"❌ {symbol}에 {direction} 포지션이 없습니다.")
            return
        
        try:
            entry_price = float(position_data.get("entry_price", "0"))
            current_price = float(position_data.get("current_price", "0"))
            
            if "sl_price" not in position_data:
                await message.reply(f"❌ {symbol} {direction} 포지션에 설정된 SL이 없습니다.")
                return
                
            sl_price = float(position_data.get("sl_price", "0"))
            sl_triggered = position_data.get("sl_triggered", "false").lower() == "true"
            
            # 손실 계산
            loss_percent = 0.0
            if entry_price > 0:
                if direction == "long":
                    loss_percent = (entry_price - sl_price) / entry_price * 100
                else:
                    loss_percent = (sl_price - entry_price) / entry_price * 100
            
            # 현재가와의 거리 계산
            distance_percent = 0.0
            if current_price > 0:
                if direction == "long":
                    distance_percent = (current_price - sl_price) / current_price * 100
                else:
                    distance_percent = (sl_price - current_price) / current_price * 100
            
            # SL 상태 표시
            response = f"🛑 {symbol} {direction.upper()} 포지션 스탑로스 상태:\n\n"
            response += f"📌 진입가: {entry_price:.2f}\n"
            response += f"🔄 현재가: {current_price:.2f}\n"
            response += f"⚠️ SL 가격: {sl_price:.2f}\n"
            response += f"📉 예상 손실: {loss_percent:.2f}%\n"
            response += f"📏 현재가와의 거리: {distance_percent:.2f}%\n"
            
            if sl_triggered:
                response += "⚠️ 스탑로스 도달됨! 주문이 실행되었을 수 있습니다."
            else:
                response += "✅ 스탑로스 대기 중"
            
            await message.reply(response)
            
        except Exception as e:
            logger.error(f"Error in sl show command: {e}")
            await message.reply(f"❌ SL 정보를 조회하는 중 오류가 발생했습니다.")
            
    elif command == "clear" and len(args) >= 3:
        # SL 삭제
        symbol = args[1].upper()
        direction = args[2].lower()
        
        if direction not in ["long", "short"]:
            await message.reply("❌ 방향은 'long' 또는 'short'만 가능합니다.")
            return
        
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        position_data = await redis.hgetall(position_key)
        
        if not position_data:
            await message.reply(f"❌ {symbol}에 {direction} 포지션이 없습니다.")
            return
        
        # SL 정보 삭제
        await redis.hdel(position_key, "sl_price", "sl_triggered")
        
        await message.reply(f"✅ {symbol} {direction} 포지션의 스탑로스 설정이 삭제되었습니다.")
        
    else:
        await message.reply("❌ 명령어 형식이 올바르지 않습니다. '/sl'로 사용법을 확인하세요.")
        
        
# src/bot/commands/trading.py에 추가

@router.message(Command("tp"))
async def tp_command(message: types.Message) -> None:
    """TP 설정 명령어"""
    redis = await get_redis_client()
    if message.from_user is None or message.text is None:
        return
    user_id = message.from_user.id
    okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
    okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if not args:
        # 명령어 도움말 표시
        help_text = (
            "🎯 TP(Take Profit) 설정 명령어 사용법:\n\n"
            "1️⃣ TP 설정하기:\n"
            "/tp set [심볼] [방향] [TP1] [TP2] [TP3] [사이즈1] [사이즈2] [사이즈3]\n"
            "예: /tp set BTCUSDT long 40000 42000 45000 30 30 40\n\n"
            "2️⃣ TP 조회하기:\n"
            "/tp show [심볼] [방향]\n"
            "예: /tp show BTCUSDT long\n\n"
            "3️⃣ TP 삭제하기:\n"
            "/tp clear [심볼] [방향]\n"
            "예: /tp clear BTCUSDT long\n\n"
            "💡 방향은 'long' 또는 'short'로 입력해주세요.\n"
            "💰 사이즈는 각 TP에서 정리할 포지션 비율(%)입니다."
        )
        await message.reply(help_text)
        return
    
    command = args[0].lower()
    
    if command == "set" and len(args) >= 8:
        # TP 설정
        symbol = args[1].upper()
        direction = args[2].lower()
        
        if direction not in ["long", "short"]:
            await message.reply("❌ 방향은 'long' 또는 'short'만 가능합니다.")
            return
        
        try:
            # TP 가격 파싱
            tp_prices = [float(args[3]), float(args[4]), float(args[5])]
            tp_sizes = [float(args[6]), float(args[7]), float(args[8])]
            
            # 사이즈 비율 합계 체크
            if sum(tp_sizes) != 100:
                await message.reply("❌ TP 사이즈 비율의 합은 100%가 되어야 합니다.")
                return
            
            # 방향에 따라 TP 가격 검증
            position_key = f"user:{user_id}:position:{symbol}:{direction}"
            position_data = await redis.hgetall(position_key)
            
            if not position_data:
                await message.reply(f"❌ {symbol}에 {direction} 포지션이 없습니다.")
                return
            
            entry_price = float(position_data.get("entry_price", "0"))
            
            if entry_price <= 0:
                await message.reply(f"❌ 진입가격을 확인할 수 없습니다.")
                return
            
            # 롱: TP는 진입가 이상이어야 함
            # 숏: TP는 진입가 이하이어야 함
            if direction == "long":
                for tp in tp_prices:
                    if tp <= entry_price:
                        await message.reply(f"❌ 롱 포지션의 TP는 진입가({entry_price}) 이상이어야 합니다.")
                        return
                # 오름차순 정렬
                sorted_pairs = sorted(zip(tp_prices, tp_sizes))
                tp_prices = [p for p, s in sorted_pairs]
                tp_sizes = [s for p, s in sorted_pairs]
            else:  # short
                for tp in tp_prices:
                    if tp >= entry_price:
                        await message.reply(f"❌ 숏 포지션의 TP는 진입가({entry_price}) 이하이어야 합니다.")
                        return
                # 내림차순 정렬
                sorted_pairs = sorted(zip(tp_prices, tp_sizes), reverse=True)
                tp_prices = [p for p, s in sorted_pairs]
                tp_sizes = [s for p, s in sorted_pairs]
            
            # TP 정보 저장
            tp_hit_status = [False] * len(tp_prices)
            
            await redis.hset(position_key, "tp_prices", json.dumps(tp_prices))
            await redis.hset(position_key, "tp_sizes", json.dumps(tp_sizes))
            await redis.hset(position_key, "tp_hit_status", json.dumps(tp_hit_status))
            
            # 응답 메시지
            response = (
                f"✅ {symbol} {direction} 포지션의 TP 설정 완료!\n\n"
                f"진입가: {entry_price:.2f}\n"
                f"TP1: {tp_prices[0]:.2f} ({tp_sizes[0]:.1f}%)\n"
                f"TP2: {tp_prices[1]:.2f} ({tp_sizes[1]:.1f}%)\n"
                f"TP3: {tp_prices[2]:.2f} ({tp_sizes[2]:.1f}%)"
            )
            
            await message.reply(response)
            
        except (ValueError, IndexError) as e:
            await message.reply(f"❌ TP 설정 중 오류가 발생했습니다: {str(e)}")
            return
            
    elif command == "show" and len(args) >= 3:
        # TP 조회
        symbol = args[1].upper()
        direction = args[2].lower()
        
        if direction not in ["long", "short"]:
            await message.reply("❌ 방향은 'long' 또는 'short'만 가능합니다.")
            return
        
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        position_data = await redis.hgetall(position_key)
        
        if not position_data:
            await message.reply(f"❌ {symbol}에 {direction} 포지션이 없습니다.")
            return
        
        try:
            entry_price = float(position_data.get("entry_price", "0"))
            current_price = float(position_data.get("current_price", "0"))
            
            tp_prices = []
            tp_sizes = []
            tp_hit_status = []
            
            if "tp_prices" in position_data:
                tp_prices = json.loads(position_data["tp_prices"])
            
            if "tp_sizes" in position_data:
                tp_sizes = json.loads(position_data["tp_sizes"])
                
            if "tp_hit_status" in position_data:
                tp_hit_status = json.loads(position_data["tp_hit_status"])
            
            if not tp_prices:
                await message.reply(f"❌ {symbol} {direction} 포지션에 설정된 TP가 없습니다.")
                return
            
            # TP 상태 표시
            response = f"🎯 {symbol} {direction.upper()} 포지션 TP 상태:\n\n"
            response += f"📌 진입가: {entry_price:.2f}\n"
            response += f"🔄 현재가: {current_price:.2f}\n"
            
            direction_emoji = "🟢" if direction == "long" else "🔴"
            
            for i, (price, size) in enumerate(zip(tp_prices, tp_sizes)):
                hit_status = "✅ 달성" if (i < len(tp_hit_status) and tp_hit_status[i]) else "⏳ 대기"
                
                # 현재가와의 거리 계산
                distance = ""
                if current_price > 0:
                    if direction == "long":
                        diff_percent = (float(price) - current_price) / current_price * 100
                        distance = f"(현재가에서 +{diff_percent:.2f}% 떨어짐)"
                    else:
                        diff_percent = (current_price - float(price)) / current_price * 100
                        distance = f"(현재가에서 -{diff_percent:.2f}% 떨어짐)"
                
                response += f"TP{i+1}: {direction_emoji} {float(price):.2f} ({float(size):.1f}%) {hit_status} {distance}\n"
            
            await message.reply(response)
            
        except Exception as e:
            logger.error(f"Error in tp show command: {e}")
            await message.reply(f"❌ TP 정보를 조회하는 중 오류가 발생했습니다.")
            
    elif command == "clear" and len(args) >= 3:
        # TP 삭제
        symbol = args[1].upper()
        direction = args[2].lower()
        
        if direction not in ["long", "short"]:
            await message.reply("❌ 방향은 'long' 또는 'short'만 가능합니다.")
            return
        
        position_key = f"user:{user_id}:position:{symbol}:{direction}"
        position_data = await redis.hgetall(position_key)
        
        if not position_data:
            await message.reply(f"❌ {symbol}에 {direction} 포지션이 없습니다.")
            return
        
        # TP 정보 삭제
        await redis.hdel(position_key, "tp_prices", "tp_sizes", "tp_hit_status")
        
        await message.reply(f"✅ {symbol} {direction} 포지션의 모든 TP 설정이 삭제되었습니다.")
        
    else:
        await message.reply("❌ 명령어 형식이 올바르지 않습니다. '/tp'로 사용법을 확인하세요.")
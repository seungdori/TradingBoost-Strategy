# src/bot/command/dual_side_settings.py

import asyncio
import json
import traceback
from typing import Any, Dict, Optional

import aiohttp
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
import os

from HYPERRSI.src.core.config import settings
from shared.database.redis_helper import get_redis_client
from shared.helpers.user_id_resolver import resolve_user_identifier
from shared.logging import get_logger

router = Router()
logger = get_logger(__name__)

# API 엔드포인트 설정
try:
    API_PORT = 8000
except AttributeError:
    API_PORT = 8000

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api")

allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267","586156710277369942"]
def is_allowed_user(user_id: Optional[str]) -> bool:
    """허용된 사용자인지 확인"""
    if user_id is None:
        return False
    return str(user_id) in allowed_uid

# -----------------
# FSM States (추가)
# -----------------
class DualSideSettingsState(StatesGroup):
    # 심볼 선택 상태 (멀티심볼 지원)
    waiting_for_symbol_selection = State()
    waiting_for_trigger = State()
    waiting_for_ratio_type = State()
    waiting_for_ratio_value = State()
    waiting_for_tp_type = State()
    waiting_for_tp_value = State()
    waiting_for_sl_type = State()
    waiting_for_sl_value = State()
    # 추가: '기존 포지션 SL'에서 사용할 TP 인덱스를 입력받기
    waiting_for_sl_tp_index = State()
    # 추가: 양방향 매매 피라미딩 제한 설정
    waiting_for_pyramiding_limit = State()
    # 추가: 양방향 포지션 익절 시 메인 포지션 종료 여부
    waiting_for_close_main_position = State()

async def get_okx_uid_from_telegram_id(telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        Optional[str]: OKX UID or None
    """
    try:
        redis = await get_redis_client()
        # 텔레그램 ID로 OKX UID 조회
        okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            return okx_uid.decode() if isinstance(okx_uid, bytes) else okx_uid
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID를 OKX UID로 변환 중 오류: {str(e)}")
        return None

async def get_identifier(user_id: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 확인하고 적절한 OKX UID를 반환

    Args:
        user_id: 텔레그램 ID 또는 OKX UID

    Returns:
        str: OKX UID

    Note:
        이 함수는 shared.helpers.user_id_resolver.resolve_user_identifier()를 사용합니다.
    """
    return await resolve_user_identifier(str(user_id))

# API 요청 헬퍼 함수
async def get_dual_side_settings_api(user_id: str, symbol: str | None = None) -> Dict[str, Any]:
    """
    API를 통해 양방향 매매 설정을 조회합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 조회
    - symbol이 None이면 글로벌 설정 조회
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(str(user_id))

    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE_URL}/settings/{okx_uid}/dual_side"
        # 심볼 파라미터 추가
        if symbol:
            url += f"?symbol={symbol}"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data: Dict[str, Any] = await response.json()
                    settings: Dict[str, Any] = data["settings"]
                    return settings
                else:
                    error_text = await response.text()
                    logger.error(f"API 요청 실패 ({response.status}): {error_text}")
                    return {}
        except Exception as e:
            traceback.print_exc()
            logger.error(f"API 요청 중 오류 발생: {str(e)}")
            # 백업 - 직접 Redis 접근
            return await get_dual_side_settings_fallback(okx_uid, symbol)

async def update_dual_side_settings_api(user_id: str, settings: dict, symbol: str | None = None) -> bool:
    """
    API를 통해 양방향 매매 설정을 업데이트합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 저장
    - symbol이 None이면 글로벌 설정 저장
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(str(user_id))

    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE_URL}/settings/{okx_uid}/dual_side"
        # 심볼 파라미터 추가
        if symbol:
            url += f"?symbol={symbol}"
        try:
            payload = {"settings": settings}
            async with session.put(url, json=payload) as response:
                if response.status == 200:
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"API 요청 실패 ({response.status}): {error_text}")
                    # 백업 - 직접 Redis 접근
                    await update_dual_side_settings_fallback(okx_uid, settings, symbol)
                    return False
        except Exception as e:
            traceback.print_exc()
            logger.error(f"API 요청 중 오류 발생: {str(e)}")
            # 백업 - 직접 Redis 접근
            await update_dual_side_settings_fallback(okx_uid, settings, symbol)
            return False

# 백업 함수 - API 실패 시 직접 Redis 접근
async def get_dual_side_settings_fallback(user_id: str, symbol: str | None = None) -> Dict[str, Any]:
    """
    Redis에서 직접 양방향 매매 설정을 조회합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 조회, 없으면 글로벌 fallback
    - symbol이 None이면 글로벌 설정 조회
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(str(user_id))

    redis = await get_redis_client()

    # 심볼별 또는 글로벌 키 결정
    symbol_settings_key = f"user:{okx_uid}:symbol:{symbol}:dual_side" if symbol else None
    global_settings_key = f"user:{okx_uid}:dual_side"

    settings = None

    # 심볼이 제공된 경우 심볼별 설정 먼저 조회
    if symbol_settings_key:
        settings = await redis.hgetall(symbol_settings_key)

    # 심볼별 설정이 없으면 글로벌 설정 fallback
    if not settings:
        settings = await redis.hgetall(global_settings_key)

    # 문자열 값을 적절한 타입으로 변환
    parsed_settings: Dict[str, Any] = {}
    for key, value in settings.items():
        if value.lower() in ('true', 'false'):
            parsed_settings[key] = value.lower() == 'true'
        else:
            try:
                if '.' in value:
                    parsed_settings[key] = float(value)
                else:
                    parsed_settings[key] = int(value)
            except ValueError:
                parsed_settings[key] = value

    return parsed_settings

async def update_dual_side_settings_fallback(user_id: str, settings: dict, symbol: str | None = None) -> None:
    """
    Redis에 직접 양방향 매매 설정을 저장합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 저장
    - symbol이 None이면 글로벌 설정 저장
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(str(user_id))

    redis = await get_redis_client()

    # 심볼별 또는 글로벌 키 결정
    if symbol:
        settings_key = f"user:{okx_uid}:symbol:{symbol}:dual_side"
    else:
        settings_key = f"user:{okx_uid}:dual_side"

    settings_to_save = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in settings.items()}
    await redis.hset(settings_key, mapping=settings_to_save)

    # JSON 설정에도 use_dual_side_entry 값 동기화 (글로벌 설정의 경우만)
    if 'use_dual_side_entry' in settings and not symbol:
        settings_key_og = f"user:{okx_uid}:settings"
        current_settings = await redis.get(settings_key_og)
        if current_settings:
            settings_dict = json.loads(current_settings)
            settings_dict['use_dual_side_entry'] = settings['use_dual_side_entry']
            await redis.set(settings_key_og, json.dumps(settings_dict))

# =========================
# 심볼 관련 헬퍼 함수
# =========================

async def get_user_active_symbols(user_id: str) -> list[str]:
    """
    사용자의 활성 심볼 목록을 가져옵니다.
    Redis에서 user:{user_id}:active_symbols 또는 프리셋에서 조회
    """
    redis = await get_redis_client()

    # 1. active_symbols에서 조회
    active_symbols_key = f"user:{user_id}:active_symbols"
    active_symbols = await redis.smembers(active_symbols_key)

    if active_symbols:
        return sorted([s.decode() if isinstance(s, bytes) else s for s in active_symbols])

    # 2. 프리셋에서 심볼 목록 조회
    preset_key = f"user:{user_id}:presets"
    preset_data = await redis.get(preset_key)
    if preset_data:
        try:
            presets = json.loads(preset_data.decode() if isinstance(preset_data, bytes) else preset_data)
            symbols = list(presets.keys())
            if symbols:
                return sorted(symbols)
        except json.JSONDecodeError:
            pass

    # 3. 기본 심볼 반환
    return ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]


# =========================
# /dual_settings 명령어
# =========================

@router.message(Command("dual_settings"))
async def dual_side_settings_command(message: types.Message, state: FSMContext) -> None:
    """듀얼 사이드 매매(헷지) 설정 메뉴 - 심볼 선택 UI 포함"""
    if message.from_user is None:
        return
    telegram_id = str(message.from_user.id)

    # 텔레그램 ID로 OKX UID 매핑 조회
    redis = await get_redis_client()
    okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")

    if okx_uid:
        okx_uid = okx_uid.decode() if isinstance(okx_uid, bytes) else okx_uid
    else:
        # 매핑이 없으면 get_identifier로 변환 시도 (fallback)
        okx_uid = await get_identifier(telegram_id)

    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    # 사용자의 활성 심볼 목록 가져오기
    user_id = okx_uid
    symbols = await get_user_active_symbols(user_id)

    # 심볼 선택 키보드 생성
    keyboard_buttons = []

    # 글로벌 설정 버튼 (맨 위에)
    keyboard_buttons.append([
        types.InlineKeyboardButton(text="🌐 글로벌 설정 (모든 심볼 기본값)", callback_data="dual_symbol_global")
    ])

    # 심볼별 버튼 (2열로 배치)
    symbol_row = []
    for symbol in symbols:
        short_name = symbol.replace("-USDT-SWAP", "").replace("-SWAP", "")
        symbol_row.append(
            types.InlineKeyboardButton(text=f"📊 {short_name}", callback_data=f"dual_symbol_{symbol}")
        )
        if len(symbol_row) == 2:
            keyboard_buttons.append(symbol_row)
            symbol_row = []
    if symbol_row:
        keyboard_buttons.append(symbol_row)

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.reply(
        "📊 양방향 매매(헷지) 설정\n"
        "──────────────\n"
        "설정할 심볼을 선택하세요:\n\n"
        "🌐 **글로벌 설정**: 모든 심볼에 적용되는 기본값\n"
        "📊 **심볼별 설정**: 해당 심볼에만 적용 (글로벌 설정 무시)",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# =========================
# 심볼 선택 콜백 핸들러
# =========================

@router.callback_query(F.data.startswith("dual_symbol_"))
async def handle_symbol_selection(callback: types.CallbackQuery, state: FSMContext) -> None:
    """심볼 선택 후 해당 심볼의 양방향 설정 표시"""
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()

    telegram_id = callback.from_user.id
    user_id = await get_identifier(str(telegram_id))

    # 선택된 심볼 파싱
    data = callback.data
    if data == "dual_symbol_global":
        symbol = None  # 글로벌 설정
        symbol_display = "🌐 글로벌"
    else:
        symbol = data.replace("dual_symbol_", "")  # e.g., "BTC-USDT-SWAP"
        symbol_display = f"📊 {symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')}"

    # FSM에 현재 심볼 저장
    await state.update_data(current_symbol=symbol)

    # API를 통해 설정 로드
    settings = await get_dual_side_settings_api(user_id, symbol)
    if not settings:
        # 설정이 없으면 초기화
        await initialize_dual_side_settings(user_id, symbol)
        settings = await get_dual_side_settings_api(user_id, symbol)

    # 현재 설정 표시
    text, kb = await get_current_dual_settings_info(user_id, settings, symbol)
    await callback.message.edit_text(
        f"**{symbol_display} 양방향 매매 설정**\n\n{text}",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# -------------------------------
# "심볼 선택으로 돌아가기" 버튼 핸들러
# -------------------------------
@router.callback_query(F.data == "dual_back_to_symbol_select")
async def handle_back_to_symbol_select(callback: types.CallbackQuery, state: FSMContext) -> None:
    """심볼 선택 화면으로 돌아가는 콜백."""
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()

    telegram_id = callback.from_user.id
    user_id = await get_identifier(str(telegram_id))

    # FSM 상태 클리어
    await state.clear()

    # 사용자의 활성 심볼 목록 가져오기
    symbols = await get_user_active_symbols(user_id)

    # 심볼 선택 키보드 생성
    keyboard_buttons = []

    # 글로벌 설정 버튼 (맨 위에)
    keyboard_buttons.append([
        types.InlineKeyboardButton(text="🌐 글로벌 설정 (모든 심볼 기본값)", callback_data="dual_symbol_global")
    ])

    # 심볼별 버튼 (2열로 배치)
    symbol_row = []
    for symbol in symbols:
        short_name = symbol.replace("-USDT-SWAP", "").replace("-SWAP", "")
        symbol_row.append(
            types.InlineKeyboardButton(text=f"📊 {short_name}", callback_data=f"dual_symbol_{symbol}")
        )
        if len(symbol_row) == 2:
            keyboard_buttons.append(symbol_row)
            symbol_row = []
    if symbol_row:
        keyboard_buttons.append(symbol_row)

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await callback.message.edit_text(
        "📊 양방향 매매(헷지) 설정\n"
        "──────────────\n"
        "설정할 심볼을 선택하세요:\n\n"
        "🌐 **글로벌 설정**: 모든 심볼에 적용되는 기본값\n"
        "📊 **심볼별 설정**: 해당 심볼에만 적용 (글로벌 설정 무시)",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# -------------------------------
# "현재 설정 확인" 버튼 핸들러
# -------------------------------
@router.callback_query(F.data == "dual_show_current")
async def handle_show_current(callback: types.CallbackQuery, state: FSMContext) -> None:
    """현재 설정 정보를 다시 보여주는 콜백."""
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    settings = await get_dual_side_settings_api(user_id, symbol)
    text, kb = await get_current_dual_settings_info(user_id, settings, symbol)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# =========================
# [토글] 양방향 전체 ON/OFF
# =========================
@router.callback_query(F.data == "dual_toggle")
async def handle_dual_toggle(callback: types.CallbackQuery, state: FSMContext) -> None:
    try:
        if callback.from_user is None or callback.message is None:
            return
        if not isinstance(callback.message, Message):
            return
        telegram_id = callback.from_user.id
        # 텔레그램 ID를 OKX UID로 변환
        user_id = await get_identifier(str(telegram_id))

        # FSMContext에서 현재 심볼 가져오기
        data = await state.get_data()
        symbol = data.get('current_symbol')

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)
        is_enabled = settings.get('use_dual_side_entry', False)

        # 상태 변경
        settings['use_dual_side_entry'] = not is_enabled

        # API로 업데이트
        await update_dual_side_settings_api(user_id, settings, symbol)

        status_msg = "비활성화" if is_enabled else "활성화"
        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else " (글로벌)"
        await callback.answer()
        await callback.message.edit_text(
            f"✅ 양방향 매매가 {status_msg} 되었습니다{symbol_display}.\n"
            "원하시는 설정을 계속 진행해주세요.",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await callback.answer("설정 변경 중 오류가 발생했습니다.")

# =========================
# [1] DCA 트리거 설정
# =========================
@router.callback_query(F.data == "dual_set_trigger")
async def handle_trigger_setting(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await callback.message.edit_text(
        "📊 양방향 트리거 (진입 회차) 설정\n"
        "──────────────\n"
        "몇 번째 진입에서 헷지를 열까요?\n"
        "예: 2 ⇒ 두 번째 진입에서 헷지를 열까요?",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
        ])
    )
    await state.set_state(DualSideSettingsState.waiting_for_trigger)

@router.message(DualSideSettingsState.waiting_for_trigger)
async def process_trigger_value(message: types.Message, state: FSMContext) -> None:
    try:
        if message.from_user is None or message.text is None:
            return
        value = int(message.text)
        if not (1 <= value <= 10):
            await message.reply("❌ 1~10 사이 숫자를 입력해주세요.")
            return

        telegram_id = message.from_user.id
        # 텔레그램 ID를 OKX UID로 변환
        user_id = await get_identifier(str(telegram_id))

        # FSMContext에서 현재 심볼 가져오기
        data = await state.get_data()
        symbol = data.get('current_symbol')

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_entry_trigger'] = value

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await message.reply(
            f"✅ 양방향 트리거가 {value}번째 진입으로 설정되었습니다{symbol_display}.",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        # 심볼 정보는 유지하고 상태만 클리어
        await state.set_state(None)

    except ValueError:
        await message.reply("❌ 올바른 숫자를 입력해주세요.")

# =========================
# [2] 진입 비율 (Ratio) 설정
# =========================
@router.callback_query(F.data == "dual_set_ratio")
async def handle_ratio_setting(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="포지션 %", callback_data="ratio_type_percent_of_position"),
            types.InlineKeyboardButton(text="고정 수량", callback_data="ratio_type_fixed_amount")
        ],
        [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
    ])
    await callback.message.edit_text(
        "📈 반대포지션 진입 비율 설정\n"
        "──────────────\n"
        "반대 포지션 진입 수량을 어떤 기준으로 계산할지 선택하세요.",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("ratio_type_"))
async def handle_ratio_type_selection(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return
    ratio_type = callback.data.replace("ratio_type_", "")  # percent_of_position or fixed_amount
    await state.update_data(selected_ratio_type=ratio_type)

    if ratio_type == "percent_of_position":
        text = (
            "📊 [포지션 %] 설정\n"
            "현재 포지션의 몇 %만큼 헷지를 진입할까요?\n"
            "예) 30 입력시, 현재 포지션 사이즈의 30%"
        )
    else:
        text = (
            "📊 [고정 수량] 설정\n"
            "헷지 포지션 진입 시, 고정 몇 개(코인 수량)를 사용할까요?\n"
            "예) 0.1 ⇒ 0.1 BTC"
        )
    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
        ])
    )
    await state.set_state(DualSideSettingsState.waiting_for_ratio_value)

@router.message(DualSideSettingsState.waiting_for_ratio_value)
async def process_ratio_value(message: types.Message, state: FSMContext) -> None:
    try:
        if message.from_user is None or message.text is None:
            return
        value = float(message.text)
        data = await state.get_data()
        ratio_type = data.get('selected_ratio_type', 'percent_of_position')
        symbol = data.get('current_symbol')

        # 간단 검증
        if value <= 0:
            await message.reply("❌ 0보다 큰 값을 입력해주세요.")
            return

        telegram_id = message.from_user.id
        # 텔레그램 ID를 OKX UID로 변환
        user_id = await get_identifier(str(telegram_id))

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_entry_ratio_type'] = ratio_type
        settings['dual_side_entry_ratio_value'] = value

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await message.reply(
            f"✅ 진입 비율이 설정되었습니다{symbol_display}.\n"
            f"값: {value}",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        # 심볼 정보는 유지하고 상태만 클리어
        await state.set_state(None)

    except ValueError:
        await message.reply("❌ 숫자를 입력해주세요.")


# =========================
# [3] TP 설정 (existing_position or percent)
# =========================
@router.callback_query(F.data == "dual_set_tp")
async def handle_tp_setting(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="설정한 마지막 진입에 익절", callback_data="tp_type_last_dca_on_position"),
            types.InlineKeyboardButton(text="기존 포지션 SL에 익절", callback_data="tp_type_existing_position")
        ],
        [
            types.InlineKeyboardButton(text="퍼센트(%) 도달 시 익절", callback_data="tp_type_percent"),
            types.InlineKeyboardButton(text="양방향 익절 사용 안함", callback_data="do_not_close_dual_position")
        ],
        [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
    ])
    await callback.message.edit_text(
        "📈 반대포지션 익절(TP) 설정\n"
        "──────────────\n"
        "아래 중 한 가지를 선택해주세요.\n"
        "• 설정한 마지막 진입에 익절\n"
        "• 기존 포지션 SL에 익절\n"
        "• 퍼센트(%) 도달 시 익절\n"
        "• 양방향 익절 사용 안함",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("tp_type_"))
async def handle_tp_type_selection(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return
    tp_type = callback.data.replace("tp_type_", "")  # existing_position or percent
    await state.update_data(selected_tp_type=tp_type)

    if tp_type == "existing_position":
        # 양방향 포지션 익절 시 메인 포지션 종료 여부 묻기
        await ask_close_main_position(callback, state)
    elif tp_type == "last_dca_on_position":
        # 양방향 포지션 익절 시 메인 포지션 종료 여부 묻기
        await ask_close_main_position(callback, state)
    else:
        # 퍼센트
        await callback.answer()
        await callback.message.edit_text(
            "📊 퍼센트 TP 설정\n"
            "반대포지션 평단가 대비 몇 % 수익 시 익절할까요?\n"
            "예) 1 ⇒ 반대포지션 평단 대비 +1%에 익절",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
            ])
        )
        await state.set_state(DualSideSettingsState.waiting_for_tp_value)

# 추가: 양방향 포지션 익절 시 메인 포지션 종료 여부를 묻는 함수
async def ask_close_main_position(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()

    # 선택한 TP 타입을 저장
    data = await state.get_data()
    tp_type = data.get('selected_tp_type')

    # 양방향 포지션 익절 시 메인 포지션 종료 여부를 묻는 키보드
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="예", callback_data="close_main_yes"),
            types.InlineKeyboardButton(text="아니오", callback_data="close_main_no")
        ],
        [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
    ])

    await callback.message.edit_text(
        "❓ 양방향 포지션을 익절 시, 메인 포지션도 같이 종료하시겠습니까?",
        reply_markup=keyboard
    )

    # 다음 상태로 진행
    await state.set_state(DualSideSettingsState.waiting_for_close_main_position)

# 추가: 양방향 포지션 익절 시 메인 포지션 종료 여부 응답 처리
@router.callback_query(F.data.startswith("close_main_"))
async def handle_close_main_position(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')
    tp_type = data.get('selected_tp_type')

    # 응답 결과 확인 (yes 또는 no)
    close_main = callback.data == "close_main_yes"

    # API로 현재 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    # 설정 업데이트
    settings['dual_side_entry_tp_trigger_type'] = tp_type
    settings['dual_side_entry_tp_value'] = 0
    settings['close_main_on_hedge_tp'] = close_main  # 새로운 설정 추가

    # API로 설정 저장
    await update_dual_side_settings_api(user_id, settings, symbol)

    # 성공 메시지 및 설정 완료
    tp_type_text = "기존 포지션 SL" if tp_type == "existing_position" else "마지막 진입에 익절"
    close_main_text = "함께 종료됨" if close_main else "유지됨"
    symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""

    await callback.message.edit_text(
        f"✅ TP가 [{tp_type_text}] 기준으로 설정되었습니다{symbol_display}.\n"
        f"양방향 포지션 익절 시 메인 포지션은 {close_main_text}으로 설정되었습니다.",
        reply_markup=await get_main_menu_keyboard(user_id, symbol)
    )
    await callback.answer()
    # 심볼 정보는 유지하고 상태만 클리어
    await state.set_state(None)

@router.message(DualSideSettingsState.waiting_for_tp_value)
async def process_tp_value(message: types.Message, state: FSMContext) -> None:
    try:
        if message.from_user is None or message.text is None:
            return
        value = float(message.text)
        if value <= 0:
            await message.reply("❌ 0보다 큰 값을 입력해주세요.")
            return

        telegram_id = message.from_user.id
        # 텔레그램 ID를 OKX UID로 변환
        user_id = await get_identifier(str(telegram_id))

        # FSMContext에서 현재 심볼 가져오기
        data = await state.get_data()
        symbol = data.get('current_symbol')

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_entry_tp_trigger_type'] = 'percent'
        settings['dual_side_entry_tp_value'] = value

        # 양방향 포지션 익절 시 메인 포지션 종료 여부를 묻는 키보드
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="예", callback_data="close_main_percent_yes"),
                types.InlineKeyboardButton(text="아니오", callback_data="close_main_percent_no")
            ]
        ])

        await message.reply(
            "❓ 양방향 포지션을 익절 시, 메인 포지션도 같이 종료하시겠습니까?",
            reply_markup=keyboard
        )

        # 퍼센트 값 저장 (심볼 정보는 이미 state에 있음)
        await state.update_data(tp_percent_value=value)

    except ValueError:
        await message.reply("❌ 숫자를 입력해주세요.")

# 추가: 퍼센트 기준 TP에서 메인 포지션 종료 여부 처리
@router.callback_query(F.data.startswith("close_main_percent_"))
async def handle_close_main_percent(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')
    tp_value = data.get('tp_percent_value')

    # 응답 결과 확인 (yes 또는 no)
    close_main = callback.data == "close_main_percent_yes"

    # API로 현재 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    # 설정 업데이트
    settings['dual_side_entry_tp_trigger_type'] = 'percent'
    settings['dual_side_entry_tp_value'] = tp_value
    settings['close_main_on_hedge_tp'] = close_main  # 새로운 설정 추가

    # API로 설정 저장
    await update_dual_side_settings_api(user_id, settings, symbol)

    # 성공 메시지 및 설정 완료
    close_main_text = "함께 종료됨" if close_main else "유지됨"
    symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""

    await callback.message.edit_text(
        f"✅ TP가 퍼센트 기준으로 설정되었습니다{symbol_display}.\n"
        f"익절 시점: 평단 대비 +{tp_value}%\n"
        f"양방향 포지션 익절 시 메인 포지션은 {close_main_text}으로 설정되었습니다.",
        reply_markup=await get_main_menu_keyboard(user_id, symbol)
    )
    await callback.answer()
    # 심볼 정보는 유지하고 상태만 클리어
    await state.set_state(None)


#==============================================
# STOP LOSS SETTING
#==============================================
@router.callback_query(F.data == "dual_set_sl")
async def handle_sl_setting(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    """SL 설정 메뉴"""
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    # API로 현재 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    # 현재 손절 상태 확인
    is_enabled = settings.get('use_dual_sl', False)

    # 손절 상태에 따른 텍스트 설정
    sl_status_text = "🟢 손절(현재: 켜짐)" if is_enabled else "🔴 손절(현재: 꺼짐)"

    await callback.answer()
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text=sl_status_text, callback_data="sl_toggle")
        ],
        [
            types.InlineKeyboardButton(text="기존 포지션 TP 이용", callback_data="sl_type_existing_position")
        ],
        [
            types.InlineKeyboardButton(text="퍼센트(%)", callback_data="sl_type_percent")
        ],
        [
            types.InlineKeyboardButton(text="현재 설정 확인", callback_data="dual_show_current")
        ],
        [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
    ])
    await callback.message.edit_text(
        "⛔️ 반대포지션 손절(SL) 설정\n"
        "──────────────\n"
        "아래 중 한 가지를 선택해주세요.\n"
        "• 기존 포지션의 TP를 헷지 SL로 사용\n"
        "• 퍼센트(%)로 설정",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "sl_toggle")
async def handle_sl_toggle(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    """손절 On/Off 토글 처리"""
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    # API로 현재 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    # 현재 상태 확인
    is_enabled = settings.get('use_dual_sl', False)

    # 상태 토글
    settings['use_dual_sl'] = not is_enabled

    # API로 설정 저장
    await update_dual_side_settings_api(user_id, settings, symbol)

    status_text = "활성화" if not is_enabled else "비활성화"
    symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
    await callback.answer(f"손절(SL)이 {status_text} 되었습니다{symbol_display}.")

    # 메인 메뉴 다시 표시
    text, kb = await get_current_dual_settings_info(user_id, settings, symbol)
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "sl_type_existing_position")
async def handle_sl_existing_position(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    """
    이전에는 여기서 곧바로 '첫 번째 TP'를 사용했지만,
    지금은 '몇 번째 TP를 사용할지'를 물어보는 과정을 추가.
    """
    await callback.answer()
    # 인라인 버튼(1~3차) 예시:
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="1차 TP", callback_data="sl_type_existing_pos_select_1"),
            types.InlineKeyboardButton(text="2차 TP", callback_data="sl_type_existing_pos_select_2"),
            types.InlineKeyboardButton(text="3차 TP", callback_data="sl_type_existing_pos_select_3"),
        ],
        [
            types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")
        ]
    ])

    await callback.message.edit_text(
        "💡 기존 포지션 TP 중 어느 것을 SL로 사용할까요?\n"
        "아래에서 선택해주세요.",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("sl_type_existing_pos_select_"))
async def handle_sl_existing_select_n(callback: types.CallbackQuery, state: FSMContext) -> None:
    """1차/2차/3차 등 버튼 눌렀을 때"""
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    if not isinstance(callback.message, Message):
        return
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    n_str = callback.data.split("_")[-1]  # '1', '2', '3'
    n = int(n_str)  # 1,2,3

    # API로 현재 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    # 설정 업데이트
    settings['dual_side_entry_sl_trigger_type'] = 'existing_position'
    settings['dual_side_entry_sl_value'] = n
    settings['use_dual_sl'] = True

    # API로 설정 저장
    await update_dual_side_settings_api(user_id, settings, symbol)

    symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
    await callback.answer()
    await callback.message.edit_text(
        f"✅ SL이 [기존 포지션 {n}차 TP]로 설정되었습니다{symbol_display}.\n",
        reply_markup=await get_main_menu_keyboard(user_id, symbol)
    )

# 퍼센트 기준 SL 설정
@router.callback_query(F.data == "sl_type_percent")
async def handle_sl_percent(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    """퍼센트 기준 SL 설정"""
    await callback.answer()
    await callback.message.edit_text(
        "📊 퍼센트 SL 설정\n"
        "──────────────\n"
        "반대포지션 평단가 대비 몇 % 손실 시 손절할까요?\n"
        "예) 2 ⇒ 반대포지션 평단 대비 -2%에 손절",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
        ])
    )
    await state.set_state(DualSideSettingsState.waiting_for_sl_value)

@router.message(DualSideSettingsState.waiting_for_sl_value)
async def process_sl_value(message: types.Message, state: FSMContext) -> None:
    """SL 퍼센트 값 처리"""
    try:
        if message.from_user is None or message.text is None:
            return
        value = float(message.text)
        if value <= 0:
            await message.reply("❌ 0보다 큰 값을 입력해주세요.")
            return

        telegram_id = message.from_user.id
        # 텔레그램 ID를 OKX UID로 변환
        user_id = await get_identifier(str(telegram_id))

        # FSMContext에서 현재 심볼 가져오기
        data = await state.get_data()
        symbol = data.get('current_symbol')

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_entry_sl_trigger_type'] = 'percent'
        settings['dual_side_entry_sl_value'] = value
        settings['use_dual_sl'] = True

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await message.reply(
            f"✅ SL이 퍼센트 기준으로 설정되었습니다{symbol_display}.\n"
            f"손절 시점: 반대포지션 평단 대비 -{value}%",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        # 심볼 정보는 유지하고 상태만 클리어
        await state.set_state(None)

    except ValueError:
        await message.reply("❌ 숫자를 입력해주세요.")



@router.callback_query(F.data == "dual_set_tp_sl_after_all_dca")
async def handle_tp_sl_after_all_dca(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    """최종 진입 후 TP/SL 설정 토글"""
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    # API로 현재 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    # 현재 상태 확인
    is_enabled = settings.get('activate_tp_sl_after_all_dca', False)

    # 상태 토글
    settings['activate_tp_sl_after_all_dca'] = not is_enabled

    # API로 설정 저장
    await update_dual_side_settings_api(user_id, settings, symbol)

    status_text = "활성화" if not is_enabled else "비활성화"
    symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
    await callback.answer(f"최종 진입 후 TP/SL 설정이 {status_text} 되었습니다{symbol_display}.")

    # 메인 메뉴 다시 표시
    text, kb = await get_current_dual_settings_info(user_id, settings, symbol)
    await callback.message.edit_text(text, reply_markup=kb)

# =========================
# [마무리 or 뒤로가기]
# =========================
@router.callback_query(F.data == "dual_settings_done")
async def handle_settings_done(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await callback.message.edit_text(
        "✅ 양방향 매매 설정이 완료되었습니다.\n"
        "추후 다시 /dual_settings 로 설정을 변경할 수 있습니다."
    )

@router.callback_query(F.data == "back_to_dual_menu")
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    # 심볼 표시
    if symbol:
        symbol_display = symbol.replace("-USDT-SWAP", "").replace("-SWAP", "")
        header = f"📊 [{symbol_display}] 메인 메뉴로 돌아갑니다."
    else:
        header = "🌐 [글로벌] 메인 메뉴로 돌아갑니다."

    await callback.message.edit_text(
        header,
        reply_markup=await get_main_menu_keyboard(user_id, symbol)
    )
    await callback.answer()



# =========================
# 메인 메뉴 키보드
# =========================
async def get_main_menu_keyboard(user_id: str, symbol: str | None = None) -> types.InlineKeyboardMarkup:
    """
    메인 메뉴 키보드를 생성합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 표시
    - symbol이 None이면 글로벌 설정 표시
    """
    # API로 설정 가져오기
    settings = await get_dual_side_settings_api(user_id, symbol)

    is_enabled = settings.get('use_dual_side_entry', False)
    after_all_dca_on_off = settings.get('activate_tp_sl_after_all_dca', False)
    after_all_dca_on_off_str = "활성화" if after_all_dca_on_off else "비활성화"
    dca_trigger = settings.get('dual_side_entry_trigger', 2)
    close_main_on_hedge_tp = settings.get('close_main_on_hedge_tp', False)
    ratio_str = f"{float(settings.get('dual_side_entry_ratio_value', 30)):.1f}% (포지션 기준)"
    tp_str = f"퍼센트: ±{settings.get('dual_side_entry_tp_value', 1)}%"
    if settings.get('dual_side_entry_tp_trigger_type', 'last_dca_on_position') == 'existing_position':
        tp_str = "기존포지션의 SL" + (" (메인포지션 종료)" if close_main_on_hedge_tp else "")
    elif settings.get('dual_side_entry_tp_trigger_type', 'last_dca_on_position') == 'last_dca_on_position':
        tp_str = "마지막 진입에 익절" + (" (메인포지션 종료)" if close_main_on_hedge_tp else "")
    sl_str = f"퍼센트: ±{settings.get('dual_side_entry_sl_value', 2)}%"
    if settings.get('dual_side_entry_sl_trigger_type', 'percent') == 'existing_position':
        sl_str = f"기존포지션 {settings.get('dual_side_entry_sl_value', 2)}차 TP"
    pyramiding_limit = settings.get('dual_side_pyramiding_limit', 1)
    pyramiding_limit_str = "미설정" if pyramiding_limit == 0 else f"{pyramiding_limit}회"
    trend_close_enabled = settings.get('dual_side_trend_close', False)
    trend_close_str = "활성화" if trend_close_enabled else "비활성화"

    # 심볼 표시 텍스트
    if symbol:
        symbol_display = symbol.replace("-USDT-SWAP", "").replace("-SWAP", "")
        header_text = f"📊 {symbol_display}"
    else:
        header_text = "🌐 글로벌"

    return types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text=f"양방향 매매 {'비활성화로 변경' if is_enabled else '활성화로 변경'}",
                callback_data="dual_toggle"
            )
        ],
        [types.InlineKeyboardButton(text=f"양방향 매매 시작 기준: {dca_trigger}번째 진입", callback_data="dual_set_trigger")],
        [types.InlineKeyboardButton(text=f"진입 비율 설정: {ratio_str}", callback_data="dual_set_ratio")],
        [types.InlineKeyboardButton(text=f"익절(TP) 설정: {tp_str}", callback_data="dual_set_tp")],
        [types.InlineKeyboardButton(text=f"손절(SL) 설정: {sl_str}", callback_data="dual_set_sl")],
        [types.InlineKeyboardButton(text=f"피라미딩 제한: {pyramiding_limit_str}", callback_data="dual_set_pyramiding_limit")],
        [types.InlineKeyboardButton(text=f"양방향 트랜드 종료 설정: {trend_close_str}", callback_data="dual_set_trend_close")],
        [types.InlineKeyboardButton(text="현재 설정 확인", callback_data="dual_show_current")],
        [types.InlineKeyboardButton(text="🔄 심볼 선택으로 돌아가기", callback_data="dual_back_to_symbol_select")],
        [types.InlineKeyboardButton(text="설정 완료", callback_data="dual_settings_done")]
    ])




# =========================
# 현재 설정 정보를 문자열로 만드는 함수
# =========================
async def get_current_dual_settings_info(user_id: str, settings: Dict[str, Any] | None = None, symbol: str | None = None) -> tuple[str, types.InlineKeyboardMarkup]:
    """
    현재 양방향 매매 설정 정보를 표시합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 표시
    - symbol이 None이면 글로벌 설정 표시
    """
    if settings is None:
        settings = await get_dual_side_settings_api(user_id, symbol)

    # 기본 설정값
    use_dual_side = settings.get('use_dual_side_entry', False)
    trigger = settings.get('dual_side_entry_trigger', '2')
    ratio_type = settings.get('dual_side_entry_ratio_type', 'percent_of_position')
    ratio_value = settings.get('dual_side_entry_ratio_value', '30')
    tp_trigger_type = settings.get('dual_side_entry_tp_trigger_type', 'last_dca_on_position')
    tp_value = settings.get('dual_side_entry_tp_value', '1')
    use_dual_sl = settings.get('use_dual_sl', False)
    sl_trigger_type = settings.get('dual_side_entry_sl_trigger_type', 'percent')
    sl_value = settings.get('dual_side_entry_sl_value', '2')
    activate_tp_sl_after_all_dca = settings.get('activate_tp_sl_after_all_dca', False)
    pyramiding_limit = settings.get('dual_side_pyramiding_limit', '1')
    trend_close = settings.get('dual_side_trend_close', False)
    close_main_on_hedge_tp = settings.get('close_main_on_hedge_tp', False)

    # TP 관련 텍스트
    close_main_text = "메인포지션 종료" if close_main_on_hedge_tp else "메인포지션 유지"
    if tp_trigger_type == 'do_not_close':
        tp_str = "양방향 익절 사용 안함"
    elif tp_trigger_type == 'existing_position':
        tp_str = f"기존포지션의 SL ({close_main_text})"
    elif tp_trigger_type == 'last_dca_on_position':
        tp_str = f"마지막 진입에 익절 ({close_main_text})"
    else:
        tp_str = f"퍼센트: ±{tp_value}% ({close_main_text})"

    # SL 관련 텍스트
    if not use_dual_sl:
        sl_str = "사용 안함"
    elif sl_trigger_type == 'existing_position':
        sl_str = "기존포지션의 TP"
    else:
        sl_str = f"퍼센트: ±{sl_value}%"

    # 트렌드 종료 설정
    trend_close_str = "활성화" if trend_close else "비활성화"

    # 심볼 표시 텍스트
    if symbol:
        symbol_display = symbol.replace("-USDT-SWAP", "").replace("-SWAP", "")
        header = f"📊 [{symbol_display}] 양방향 매매 설정"
    else:
        header = "🌐 [글로벌] 양방향 매매 설정"

    # 설정 정보 텍스트
    text = (
        f"{header}\n"
        f"──────────────\n"
        f"▶ 양방향 매매: {'활성화' if use_dual_side else '비활성화'}\n"
        f"▶ 진입 시점: {trigger}번째 진입\n"
        f"▶ 진입 비율: {ratio_value}% (포지션 기준)\n"
        f"▶ 익절 설정: {tp_str}\n"
        f"▶ 손절 설정: {sl_str}\n"
        f"▶ DCA 완료 후 TP/SL: {'활성화' if activate_tp_sl_after_all_dca else '비활성화'}\n"
        f"▶ 피라미딩 제한: {pyramiding_limit}회\n"
        f"▶ 트랜드 종료 설정: {trend_close_str}\n"
        f"\n원하시는 항목을 선택하세요."
    )

    kb = await get_main_menu_keyboard(user_id, symbol)
    return text, kb


# =========================
# 기본값 초기화
# =========================
async def initialize_dual_side_settings(user_id: str, symbol: str | None = None) -> None:
    """
    API를 통해 듀얼 사이드 설정을 기본값으로 초기화합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 초기화
    - symbol이 None이면 글로벌 설정 초기화
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(str(user_id))

    try:
        # API를 통해 초기화
        async with aiohttp.ClientSession() as session:
            url = f"{API_BASE_URL}/settings/{okx_uid}/dual_side/reset"
            # 심볼 파라미터 추가
            if symbol:
                url += f"?symbol={symbol}"
            async with session.post(url) as response:
                if response.status == 200:
                    symbol_info = f" ({symbol})" if symbol else " (글로벌)"
                    logger.info(f"사용자 {okx_uid}의 양방향 매매 설정이 초기화되었습니다{symbol_info}.")
                else:
                    logger.error(f"API 초기화 실패 ({response.status}): {await response.text()}")
                    # 백업 - 직접 초기화
                    await initialize_dual_side_settings_fallback(okx_uid, symbol)
    except Exception as e:
        logger.error(f"API 초기화 중 오류 발생: {str(e)}")
        # 백업 - 직접 초기화
        await initialize_dual_side_settings_fallback(okx_uid, symbol)

async def initialize_dual_side_settings_fallback(user_id: str, symbol: str | None = None) -> None:
    """
    Redis에 직접 듀얼 사이드 설정을 기본값으로 초기화합니다.

    멀티심볼 지원:
    - symbol이 제공되면 심볼별 설정 초기화
    - symbol이 None이면 글로벌 설정 초기화
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(str(user_id))

    redis = await get_redis_client()

    # 심볼별 또는 글로벌 키 결정
    if symbol:
        settings_key = f"user:{okx_uid}:symbol:{symbol}:dual_side"
    else:
        settings_key = f"user:{okx_uid}:dual_side"
    default_settings = {
        'use_dual_side_entry': 'false',  # 기본값 추가
        'dual_side_entry_trigger': '2',
        'dual_side_entry_ratio_type': 'percent_of_position',
        'dual_side_entry_ratio_value': '30',
        'dual_side_entry_tp_trigger_type': 'last_dca_on_position',
        'dual_side_entry_tp_value': '1',
        'use_dual_sl': 'false',
        'dual_side_entry_sl_trigger_type': 'percent',
        'dual_side_entry_sl_value': '2',
        'activate_tp_sl_after_all_dca': 'false',
        'dual_side_trend_close': 'false',
        'dual_side_pyramiding_limit': '1',
        'close_main_on_hedge_tp': 'false'  # 기본값으로 메인 포지션 유지
    }
    await redis.delete(settings_key)
    await redis.hset(settings_key, mapping=default_settings)

# -------------------------------
# "파라미딩 제한 설정" 버튼 핸들러
# -------------------------------
@router.callback_query(F.data == "dual_set_pyramiding_limit")

async def handle_pyramiding_limit_setting(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await callback.message.edit_text(
        "📊 양방향 매매 피라미딩 제한 설정\n"
        "──────────────\n"
        "양방향 매매에서 최대 몇 회까지 진입할지 설정합니다.\n"
        "1~10 사이의 숫자를 입력해주세요.\n"
        "예: 3 ⇒ 최대 3회까지 반대방향 진입",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="뒤로", callback_data="back_to_dual_menu")]
        ])
    )
    await state.set_state(DualSideSettingsState.waiting_for_pyramiding_limit)

@router.message(DualSideSettingsState.waiting_for_pyramiding_limit)
async def process_pyramiding_limit_value(message: types.Message, state: FSMContext) -> None:
    try:
        if message.from_user is None or message.text is None:
            return
        value = int(message.text)
        if not (1 <= value <= 10):
            await message.reply("❌ 1~10 사이 숫자를 입력해주세요.")
            return

        telegram_id = message.from_user.id
        # 텔레그램 ID를 OKX UID로 변환
        user_id = await get_identifier(str(telegram_id))

        # FSMContext에서 현재 심볼 가져오기
        data = await state.get_data()
        symbol = data.get('current_symbol')

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_pyramiding_limit'] = value

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await message.reply(
            f"✅ 양방향 피라미딩 제한이 {value}회로 설정되었습니다{symbol_display}.",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        # 심볼 정보는 유지하고 상태만 클리어
        await state.set_state(None)

    except ValueError:
        await message.reply("❌ 올바른 숫자를 입력해주세요.")
        
#===============================================================
# 트렌드 클로즈 설정
#===============================================================

@router.callback_query(F.data == "dual_set_trend_close")
async def handle_trend_close_setting(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    try:
        logger.info(f"트렌드 클로즈 설정 메뉴 열기 - 사용자: {user_id}, 심볼: {symbol}")

        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 현재 설정 값 가져오기
        trend_close_enabled = settings.get('dual_side_trend_close', False)
        logger.info(f"현재 트렌드 클로즈 설정값: {trend_close_enabled}")

        status = "활성화" if trend_close_enabled else "비활성화"

        # 현재 상태에 따라 다른 버튼 보여주기
        button_row = []
        if trend_close_enabled:
            # 현재 활성화 상태 -> 비활성화 버튼만 표시
            button_row.append(
                types.InlineKeyboardButton(
                    text="🔴 비활성화로 변경",
                    callback_data="trend_close_disable"
                )
            )
        else:
            # 현재 비활성화 상태 -> 활성화 버튼만 표시
            button_row.append(
                types.InlineKeyboardButton(
                    text="🟢 활성화로 변경",
                    callback_data="trend_close_enable"
                )
            )

        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [button_row[0]],  # 한 버튼만 표시
                [types.InlineKeyboardButton(text="« 뒤로가기", callback_data="back_to_dual_menu")]
            ]
        )

        logger.info(f"트렌드 클로즈 키보드 생성됨, 현재 상태: {status}")

        await callback.message.edit_text(
            f"📊 양방향 트랜드 종료 설정 (현재: {status})\n"
            "──────────────\n"
            "양방향 매매가 진행중일 때, 메인포지션의 방향에서 트랜드로 인한 종료가 발생하면, 양방향 포지션도 클로즈 처리할지 선택합니다.\n"
            "활성화 시 포지션 종료 처리, 비활성화 시 포지션 종료 처리 안함\n",
            reply_markup=keyboard
        )
        logger.info("트렌드 클로즈 설정 메시지 편집 완료")

    except Exception as e:
        logger.error(f"트렌드 클로즈 설정 표시 중 오류: {e}")
        await callback.message.reply(f"트렌드 클로즈 설정 불러오기 중 오류 발생: {e}")

@router.callback_query(F.data == "trend_close_enable")
async def handle_trend_close_enable(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer(text="활성화 처리 중...")
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    try:
        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_trend_close'] = True

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        # 설정이 변경되었음을 알림
        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await callback.message.edit_text(
            f"✅ 트렌드 종료 설정이 활성화로 변경되었습니다{symbol_display}.\n메인 메뉴로 돌아갑니다.",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        logger.info(f"사용자 {user_id}의 트렌드 클로즈 설정이 활성화로 변경되었습니다. 심볼: {symbol}")

    except Exception as e:
        logger.error(f"트렌드 클로즈 활성화 오류: {e}")
        await callback.message.reply(f"트렌드 클로즈 활성화 중 오류 발생: {e}")

@router.callback_query(F.data == "trend_close_disable")
async def handle_trend_close_disable(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    await callback.answer(text="비활성화 처리 중...")
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    try:
        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_trend_close'] = False

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        # 설정이 변경되었음을 알림
        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await callback.message.edit_text(
            f"✅ 트렌드 종료 설정이 비활성화로 변경되었습니다{symbol_display}.\n메인 메뉴로 돌아갑니다.",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        logger.info(f"사용자 {user_id}의 트렌드 클로즈 설정이 비활성화로 변경되었습니다. 심볼: {symbol}")

    except Exception as e:
        logger.error(f"트렌드 클로즈 비활성화 오류: {e}")
        await callback.message.reply(f"트렌드 클로즈 비활성화 중 오류 발생: {e}")

@router.callback_query(F.data == "do_not_close_dual_position")
async def handle_do_not_close_dual_position(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    """양방향 익절을 사용하지 않는 설정 처리"""
    telegram_id = callback.from_user.id
    # 텔레그램 ID를 OKX UID로 변환
    user_id = await get_identifier(str(telegram_id))

    # FSMContext에서 현재 심볼 가져오기
    data = await state.get_data()
    symbol = data.get('current_symbol')

    try:
        # API로 현재 설정 가져오기
        settings = await get_dual_side_settings_api(user_id, symbol)

        # 설정 업데이트
        settings['dual_side_entry_tp_trigger_type'] = 'do_not_close'
        settings['dual_side_entry_tp_value'] = 0
        settings['close_main_on_hedge_tp'] = False

        # API로 설정 저장
        await update_dual_side_settings_api(user_id, settings, symbol)

        # 설정이 변경되었음을 알림
        symbol_display = f" ({symbol.replace('-USDT-SWAP', '').replace('-SWAP', '')})" if symbol else ""
        await callback.message.edit_text(
            f"✅ 양방향 익절이 비활성화되었습니다{symbol_display}.\n메인 메뉴로 돌아갑니다.",
            reply_markup=await get_main_menu_keyboard(user_id, symbol)
        )
        logger.info(f"사용자 {user_id}의 양방향 익절이 비활성화되었습니다. 심볼: {symbol}")

    except Exception as e:
        logger.error(f"양방향 익절 비활성화 오류: {e}")
        await callback.message.reply(f"양방향 익절 비활성화 중 오류 발생: {e}")
        
    
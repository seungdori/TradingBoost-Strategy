# src/bot/commands/settings.py
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from aiogram import types, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import ErrorEvent
from shared.logging import get_logger
from shared.constants.default_settings import (
    DEFAULT_PARAMS_SETTINGS,
    SETTINGS_CONSTRAINTS,
    ENTRY_OPTIONS,
    TP_SL_OPTIONS,
    DIRECTION_OPTIONS,
    PYRAMIDING_TYPES,
    ENTRY_CRITERION_OPTIONS,
    TRAILING_STOP_TYPES,
    ENTRY_AMOUNT_OPTIONS,
    ENTRY_AMOUNT_UNITS
)
import json
from HYPERRSI.src.bot.states.states import SettingStates
from HYPERRSI.src.services.redis_service import RedisService
from HYPERRSI.src.bot.keyboards.settings_keyboard import get_settings_keyboard
from HYPERRSI.src.bot.utils import validator
import traceback  # 상단에 추가
from aiogram.exceptions import TelegramBadRequest
from typing import Optional, Dict, Any



router = Router()
logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()
redis_service = RedisService()

allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267"]

def is_allowed_user(user_id: Optional[str]) -> bool:
    """허용된 사용자인지 확인"""
    if user_id is None:
        return False
    return str(user_id) in allowed_uid

async def get_okx_uid_from_telegram_id(telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        Optional[str]: OKX UID or None if not found
    """
    try:
        # 텔레그램 ID로 OKX UID 조회
        okx_uid = await redis_client.get(f"user:{telegram_id}:okx_uid")
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
    """
    # 11글자 이하면 텔레그램 ID로 간주하고 변환
    if len(str(user_id)) <= 11:
        okx_uid = await get_okx_uid_from_telegram_id(user_id)
        if not okx_uid:
            logger.error(f"텔레그램 ID {user_id}에 대한 OKX UID를 찾을 수 없습니다")
            return str(user_id)  # 변환 실패 시 원래 ID 반환
        return okx_uid
    # 12글자 이상이면 이미 OKX UID로 간주
    return str(user_id)


@router.message(Command("settings"))
async def settings_command(message: types.Message) -> None:
    """설정 메뉴 표시"""
    if message.from_user is None:
        return

    user_id = str(message.from_user.id)

    # 텔레그램 ID인지 OKX UID인지 확인
    user_id = await get_identifier(user_id)

    okx_uid = await redis_client.get(f"user:{user_id}:okx_uid")
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    settings = await redis_service.get_user_settings(user_id)
    if settings is None:
        settings = DEFAULT_PARAMS_SETTINGS.copy()
        await redis_service.set_user_settings(user_id, settings)

    settings['current_category'] = None

    keyboard = get_settings_keyboard(settings)
    await message.answer("변경할 설정 항목을 선택하세요:", reply_markup=keyboard)

        
@router.callback_query(F.data.startswith("direction:"))
async def handle_direction_callback(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    await callback.answer()  # 클라이언트에게 콜백이 처리되었음을 알림

    direction = callback.data.split(":")[1]
    direction_map = {"long": "롱", "short": "숏", "both": "롱숏"}

    user_id = str(callback.from_user.id)
    user_id = await get_identifier(user_id)
    settings = await redis_service.get_user_settings(user_id)
    if settings is None:
        settings = DEFAULT_PARAMS_SETTINGS.copy()

    settings['direction'] = direction_map[direction]
    await redis_service.set_user_settings(user_id, settings)

    keyboard = get_settings_keyboard(settings)
    await callback.message.edit_text(
        f"✅ 진입 방향이 {direction_map[direction]}으로 변경되었습니다.",
        reply_markup=keyboard
    )
@router.callback_query(F.data.startswith("setting:"))
async def handle_setting_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    setting_type = callback.data.split(":")[1]
    callback_parts = callback.data.split(":")
    user_id = str(callback.from_user.id)
    user_id = await get_identifier(user_id)
    settings = await redis_service.get_user_settings(user_id)
    if settings is None:
        settings = DEFAULT_PARAMS_SETTINGS.copy()
    def get_cancel_keyboard():
        return types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ 취소", callback_data="setting:cancel")]
        ])
    print(f"callback_parts: {callback_parts}")

    # 카테고리 선택 처리
    if setting_type == "show_category":
        print(f"callback_parts: {callback_parts}")
        if len(callback_parts) > 2:
            category = callback_parts[2]
            user_id = str(callback.from_user.id)
            user_id = await get_identifier(user_id)
            settings = await redis_service.get_user_settings(user_id)
            if settings is None:
                settings = DEFAULT_PARAMS_SETTINGS.copy()
            
            if category == "main":
                settings.pop('current_category', None)
            else:
                settings['current_category'] = category
                
            keyboard = get_settings_keyboard(settings)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            return
    # 심볼별 투입금액 설정 메뉴 처리
    if setting_type == "symbol_investments":
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="BTC-USDT-SWAP", callback_data="symbol_investment:btc")],
            [types.InlineKeyboardButton(text="ETH-USDT-SWAP", callback_data="symbol_investment:eth")],
            [types.InlineKeyboardButton(text="SOL-USDT-SWAP", callback_data="symbol_investment:sol")],
            [types.InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")]
        ])
        
        # 현재 설정된 투입금액 표시
        btc_investment = settings.get('btc_investment', 100)
        eth_investment = settings.get('eth_investment', 100)
        sol_investment = settings.get('sol_investment', 100)
        
        message_text = (
            "📊 종목별 투입금액 설정\n\n"
            f"• BTC-USDT-SWAP: {btc_investment} USDT\n"
            f"• ETH-USDT-SWAP: {eth_investment} USDT\n"
            f"• SOL-USDT-SWAP: {sol_investment} USDT\n\n"
            "설정할 종목을 선택하세요:"
        )
        
        await callback.message.edit_text(message_text, reply_markup=keyboard)
        return
    
    
    if setting_type == "done":
        await callback.message.delete()  # 메시지 자체를 삭제
        #await callback.message.answer(.")  # 새 메시지로 알림
        return
    if setting_type == "cancel":
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await callback.message.edit_text("설정이 취소되었습니다.", reply_markup=keyboard)
        return  


    setting_prompts = {
        "entry_amount_option": "투입금액 기준을 선택하세요:",
        "investment": "투입금액을 입력하세요 (USDT):",
        "leverage": "레버리지를 입력하세요 (1-125):",
        "pyramiding_limit": "최대 진입 횟수를 입력하세요 (1-10):",
        "entry_multiplier": "추가 진입 배율을 입력하세요 (0.1-5.0):",
        "rsi_length": "RSI 기간을 입력하세요 (1-100):",
        "rsi_oversold": "RSI 과매도 기준값을 입력하세요 (0-100):",
        "rsi_overbought": "RSI 과매수 기준값을 입력하세요 (0-100):",
        "direction": "포지션 방향을 선택하세요:",
        "entry_option": "진입 방법을 선택하세요:",
        "tp_option": "익절 기준을 선택하세요:",
        "entry_criterion": "추가 진입 근거를 선택하세요:",
        "use_sl_on_last": "마지막 진입만 손절 사용 여부:",
        "symbol_investments": "종목별 투입금액을 설정합니다. 설정할 종목을 선택하세요.",
        "cooldown_time": "손절/익절 후 진입을 제한할 시간을 입력하세요(1초-3000초):",
        # ─────────────────────────────
        #  기존 tp1_ratio, tp2_ratio, tp3_ratio 제거,
        #  대신 "tp_ratios" 추가
        # ─────────────────────────────
        "tp_ratios": (
            "TP1, TP2, TP3 비율을 공백으로 구분하여 입력해주세요. (합계 100%)\n"
            "예) `30 30 40`"
        ),
        "tp1_value": "TP1 목표값을 입력하세요:",
        "tp2_value": "TP2 목표값을 입력하세요:",
        "tp3_value": "TP3 목표값을 입력하세요:",
        "use_sl": "손절 사용 여부를 선택하세요:",
        "sl_option": "손절 기준을 선택하세요:",
        "sl_value": "손절값을 입력하세요:",
        "use_check_DCA_with_price": "가격 기준 추가 진입 사용 여부:",
        "use_rsi_with_pyramiding": "피라미딩 진입 시 RSI 과매도 과매수에만 진입:",
        "use_break_even": "TP1 도달 후 본절가 Break-even 사용 여부:",
        "use_break_even_tp2": "TP2 도달 후 TP1 스탑 사용 여부:",
        "use_break_even_tp3": "TP3 도달 후 TP2 스탑 사용 여부:",
        "trailing_stop_active": "트레일링스탑 기능 사용 여부:",
        "use_trailing_stop_value_with_tp2_tp3_difference": "TP2와 TP3의 차이만큼 트레일링 스탑 적용 여부:",
        "trailing_stop_type": "트레일링 스탑 방식을 선택하세요:",
        "trailing_stop_offset_value": "트레일링 스탑 값(%)을 입력하세요:",
        "pyramiding_entry_type": "추가 진입 기준을 선택하세요:",
        "pyramiding_value": "추가 진입값을 입력하세요:",
        "use_trend_logic": "트랜드 로직 사용 여부:",
        "trend_timeframe": "트랜드 로직 타임프레임을 선택하세요:",
        "use_trend_close": "트랜드 청산 사용 여부:",
        "trailing_stop": "트레일링 스탑을 시작할 시점을 선택해주세요:",
    }
    
    if setting_type not in setting_prompts:
        await callback.answer("지원하지 않는 설정입니다.")
        return
    # 선택형 설정 처리
    if setting_type in [
        "direction", "entry_option", "tp_option", 
        "sl_option", "pyramiding_type", "pyramiding_entry_type", 
        "entry_criterion", "trailing_stop_type", "trailing_stop"
    ]:
        keyboards = {
            "direction": [
                [types.InlineKeyboardButton(text="롱", callback_data="direction:long")],
                [types.InlineKeyboardButton(text="숏", callback_data="direction:short")],
                [types.InlineKeyboardButton(text="롱숏", callback_data="direction:both")]
            ],
            "entry_option": [
                [types.InlineKeyboardButton(text=option, callback_data=f"entry_option:{option}")]
                for option in ENTRY_OPTIONS
            ],
            "tp_option": [
                [types.InlineKeyboardButton(text=option, callback_data=f"tp_option:{option}")]
                for option in TP_SL_OPTIONS
            ],
            "sl_option": [
                [types.InlineKeyboardButton(text=option, callback_data=f"sl_option:{option}")]
                for option in TP_SL_OPTIONS
            ],
            "pyramiding_type": [
                [types.InlineKeyboardButton(text=ptype, callback_data=f"pyramiding_type:{i}")]
                for i, ptype in enumerate(PYRAMIDING_TYPES)
            ],
            "pyramiding_entry_type": [
                [types.InlineKeyboardButton(text=option, callback_data=f"pyramiding_entry_type:{option}")]
                for option in TP_SL_OPTIONS
            ],
            "trend_timeframe": [
                [types.InlineKeyboardButton(text=tf.upper(), callback_data=f"set_trend_timeframe:{tf}") 
                 for tf in ['1m', '3m', '5m']], 
                [types.InlineKeyboardButton(text=tf.upper(), callback_data=f"set_trend_timeframe:{tf}") 
                 for tf in ['15m', '30m', '1h']],
                [types.InlineKeyboardButton(text=tf.upper(), callback_data=f"set_trend_timeframe:{tf}") 
                 for tf in ['2h', '4h', '6h']],
                [types.InlineKeyboardButton(text=tf.upper(), callback_data=f"set_trend_timeframe:{tf}") 
                 for tf in ['12h', '1d']],
                [types.InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")]
            ],
            "entry_criterion": [
                [types.InlineKeyboardButton(text=option, callback_data=f"entry_criterion:{option}")]
                for option in ENTRY_CRITERION_OPTIONS
            ] + [[
                types.InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")
            ]],
            "trailing_stop_type": [
                [types.InlineKeyboardButton(
                    text=f"{'✓ ' if settings.get('trailing_stop_type') == 'fixed' else ''}고정값({settings.get('trailing_stop_offset_value', 0)}) 사용",
                    callback_data="trailing_stop_type:fixed"
                )],
                [types.InlineKeyboardButton(
                    text=f"{'✓ ' if settings.get('trailing_stop_type') == 'tp_diff' else ''}TP2-TP3 차이 사용",
                    callback_data="trailing_stop_type:tp_diff"
                )],
                [types.InlineKeyboardButton(
                    text="⬅️ 뒤로가기",
                    callback_data="settings_back"
                )]
            ],
            "trailing_stop": [
                [types.InlineKeyboardButton(text="TP1 도달 시", callback_data="set_trailing_start:tp1")],
                [types.InlineKeyboardButton(text="TP2 도달 시", callback_data="set_trailing_start:tp2")],
                [types.InlineKeyboardButton(text="TP3 도달 시", callback_data="set_trailing_start:tp3")],
                [types.InlineKeyboardButton(text="❌ 사용 안함", callback_data="set_trailing_start:disable")],
                [types.InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")]
            ],
        }
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboards[setting_type])
        await callback.message.edit_text(setting_prompts[setting_type], reply_markup=keyboard)
    
    # 불리언 설정 처리
    elif setting_type in ["use_sl", "use_break_even", "use_break_even_tp2", "use_break_even_tp3", "use_sl_on_last", "use_cooldown", "use_trend_logic", "use_trend_close",
                        "use_rsi_with_pyramiding", "trailing_stop_active", "use_trailing_stop_value_with_tp2_tp3_difference", "use_check_DCA_with_price"]:
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="사용", callback_data=f"{setting_type}:true"),
                types.InlineKeyboardButton(text="미사용", callback_data=f"{setting_type}:false")
            ]
        ])
        await callback.message.edit_text(setting_prompts[setting_type], reply_markup=keyboard)
    
    # 수치 입력 설정 처리
    else:
        # TP 비율 한 번에 입력받기
        if setting_type == "tp_ratios":
            await state.set_state(SettingStates.waiting_for_tp_ratios)
        elif setting_type == "pyramiding_limit":
            await state.set_state(SettingStates.waiting_for_pyramiding_limit)
        elif setting_type == "trailing_stop_offset_value":
            await state.set_state(SettingStates.waiting_for_trailing_stop_offset_value)
        elif setting_type == "trailing_stop_type":
            await state.set_state(SettingStates.waiting_for_trailing_stop_type)
        else:
            # 예) investment, leverage, tp1_value ...
            await state.set_state(getattr(SettingStates, f"waiting_for_{setting_type}"))
        setting_prompt = setting_prompts[setting_type]
        await callback.message.edit_text(
            f"{setting_prompt}\n\n취소하려면 아래 버튼을 클릭하세요.", 
            reply_markup=get_cancel_keyboard()
        )


#
@router.callback_query(F.data.startswith("entry_option:"))
@router.callback_query(F.data.startswith("tp_option:"))
@router.callback_query(F.data.startswith("sl_option:"))
@router.callback_query(F.data.startswith("pyramiding_entry_type:"))
@router.callback_query(F.data.startswith("entry_criterion:"))
async def handle_option_callback(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    setting_type, value = callback.data.split(":")
    
    user_id = str(callback.from_user.id)
    user_id = await get_identifier(user_id)
    settings = await redis_service.get_user_settings(user_id)
    if settings is None:
        settings = DEFAULT_PARAMS_SETTINGS.copy()
    settings[setting_type] = value
    
    await redis_service.set_user_settings(user_id, settings)
    
    # 설정 타입별 표시 이름
    type_names = {
        "entry_option": "진입 방법",
        "tp_option": "익절 기준",
        "sl_option": "손절 기준",
        "pyramiding_entry_type": "추가진입 기준",
        "entry_criterion": "추가 진입 근거",
    }
    
    keyboard = get_settings_keyboard(settings)
    await callback.message.edit_text(
        f"✅ {type_names[setting_type]}이 {value}로 변경되었습니다.",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("use_"))
async def handle_boolean_callback(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    setting_type, value = callback.data.split(":")
    bool_value = (value == "true")
    
    user_id = str(callback.from_user.id)
    user_id = await get_identifier(user_id)
    settings = await redis_service.get_user_settings(user_id)
    if settings is None:
        settings = DEFAULT_PARAMS_SETTINGS.copy()
    settings[setting_type] = bool_value
    await redis_service.set_user_settings(user_id, settings)
    
    # 설정 타입별 표시 이름
    type_names = {
        "use_sl": "손절",
        "use_break_even": "TP1 본절가",
        "use_break_even_tp2": "TP2 TP1스탑",
        "use_break_even_tp3": "TP3 TP2스탑",
        "use_sl_on_last": "마지막 진입만 손절",
        "use_cooldown": "재진입 대기 시간",
        "use_trend_logic": "트랜드 로직",
        "use_trend_close": "트랜드 청산",
        "use_trend_timeframe": "트랜드 로직 타임프레임",
        "use_check_DCA_with_price": "가격 기준 추가 진입",
        "use_rsi_with_pyramiding": "피라미딩 진입 시 RSI 과매도 과매수에만 진입",
        "trailing_stop_active": "트레일링스탑 기능 사용 여부:",
        "use_trailing_stop_value_with_tp2_tp3_difference": "TP2와 TP3의 차이만큼 트레일링 스탑 적용",
    }
    
    keyboard = get_settings_keyboard(settings)
    status = "사용" if bool_value else "미사용"
    await callback.message.edit_text(
        f"✅ {type_names[setting_type]}가 {status}으로 변경되었습니다.",
        reply_markup=keyboard
    )

# ─────────────────────────────
# 1) 일반 수치 입력 설정 처리
# ─────────────────────────────
@router.callback_query(F.data == "setting:use_sl_on_last")
async def handle_sl_last_toggle(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return

    try:
        user_id = str(callback.from_user.id)
        user_id = await get_identifier(user_id)
        settings_key = f"user:{user_id}:settings"
        
        # settings에서 현재 상태 가져오기
        settings = await redis_client.get(settings_key)
        settings_dict = json.loads(settings) if settings else {}
        
        # 현재 상태 반전
        is_enabled = settings_dict.get('use_sl_on_last', False)
        settings_dict['use_sl_on_last'] = not is_enabled
        
        # 새로운 설정 저장
        await redis_client.set(settings_key, json.dumps(settings_dict))
        
        status_msg = "미사용" if is_enabled else "사용"
        await callback.answer()
        keyboard = get_settings_keyboard(settings_dict)  # settings_keyboard 사용
        await callback.message.edit_text(
            f"✅ 마지막 진입만 손절이 {status_msg}으로 변경되었습니다.\n"
            "원하시는 설정을 계속 진행해주세요.",
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"Error: {str(e)}")
        await callback.answer("설정 변경 중 오류가 발생했습니다.")
  
  
@router.message(SettingStates.waiting_for_cooldown_time)
async def process_cooldown_time(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        time = int(message.text)
        if not 1 <= time <= 3000:
            await message.answer("재진입 대기시간은 0초에서 3000초 사이여야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['cooldown_time'] = time
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 재진입 대기시간이 {time}초로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
        
@router.message(SettingStates.waiting_for_investment)
async def process_investment(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        investment = float(message.text)
        is_valid, error_msg = validator.validate_setting("investment", investment)
        if not is_valid:
            cancel_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="❌ 취소", callback_data="setting:cancel")]
            ])
            await message.answer(
                f"{error_msg}\n\n"
                "값을 다시 입력하세요. 취소하려면 아래 버튼을 클릭하세요.",
                reply_markup=cancel_keyboard
            )
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['investment'] = investment
        await redis_service.set_user_settings(user_id, settings)
        
        # entry_amount_option에 따라 단위 표시
        entry_amount_option = settings.get('entry_amount_option', 'usdt')
        unit = ENTRY_AMOUNT_UNITS.get(str(entry_amount_option), 'USDT')
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 투입금액이 {investment} {unit}로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        cancel_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ 취소", callback_data="setting:cancel")]
        ])
        await message.answer(
            "올바른 숫자를 입력해주세요.\n\n"
            "취소하려면 아래 버튼을 클릭하세요.",
            reply_markup=cancel_keyboard
        )
        
@router.callback_query(lambda c: c.data == "setting:done")
async def handle_done(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    if callback_query.from_user is None or callback_query.message is None:
        return
    if not isinstance(callback_query.message, Message):
        return

    try:
        # 상태 초기화
        await state.clear()
        
        # 기존 메시지 삭제
        await callback_query.message.delete()
        
        # 새 메시지로 응답
        await callback_query.message.answer("설정이 완료되었습니다.")
        
        # 콜백 쿼리 응답
        await callback_query.answer()
        
    except Exception as e:
        logger.error(f"Cancel handler error: {e}")
        try:
            await callback_query.message.answer("설정 취소 중 오류가 발생했습니다. 다시 시도해주세요.")
        except:
            logger.error("Failed to send error message")

@router.message(SettingStates.waiting_for_leverage)
async def process_leverage(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        leverage = int(message.text)
        is_valid, error_msg = validator.validate_setting("leverage", leverage)
        if not is_valid:
            await message.answer(error_msg)
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['leverage'] = leverage
        await redis_service.set_user_settings(user_id, settings)
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 레버리지 설정이 {leverage}x로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 정수를 입력해주세요.")

@router.message(SettingStates.waiting_for_rsi_length)
async def process_rsi_length(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        rsi_length = int(message.text)
        is_valid, error_msg = validator.validate_setting("rsi_length", rsi_length)
        if not is_valid:
            await message.answer(error_msg)
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['rsi_length'] = rsi_length
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ RSI 기간이 {rsi_length}로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 정수를 입력해주세요.")
        
@router.message(SettingStates.waiting_for_tp1_value)
async def handle_tp1_value(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        value = float(message.text)
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['tp1_value'] = value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ TP1 값이 {value}로 설정되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
 
@router.message(SettingStates.waiting_for_tp2_value)
async def handle_tp2_value(message: types.Message, state: FSMContext) -> None:  # 함수 이름 변경
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        value = float(message.text)
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['tp2_value'] = value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ TP2 값이 {value}로 설정되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
        
@router.message(SettingStates.waiting_for_tp3_value)
async def handle_tp3_value(message: types.Message, state: FSMContext) -> None:  # 함수 이름 변경
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        value = float(message.text)
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['tp3_value'] = value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ TP3 값이 {value}로 설정되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
#
# ────────────────────────────────────────────
# 2) TP 비율 한 번에 입력받기 
# ────────────────────────────────────────────
#

@router.message(SettingStates.waiting_for_tp_ratios)
async def process_tp_ratios(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    """
    사용자가 "30 30 40"처럼 TP1/TP2/TP3 비율을 한 줄에 입력하면 처리하는 핸들러
    """
    try:
        # 공백 기준으로 파싱
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("TP1, TP2, TP3 비율을 공백으로 구분해 3개 모두 입력해주세요. 예) 30 30 40")
            return
        
        tp1_ratio, tp2_ratio, tp3_ratio = map(float, parts)  # 실수 변환
        
        # 간단 유효성 체크 (합계 100%)
        total = tp1_ratio + tp2_ratio + tp3_ratio
        if abs(total - 100.0) > 1e-9:
            await message.answer(f"입력하신 비율의 합이 {total}% 입니다.\n반드시 합계가 100%가 되도록 다시 입력해주세요.")
            return
        
        # 실제 설정에 저장
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings["tp1_ratio"] = tp1_ratio
        settings["tp2_ratio"] = tp2_ratio
        settings["tp3_ratio"] = tp3_ratio
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        
        await message.answer(
            f"✅ TP 비율이 설정되었습니다.\n"
            f" - TP1: {tp1_ratio}%\n"
            f" - TP2: {tp2_ratio}%\n"
            f" - TP3: {tp3_ratio}%",
            reply_markup=keyboard
        )
    except ValueError:
        await message.answer("숫자 형식이 잘못되었습니다. 예) 30 30 40 식으로 입력해주세요.")

@router.message(SettingStates.waiting_for_sl_value)
async def process_sl_value(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        sl_value = float(message.text)
        is_valid, error_msg = validator.validate_setting("sl_value", sl_value)
        if not is_valid:
            await message.answer(error_msg)
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['sl_value'] = sl_value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 손절값이 {sl_value}로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")

@router.message(SettingStates.waiting_for_pyramiding_value)
async def process_pyramiding_value(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        pyramiding_value = float(message.text)
        is_valid, error_msg = validator.validate_setting("pyramiding_value", pyramiding_value)
        if not is_valid:
            await message.answer(error_msg)
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['pyramiding_value'] = pyramiding_value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 추가 진입값이 {pyramiding_value}로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
        
        
@router.message(SettingStates.waiting_for_entry_multiplier)
async def process_entry_multiplier(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        multiplier = float(message.text)
        if not 0.1 <= multiplier <= 5.0:
            await message.answer("추가 진입 배율은 0.1에서 5.0 사이여야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['entry_multiplier'] = multiplier
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 추가 진입 배율이 {multiplier}x로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")


@router.callback_query(lambda c: c.data.startswith("trailing_stop_type:"))
async def handle_trailing_type_selection(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    try:
        type_ = callback.data.split(":")[1]
        user_id = str(callback.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        
        # 타입 저장 추가
        settings['trailing_stop_type'] = type_
        
        if type_ == "fixed":
            # 고정값을 선택한 경우 값 입력 상태로 전환
            await state.set_state(SettingStates.waiting_for_trailing_stop_offset_value)
            await callback.message.edit_text(
                "트레일링 스탑 값(%)을 입력해주세요:\n"
                "• 설정 가능 범위: 0.1 ~ 100%\n"
                "• 예시: 1.5"
            )
            return
        else:  # tp_diff
            settings['use_trailing_stop_value_with_tp2_tp3_difference'] = True
            settings['trailing_stop_active'] = True  # tp_diff도 트레일링 스탑 활성화 필요
            settings['trailing_stop_offset_value'] = 0
            msg = "TP2-TP3 차이"
            
        await redis_service.set_user_settings(user_id, settings)
        keyboard = get_settings_keyboard(settings)
        await callback.message.edit_text(
            f"✅ 트레일링 스탑 방식이 {msg}로 설정되었습니다.",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in handle_trailing_type_selection: {e}")
        await callback.answer("설정 변경 중 오류가 발생했습니다.")

@router.message(SettingStates.waiting_for_trailing_stop_offset_value)
async def process_trailing_stop_offset_value(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        offset_value = float(message.text)
        if not 0.0 <= offset_value <= 50.0:
            await message.answer("트레일링 스탑 값은 0.0에서 50.0 사이여야 합니다.")
            return
            
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        
        settings['trailing_stop_offset_value'] = offset_value
        settings['use_trailing_stop_value_with_tp2_tp3_difference'] = False
        settings['trailing_stop_active'] = True  # 고정값 트레일링 스탑 활성화
        
        await redis_service.set_user_settings(user_id, settings)
        await state.clear()
        
        keyboard = get_settings_keyboard(settings)
        await message.answer(
            f"✅ 트레일링 스탑이 {offset_value}% 고정값으로 설정되었습니다.",
            reply_markup=keyboard
        )
        
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
        
        
@router.message(SettingStates.waiting_for_pyramiding_limit)
async def process_pyramiding_limit(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    print("process_pyramiding_limit")
    try:
        pyramiding_limit = int(message.text)
        if not 1 <= pyramiding_limit <= 10:
            await message.answer("최대 진입 횟수는 1에서 10 사이여야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = {}
        settings['pyramiding_limit'] = pyramiding_limit
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ 최대 진입 횟수가 {pyramiding_limit}회로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")


@router.message(SettingStates.waiting_for_rsi_oversold)
async def process_rsi_oversold(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        rsi_value = int(message.text)
        if not 0 <= rsi_value <= 100:
            await message.answer("RSI 값은 0에서 100 사이여야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['rsi_oversold'] = rsi_value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ RSI 과매도 기준이 {rsi_value}로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")

@router.message(SettingStates.waiting_for_rsi_overbought)
async def process_rsi_overbought(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        rsi_value = int(message.text)
        if not 0 <= rsi_value <= 100:
            await message.answer("RSI 값은 0에서 100 사이여야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['rsi_overbought'] = rsi_value
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        keyboard = get_settings_keyboard(settings)
        await message.answer(f"✅ RSI 과매수 기준이 {rsi_value}로 변경되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")
        
        
#================================================================================================
# 트랜드 로직 타임프레임
#================================================================================================
@router.callback_query(lambda c: c.data == "trend_timeframe_setting")
async def handle_trend_timeframe_setting(callback_query: CallbackQuery) -> None:
    if callback_query.from_user is None or callback_query.message is None:
        return
    if not isinstance(callback_query.message, Message):
        return

    try:
        # 사용 가능한 타임프레임 옵션들
        timeframe_options = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']
        
        # 현재 설정된 타임프레임 가져오기
        user_id = str(callback_query.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        current_tf = str(settings.get('trend_timeframe', '')).lower() if settings else ''
        
        # 인라인 키보드 생성
        buttons = []
        for i in range(0, len(timeframe_options), 3):  # 한 줄에 3개씩 배치
            row = []
            for tf in timeframe_options[i:i+3]:
                # 현재 선택된 타임프레임이면 ✓ 표시 추가
                text = f"✓ {tf.upper()}" if tf == current_tf else tf.upper()
                row.append(InlineKeyboardButton(
                    text=text,
                    callback_data=f"set_trend_timeframe:{tf}"
                ))
            buttons.append(row)
        
        # 뒤로가기 버튼 추가
        buttons.append([InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback_query.message.edit_text(
            "트랜드 로직에 사용할 타임프레임을 선택해주세요:\n"
            f"현재 설정: [{current_tf.upper() if current_tf else '설정 없음'}]",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in handle_trend_timeframe_setting: {e}")
        await callback_query.answer("설정 메뉴를 불러오는 중 오류가 발생했습니다.", show_alert=True)


@router.callback_query(lambda c: c.data.startswith("set_trend_timeframe:"))
async def handle_trend_timeframe_value(callback_query: CallbackQuery) -> None:
    if callback_query.from_user is None or callback_query.message is None:
        return
    if not isinstance(callback_query.message, Message):
        return
    if callback_query.data is None:
        return

    try:
        timeframe = callback_query.data.split(":")[1]
        user_id = str(callback_query.from_user.id)
        user_id = await get_identifier(user_id)
        # 현재 설정 가져오기
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = {}
            
        # 타임프레임 설정 업데이트
        settings['trend_timeframe'] = timeframe.upper()
        
        # 설정 저장
        await redis_service.set_user_settings(user_id, settings)
        
        # 설정 메뉴로 돌아가기
        keyboard = get_settings_keyboard(settings)
        await callback_query.message.edit_text(
            f"✅ 트렌드 타임프레임이 {timeframe.upper()}로 설정되었습니다.",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in handle_trend_timeframe_value: {e}")
        await callback_query.answer("설정 변경 중 오류가 발생했습니다.", show_alert=True)
#================================================================================================
# Setting Back
#================================================================================================


@router.callback_query(lambda c: c.data == "settings_back")
async def handle_settings_back(callback_query: CallbackQuery) -> None:
    if callback_query.from_user is None or callback_query.message is None:
        return
    if not isinstance(callback_query.message, Message):
        return

    try:
        user_id = str(callback_query.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        keyboard = get_settings_keyboard(settings)
        await callback_query.message.edit_text("설정을 선택하세요:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in handle_settings_back: {e}")
        await callback_query.answer("설정 메뉴로 돌아가는 중 오류가 발생했습니다.", show_alert=True)

#================================================================================================
# 에러 핸들러
#================================================================================================

# 에러 핸들링
@router.errors()
async def error_handler(event: ErrorEvent) -> None:
    try:
        # message is not modified 에러는 무시
        if isinstance(event.exception, TelegramBadRequest) and "message is not modified" in str(event.exception):
            return
            
        # 간단한 에러 정보만 로깅
        print(f"Error occurred: {type(event.exception).__name__} - {str(event.exception)}")
        # callback_query가 있는 경우
        if hasattr(event.update, 'callback_query') and event.update.callback_query:
            await event.update.callback_query.answer(
                f"오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                show_alert=True
            )
        # 일반 메시지인 경우
        elif hasattr(event.update, 'message') and event.update.message:
            await event.update.message.answer(
                f"오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            )
            
    except Exception as e:
        traceback.print_exc()
        

@router.callback_query(F.data.startswith("trailing_stop_active"))
async def handle_trailing_stop_selection(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return

    try:
        # 트레일링 스탑 설정 메뉴 표시
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="TP1 도달 시", callback_data="set_trailing_start:tp1")],
            [InlineKeyboardButton(text="TP2 도달 시", callback_data="set_trailing_start:tp2")],
            [InlineKeyboardButton(text="TP3 도달 시", callback_data="set_trailing_start:tp3")],
            [InlineKeyboardButton(text="❌ 사용 안함", callback_data="set_trailing_start:disable")],
            [InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")]
        ])
        
        await callback.message.edit_text(
            "트레일링 스탑을 시작할 시점을 선택해주세요:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in handle_trailing_stop_selection: {e}")
        await callback.answer("설정 변경 중 오류가 발생했습니다.")

@router.callback_query(lambda c: c.data.startswith("set_trailing_start:"))
async def handle_trailing_start_point(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    try:
        point = callback.data.split(":")[1]
        user_id = str(callback.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        
        if point == "disable":
            # 트레일링 스탑 비활성화
            settings['trailing_start_point'] = None
            settings['trailing_stop_type'] = None
            msg = "트레일링 스탑이 비활성화되었습니다."
        else:
            # 트레일링 스탑 시작 지점 설정
            settings['trailing_stop_active'] = True
            settings['trailing_start_point'] = point
            msg = f"트레일링 스탑이 {point.upper()} 도달 시 시작되도록 설정되었습니다."
        
        await redis_service.set_user_settings(user_id, settings)
        keyboard = get_settings_keyboard(settings)
        await callback.message.edit_text(f"✅ {msg}", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in handle_trailing_start_point: {e}")
        await callback.answer("설정 변경 중 오류가 발생했습니다.")
        


@router.callback_query(F.data.startswith("symbol_investment:"))
async def handle_symbol_investment(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    symbol = callback.data.split(":")[1]
    user_id = str(callback.from_user.id)
    user_id = await get_identifier(user_id)
    settings = await redis_service.get_user_settings(user_id)
    if settings is None:
        settings = DEFAULT_PARAMS_SETTINGS.copy()
    
    # 심볼별 상태 설정
    symbol_states = {
        "btc": SettingStates.waiting_for_btc_investment,
        "eth": SettingStates.waiting_for_eth_investment,
        "sol": SettingStates.waiting_for_sol_investment
    }
    
    # 심볼별 설명 텍스트
    symbol_names = {
        "btc": "BTC-USDT-SWAP",
        "eth": "ETH-USDT-SWAP",
        "sol": "SOL-USDT-SWAP"
    }
    
    # 현재 설정값 가져오기
    current_value = settings.get(f'{symbol}_investment', 100)
    
    # 취소 버튼
    cancel_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ 취소", callback_data="setting:cancel")]
    ])
    
    # 상태 설정 및 메시지 표시
    await state.set_state(symbol_states[symbol])
    await callback.message.edit_text(
        f"{symbol_names[symbol]}의 투입금액을 입력하세요 (USDT):\n"
        f"현재 설정: {current_value} USDT\n\n"
        "취소하려면 아래 버튼을 클릭하세요.",
        reply_markup=cancel_keyboard
    )

# BTC 투입금액 처리
@router.message(SettingStates.waiting_for_btc_investment)
async def process_btc_investment(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        investment = float(message.text)
        if investment <= 0:
            await message.answer("투입금액은 0보다 커야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['btc_investment'] = investment
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        
        # 종목별 투입금액 메뉴로 돌아가기
        buttons = [[types.InlineKeyboardButton(text="종목별 투입금액 설정으로 돌아가기", callback_data="setting:symbol_investments")]]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(f"✅ BTC-USDT-SWAP의 투입금액이 {investment} USDT로 설정되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")

# ETH 투입금액 처리
@router.message(SettingStates.waiting_for_eth_investment)
async def process_eth_investment(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        investment = float(message.text)
        if investment <= 0:
            await message.answer("투입금액은 0보다 커야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['eth_investment'] = investment
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        
        # 종목별 투입금액 메뉴로 돌아가기
        buttons = [[types.InlineKeyboardButton(text="종목별 투입금액 설정으로 돌아가기", callback_data="setting:symbol_investments")]]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(f"✅ ETH-USDT-SWAP의 투입금액이 {investment} USDT로 설정되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")

# SOL 투입금액 처리
@router.message(SettingStates.waiting_for_sol_investment)
async def process_sol_investment(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if message.text is None:
        await message.answer("텍스트를 입력해주세요.")
        return

    try:
        investment = float(message.text)
        if investment <= 0:
            await message.answer("투입금액은 0보다 커야 합니다.")
            return
        
        user_id = str(message.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        settings['sol_investment'] = investment
        await redis_service.set_user_settings(user_id, settings)
        
        await state.clear()
        
        # 종목별 투입금액 메뉴로 돌아가기
        buttons = [[types.InlineKeyboardButton(text="종목별 투입금액 설정으로 돌아가기", callback_data="setting:symbol_investments")]]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(f"✅ SOL-USDT-SWAP의 투입금액이 {investment} USDT로 설정되었습니다.", reply_markup=keyboard)
    except ValueError:
        await message.answer("올바른 숫자를 입력해주세요.")

# 투입금액 기준 설정 핸들러
@router.callback_query(F.data == "setting:entry_amount_option")
async def handle_entry_amount_option(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return

    try:
        user_id = str(callback.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        
        # 현재 설정값 가져오기
        current_option = settings.get('entry_amount_option', 'usdt')
        
        # 인라인 키보드 생성
        buttons = []
        options_display = {
            "usdt": "USDT 단위",
            "percent": "퍼센트(%) 단위",
            "count": "개수 단위"
        }
        
        for option in ENTRY_AMOUNT_OPTIONS:
            # 현재 선택된 옵션에 체크 표시 추가
            text = f"✓ {options_display[option]}" if option == current_option else options_display[option]
            buttons.append([InlineKeyboardButton(
                text=text,
                callback_data=f"set_entry_amount_option:{option}"
            )])
        
        # 뒤로가기 버튼 추가
        buttons.append([InlineKeyboardButton(text="⬅️ 뒤로가기", callback_data="settings_back")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(
            "투입금액 기준을 선택해주세요:\n"
            f"현재 설정: [{options_display[str(current_option)]}]",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in handle_entry_amount_option: {e}")
        await callback.answer("설정 메뉴를 불러오는 중 오류가 발생했습니다.")

# 투입금액 기준 설정 변경 처리
@router.callback_query(lambda c: c.data.startswith("set_entry_amount_option:"))
async def handle_entry_amount_option_selection(callback: types.CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not isinstance(callback.message, Message):
        return
    if callback.data is None:
        return

    try:
        option = callback.data.split(":")[1]
        user_id = str(callback.from_user.id)
        user_id = await get_identifier(user_id)
        settings = await redis_service.get_user_settings(user_id)
        if settings is None:
            settings = DEFAULT_PARAMS_SETTINGS.copy()
        
        # 투입금액 기준 설정 업데이트
        settings['entry_amount_option'] = option
        await redis_service.set_user_settings(user_id, settings)
        
        # 옵션별 표시 텍스트
        options_display = {
            "usdt": "USDT 단위",
            "percent": "퍼센트(%) 단위",
            "count": "개수 단위"
        }
        
        # 설정 메뉴로 돌아가기
        keyboard = get_settings_keyboard(settings)
        await callback.message.edit_text(
            f"✅ 투입금액 기준이 {options_display[option]}로 설정되었습니다.",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in handle_entry_amount_option_selection: {e}")
        await callback.answer("설정 변경 중 오류가 발생했습니다.")
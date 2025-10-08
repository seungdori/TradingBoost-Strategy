from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List

def get_tp_value_display(value: float, tp_option: str) -> str:
    if tp_option == "퍼센트 기준":
        return f"{value}%"
    elif tp_option == "금액 기준":
        return f"${value}"
    else:  # ATR 기준
        return f"{value}"

def get_pyramiding_value_display(value: float, entry_type: str) -> str:
    if entry_type == "퍼센트 기준":
        return f"{value}%"
    elif entry_type == "금액 기준":
        return f"${value}"
    else:  # ATR 기준
        return f"{value}"

def get_sl_value_display(value: float, sl_option: str) -> str:
    if sl_option == "퍼센트 기준":
        return f"{value}%"
    elif sl_option == "금액 기준":
        return f"${value}"
    else:  # ATR 기준
        return f"{value}"

def create_settings_button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)

def get_settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    # 현재 선택된 카테고리 확인
    current_category = settings.get('current_category', None)
    
    if current_category is None:
        # 메인 카테고리 메뉴 표시
        buttons = [
            [create_settings_button("⚙️ 기본 설정", "setting:show_category:basic")],
            [create_settings_button("📊 RSI 설정", "setting:show_category:rsi")],
            [create_settings_button("🎯 TP 설정", "setting:show_category:tp")],
            [create_settings_button("🛑 손절 설정", "setting:show_category:sl")],
            [create_settings_button("🔄 브레이크이븐/트레일링 설정", "setting:show_category:break_even")],
            [create_settings_button("📈 피라미딩 설정", "setting:show_category:pyramiding")],
            [create_settings_button("📉 트랜드 설정", "setting:show_category:trend")],
            [create_settings_button("✅ 완료", "setting:done")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    trailing_start_point = settings.get('trailing_start_point', None)
    trailing_start_point_str = None
    if trailing_start_point is None:
        trailing_start_point_str = "미사용 🔴"
    else:
        trailing_start_point_str = f"{trailing_start_point.upper()}에서 사용 🟢"
    # 카테고리별 버튼 정의
    category_buttons = {
        "basic": [
            create_settings_button(
                f"💰 심볼별 투입금액 설정",
                "setting:symbol_investments"
            ),
            create_settings_button(
                f"💵 투입금액 기준: {settings.get('entry_amount_option', 'usdt').upper()}",
                "setting:entry_amount_option"
            ),
            create_settings_button(
                f"⚡ 레버리지: {settings.get('leverage', 10)}x",
                "setting:leverage"
            ),
            create_settings_button(
                f"↕️ 포지션 방향: {settings.get('direction', '롱숏')}",
                "setting:direction"
            ),
            create_settings_button(
                f"📍 진입 방법: {settings.get('entry_option', '돌파')}",
                "setting:entry_option"
            ),
            create_settings_button(
                f"⏲️ 재진입 대기시간: {settings.get('cooldown_time', 300)}초",
                "setting:cooldown_time"
            )
        ],
        "rsi": [
            create_settings_button(
                f"📊 RSI 기간: {settings.get('rsi_length', 14)}",
                "setting:rsi_length"
            ),
            create_settings_button(
                f"📉 RSI 과매도: {settings.get('rsi_oversold', 30)}",
                "setting:rsi_oversold"
            ),
            create_settings_button(
                f"📈 RSI 과매수: {settings.get('rsi_overbought', 70)}",
                "setting:rsi_overbought"
            )
        ],
        "tp": [
            create_settings_button(
                f"💹 익절 기준: {settings.get('tp_option', '퍼센트 기준')}",
                "setting:tp_option"
            ),
            create_settings_button(
                f"📈 TP 비율: "
                f"{settings.get('tp1_ratio', 30)}/"
                f"{settings.get('tp2_ratio', 30)}/"
                f"{settings.get('tp3_ratio', 40)}%",
                "setting:tp_ratios"
            ),
            create_settings_button(
                f"🎯 TP1 값: {get_tp_value_display(settings.get('tp1_value', 2.0), settings.get('tp_option', '퍼센트 기준'))}",
                "setting:tp1_value"
            ),
            create_settings_button(
                f"🎯 TP2 값: {get_tp_value_display(settings.get('tp2_value', 3.0), settings.get('tp_option', '퍼센트 기준'))}",
                "setting:tp2_value"
            ),
            create_settings_button(
                f"🎯 TP3 값: {get_tp_value_display(settings.get('tp3_value', 4.0), settings.get('tp_option', '퍼센트 기준'))}",
                "setting:tp3_value"
            )
        ],
        "sl": [
            create_settings_button(
                f"- 손절: {'사용 🟢' if settings.get('use_sl', False) else '미사용 🔴'}",
                "setting:use_sl"
            ),
            create_settings_button(
                f"- 손절 기준: {settings.get('sl_option', '퍼센트 기준')}",
                "setting:sl_option"
            ),
            create_settings_button(
                f"- 손절값: {get_sl_value_display(settings.get('sl_value', 5.0), settings.get('sl_option', '퍼센트 기준'))}",
                "setting:sl_value"
            ),
            create_settings_button(
                f"- 마지막 진입만 손절: {'사용 🟢' if settings.get('use_sl_on_last', False) else '미사용 🔴'}",
                "setting:use_sl_on_last"
            )
        ],
        "break_even": [
            create_settings_button(
                f"- TP1도달 시 본절가: {'사용 🟢' if settings.get('use_break_even', True) else '미사용 🔴'}",
                "setting:use_break_even"
            ),
            create_settings_button(
                f"- TP2도달 시 TP1스탑: {'사용 🟢' if settings.get('use_break_even_tp2', True) else '미사용 🔴'}",
                "setting:use_break_even_tp2"
            ),
            create_settings_button(
                f"- TP3도달 시 TP2스탑: {'사용 🟢' if settings.get('use_break_even_tp3', True) else '미사용 🔴'}",
                "setting:use_break_even_tp3"
            ),
            create_settings_button(
                f"- 트레일링 스탑: {f'{trailing_start_point_str}' if settings.get('trailing_stop_active') else '미사용 🔴'}",
                "setting:trailing_stop"
            ),
            # trailing_start_point가 설정되어 있을 때만 방식 버튼 표시
            *([] if not settings.get('trailing_start_point') else [
                create_settings_button(
                    f"- 트레일링 스탑 방식: {'고정값' if settings.get('trailing_stop_type') == 'fixed' else 'TP 차이값'}",
                    "setting:trailing_stop_type"
                )
            ])
        ],
        "pyramiding": [
            create_settings_button(
                f"- 추가 진입 배율: {settings.get('entry_multiplier', 1.0)}",
                "setting:entry_multiplier"
            ),
            create_settings_button(
                f"- 추가진입 근거: {settings.get('entry_criterion', '평균 단가')}",
                "setting:entry_criterion"
            ),
            create_settings_button(
                f"- 추가진입 기준: {settings.get('pyramiding_entry_type', '퍼센트 기준')}",
                "setting:pyramiding_entry_type"
            ),
            create_settings_button(
                f"- 추가진입 값(금액/%/ATR): {get_pyramiding_value_display(settings.get('pyramiding_value', 3.0), settings.get('pyramiding_entry_type', '퍼센트 기준'))}",
                "setting:pyramiding_value"
            ),
            create_settings_button(
                f"- 최대 진입 횟수: {settings.get('pyramiding_limit', 4)}",
                "setting:pyramiding_limit"
            ),
            create_settings_button(
                f"- 가격 기준 추가 진입: {'사용 🟢' if settings.get('use_check_DCA_with_price', True) else '미사용 🔴'}",
                "setting:use_check_DCA_with_price"
            ),
            create_settings_button(
                f"- RSI 과매도 과매수에만 진입: {'사용 🟢' if settings.get('use_rsi_with_pyramiding', True) else '미사용 🔴'}",
                "setting:use_rsi_with_pyramiding"
            )
        ],
        "trend": [
            create_settings_button(
                f"- 트랜드 로직: {'사용 🟢' if settings.get('use_trend_logic', True) else '미사용 🔴'}",
                "setting:use_trend_logic"
            ),
            create_settings_button(
                f"- 트랜드 로직 타임프레임: {settings.get('trend_timeframe', '1H')}",
                "trend_timeframe_setting"
            ),
            create_settings_button(
                f"- 트랜드 청산: {'사용 🟢' if settings.get('use_trend_close', True) else '미사용 🔴'}",
                "setting:use_trend_close"
            )
        ]
    }
    
    buttons = []
    if current_category in category_buttons:
        current_buttons = category_buttons[current_category]
        # 1열로 버튼 배치
        for button in current_buttons:
            buttons.append([button])
    
    # 뒤로가기와 완료 버튼 추가
    buttons.append([
        create_settings_button("◀️ 뒤로가기", "setting:show_category:main"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
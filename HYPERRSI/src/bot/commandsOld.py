##src/bot/commands.py
#TODO:이미 다 구현된 것 같다면 삭제.

#from aiogram import types, Router, F
#from aiogram.filters import Command, StateFilter
#from aiogram.fsm.context import FSMContext
#from aiogram.fsm.state import State, StatesGroup, any_state
#from HYPERRSI.src.core.database import redis_client
#from HYPERRSI.src.tasks.trading_tasks import execute_trade
#from HYPERRSI.src.services.trading_service import TradingService
#import logging
#from HYPERRSI.src.core.models.database import UserModel, ExchangeKeysModel, UserPreferencesModel, UserStateModel
#from HYPERRSI.src.core.database import get_async_session
#from HYPERRSI.src.helpers.state_sync import StateSync
#from HYPERRSI.src.services.redis_service import RedisService

#import time
#router = Router()
#redis_service = RedisService()


#logger = logging.getLogger(__name__)

#class SettingStates(StatesGroup):
#    waiting_for_investment = State()
#    waiting_for_leverage = State()
#    waiting_for_direction = State()
#    waiting_for_max_entries = State()
#    waiting_for_entry_multiplier = State()
#    waiting_for_rsi_oversold = State()
#    waiting_for_rsi_overbought = State()

#class RegisterStates(StatesGroup):
#    waiting_for_api_key = State()
#    waiting_for_api_secret = State()
#    waiting_for_passphrase = State()

## Redis key patterns
#def get_redis_keys(user_id):
#    return {
#        'status': f"user:{user_id}:trading:status",
#        'api_keys': f"user:{user_id}:api:keys",
#        'stats': f"user:{user_id}:stats",
#        'position': f"user:{user_id}:position"
#    }

#async def start_command(message: types.Message):
#    """시작 명령어 처리"""
#    user_id = message.from_user.id
#    keys = get_redis_keys(user_id)
    
#    # 사용자 API 키 확인
#    api_keys = await redis_client.hgetall(keys['api_keys'])
    
#    if not api_keys:
#        await message.reply(
#            "안녕하세요! 트레이딩 봇입니다.\n"
#            "시작하기 전에 먼저 등록이 필요합니다.\n"
#            "/register 명령어로 등록을 진행해주세요."
#        )
#        return
    
#    welcome_msg = (
#        "안녕하세요! 트레이딩 봇입니다.\n"
#        "사용 가능한 명령어:\n"
#        "/status - 현재 트레이딩 상태 확인\n"
#        "/trade start - 자동 트레이딩 시작\n"
#        "/trade stop - 자동 트레이딩 중지\n"
#        "/position - 현재 포지션 확인"
#    )
    
#    await message.reply(welcome_msg)

#async def status_command(message: types.Message):
#    """상태 확인 명령어"""
#    user_id = message.from_user.id
#    keys = get_redis_keys(user_id)
    
#    status = await redis_client.get(keys['status'])
#    stats = await redis_client.hgetall(keys['stats'])
    
#    status_text = "활성화" if status == "active" else "비활성화"
    
#    stats_msg = (
#        f"트레이딩 상태: {status_text}\n"
#        f"총 거래 횟수: {stats.get('total_trades', 0)}\n"
#        f"성공 거래: {stats.get('successful_trades', 0)}\n"
#        f"수익률: {stats.get('profit_percentage', '0')}%"
#    )
    
#    await message.reply(stats_msg)


#async def trade_command(message: types.Message):
#    user_id = message.from_user.id
#    keys = get_redis_keys(user_id)
    
#    # API 키 확인
#    api_keys = await redis_client.hgetall(keys['api_keys'])
#    if not api_keys:
#        await message.reply(
#            "API 키 정보가 없습니다.\n"
#            "/register 명령어로 API 키를 등록해주세요."
#        )
#        return

#    if len(message.text.split()) < 2:
#        await message.reply(
#            "사용법: \n"
#            "/trade start - 자동 트레이딩 시작\n"
#            "/trade stop - 자동 트레이딩 중지"
#        )
#        return

#    command = message.text.split()[1].lower()
    
#    if command == "start":
#        current_status = await redis_client.get(keys['status'])
#        if current_status == "active":
#            await message.reply("이미 트레이딩이 실행 중입니다.")
#            return
        
#        await redis_client.set(keys['status'], "active")
#        # 초기 통계 설정
#        await redis_client.hmset(keys['stats'], {
#            'start_time': str(int(time.time())),
#            'total_trades': '0',
#            'successful_trades': '0',
#            'profit_percentage': '0'
#        })
        
#        await message.reply("자동 트레이딩을 시작합니다.")

#    elif command == "stop":
#        await redis_client.set(keys['status'], "inactive")
#        await message.reply("자동 트레이딩을 중지합니다.")
    
#    else:
#        await message.reply("잘못된 명령어입니다. 'start' 또는 'stop'을 사용해주세요.")

#async def position_command(message: types.Message):
#    """포지션 확인 명령어"""
#    user_id = message.from_user.id
#    trading_service = TradingService()
    
#    try:
#        position = await trading_service.get_current_position(user_id)
#        if position:
#            await message.reply(
#                f"현재 포지션:\n"
#                f"방향: {position.side}\n"
#                f"수량: {position.size}\n"
#                f"진입가격: {position.entry_price}\n"
#                f"레버리지: {position.leverage}x"
#            )
#        else:
#            await message.reply("현재 열린 포지션이 없습니다.")
#    except Exception as e:
#        await message.reply(f"포지션 정보를 가져오는 중 오류가 발생했습니다: {str(e)}")

#async def button_callback(callback_query: types.CallbackQuery):
#    """인라인 버튼 콜백 처리"""
#    query = callback_query.query
#    user_id = callback_query.from_user.id
#    data = query.data  # 버튼 데이터

#    try:
#        # 버튼 데이터에 따른 처리
#        if data.startswith('trade_'):
#            action = data.split('_')[1]
#            if action == 'start':
#                await redis_client.set(f"user:{user_id}:trading_status", "active")
#                await callback_query.answer("트레이딩을 시작합니다.")
#                await callback_query.message.edit_text("자동 트레이딩이 시작되었습니다.")
#            elif action == 'stop':
#                await redis_client.set(f"user:{user_id}:trading_status", "inactive")
#                await callback_query.answer("트레이딩을 중지합니다.")
#                await callback_query.message.edit_text("자동 트레이딩이 중지되었습니다.")
        
#        else:
#            await callback_query.answer("알 수 없는 명령입니다.")
            
#    except Exception as e:
#        logger.error(f"콜백 처리 중 오류 발생: {str(e)}")
#        await callback_query.answer("오류가 발생했습니다.")

#async def setapi_command(message: types.Message):
#    """API 키 설정"""
#    user_id = message.from_user.id
#    args = message.text.split()[1:]
    
#    if len(args) != 3:
#        await message.reply(
#            "사용법: /setapi <api_key> <api_secret> <passphrase>"
#        )
#        return
        
#    api_key, api_secret, passphrase = args
    
#    # Redis에 API 키 저장
#    await redis_client.hmset(f"user:{user_id}:api_keys", {
#        "okx_api_key": api_key,
#        "okx_api_secret": api_secret,
#        "okx_passphrase": passphrase
#    })
    
#    await message.reply("API 키가 설정되었습니다.")

#async def register_command(message: types.Message, state: FSMContext):
#    """사용자 등록 시작"""
#    user_id = message.from_user.id
#    keys = get_redis_keys(user_id)
    
#    # 이미 등록된 사용자 확인
#    api_keys = await redis_client.hgetall(keys['api_keys'])
#    if api_keys:
#        await message.reply("이미 등록된 사용자입니다. API 키를 변경하려면 /setapi 명령어를 사용하세요.")
#        return

#    await message.reply(
#        "OKX API 키 등록을 시작합니다.\n"
#        "API 키를 입력해주세요.\n"
#        "(취소하려면 /cancel 을 입력하세요)"
#    )
#    await state.set_state(RegisterStates.waiting_for_api_key)

#async def process_api_key(message: types.Message, state: FSMContext):
#    """API 키 처리"""
#    await state.update_data(api_key=message.text)
#    # 메시지 삭제를 통한 보안 강화
#    await message.reply("API Secret을 입력해주세요:")
#    await message.delete()
#    await state.set_state(RegisterStates.waiting_for_api_secret)

#async def process_api_secret(message: types.Message, state: FSMContext):
#    """API Secret 처리"""
#    await state.update_data(api_secret=message.text)
#    # 메시지 삭제를 통한 보안 강화
#    await message.reply("Passphrase를 입력해주세요:")
#    await message.delete()
#    await state.set_state(RegisterStates.waiting_for_passphrase)

#async def process_passphrase(message: types.Message, state: FSMContext):
#    """Passphrase 처리 및 사용자 등록 완료"""
#    user_id = message.from_user.id
#    keys = get_redis_keys(user_id)
    
#    # 메시지 삭제를 통한 보안 강화

    
#    # 상태 데이터 가져오기
#    user_data = await state.get_data()
#    user_data['passphrase'] = message.text
    
#    try:
#        # Redis에 API 키 정보 저장
#        await redis_client.hmset(keys['api_keys'], {
#            'api_key': user_data['api_key'],
#            'api_secret': user_data['api_secret'],
#            'passphrase': user_data['passphrase']
#        })
        
#        # 사용자 기본 설정 저장
#        await redis_client.hmset(f"user:{user_id}:preferences", {
#            'leverage': '10',
#            'trade_size': '100',
#            'rsi_period': '14',
#            'rsi_overbought': '70',
#            'rsi_oversold': '30'
#        })
        
#        # 사용자 상태 초기화
#        await redis_client.set(keys['status'], "inactive")
        
#        # 트레이딩 통계 초기화
#        await redis_client.hmset(keys['stats'], {
#            'total_trades': '0',
#            'successful_trades': '0',
#            'profit_percentage': '0',
#            'registration_date': str(int(time.time())),
#            'last_trade_date': '0'
#        })
        
#        # 상태 초기화
#        await state.clear()
        
#        await message.reply(
#            "✅ 등록이 완료되었습니다!\n\n"
#            "다음 명령어로 트레이딩을 시작할 수 있습니다:\n"
#            "/trade start - 자동 트레이딩 시작\n"
#            "/status - 현재 상태 확인\n"
#            "/position - 포지션 확인\n"
#            "/settings - 트레이딩 설정 변경"
#        )
#        await message.delete()
#        logger.info(f"New user registered: {user_id}")
        
#    except Exception as e:
#        logger.error(f"Error during user registration: {str(e)}")
#        await state.clear()
#        await message.reply(
#            "⚠️ 등록 중 오류가 발생했습니다. 다시 시도해주세요.\n"
#            "문제가 지속되면 관리자에게 문의해주세요."
#        )
        
#@router.message(Command("cancel"), StateFilter(any_state))
#async def cancel_command(message: types.Message, state: FSMContext):
#    """현재 진행 중인 상태/명령어 취소"""
#    current_state = await state.get_state()
    
#    if current_state is None:
#        await message.reply(
#            "취소할 진행 중인 작업이 없습니다.\n"
#            "도움말을 보시려면 /help 를 입력하세요."
#        )
#        return
    
#    # FSM 상태 초기화
#    await state.clear()
    
#    # 취소 확인 메시지
#    if current_state in [RegisterStates.waiting_for_api_key.state,
#                        RegisterStates.waiting_for_api_secret.state,
#                        RegisterStates.waiting_for_passphrase.state]:
#        await message.reply(
#            "✅ API 키 등록이 취소되었습니다.\n"
#            "다시 시작하시려면 /register 명령어를 사용해주세요."
#        )
#    else:
#        await message.reply("✅ 진행 중인 작업이 취소되었습니다.")
        
#async def help_command(message: types.Message):
#    """도움말 표시"""
#    user_id = message.from_user.id
#    keys = get_redis_keys(user_id)
    
#    # 사용자 등록 여부 확인
#    api_keys = await redis_client.hgetall(keys['api_keys'])
#    is_registered = bool(api_keys)
    
#    # 기본 명령어 목록
#    basic_commands = (
#        "📌 기본 명령어:\n"
#        "/help - 도움말 표시\n"
#        "/cancel - 진행 중인 작업 취소\n"
#    )
    
#    # 미등록 사용자용 명령어
#    if not is_registered:
#        commands = (
#            f"{basic_commands}\n"
#            "🔑 계정 관련:\n"
#            "/register - 새 사용자 등록 (API 키 설정)\n"
#            "\n❗️ 트레이딩을 시작하려면 먼저 등록이 필요합니다."
#        )
    
#    # 등록된 사용자용 명령어
#    else:
#        trading_status = await redis_client.get(keys['status'])
#        is_trading = trading_status == "active"
        
#        commands = (
#            f"{basic_commands}\n"
#            "🤖 트레이딩:\n"
#            "/trade start - 자동 트레이딩 시작\n"
#            "/trade stop - 자동 트레이딩 중지\n"
#            "/status - 현재 트레이딩 상태 확인\n"
#            "/position - 현재 포지션 확인\n"
#            "\n📊 설정 및 관리:\n"
#            "/settings - 트레이딩 설정 변경\n"
#            "/setapi - API 키 재설정\n"
#            "/stats - 트레이딩 통계 확인"
#        )
        
#        # 현재 트레이딩 상태 표시
#        status_text = "🟢 활성화" if is_trading else "🔴 비활성화"
#        commands += f"\n\n현재 트레이딩 상태: {status_text}"
    
#    await message.reply(commands)


#@router.message(Command("settings"))
#async def settings_command(message: types.Message):
#    """설정 메뉴 표시"""
#    user_id = str(message.from_user.id)
#    settings = await redis_service.get_user_settings(user_id)
    
#    if not settings:
#        settings = {
#            "investment": 100,
#            "leverage": 10,
#            "direction": "양방향",
#            "max_entries": 3,
#            "entry_multiplier": 1.5,
#            "rsi_oversold": 30,
#            "rsi_overbought": 70
#        }
#        await redis_service.set_user_settings(user_id, settings)
    
#    keyboard = get_settings_keyboard(settings)
#    await message.answer("변경할 설정 항목을 선택하세요:", reply_markup=keyboard)

#@router.callback_query(F.data.startswith("setting:"))
#async def handle_setting_callback(callback: types.CallbackQuery, state: FSMContext):
#    setting_type = callback.data.split(":")[1]
    
#    setting_prompts = {
#        "investment": "변경할 투입금액을 입력하세요 (USDT):",
#        "leverage": "변경할 레버리지를 입력하세요 (1-125):",
#        "direction": "포지션 방향을 선택하세요:",
#        "max_entries": "최대 진입 횟수를 입력하세요 (1-10):",
#        "entry_multiplier": "추가 진입 시 배율을 입력하세요 (1.0-3.0):",
#        "rsi_oversold": "RSI 과매도 기준값을 입력하세요 (0-100):",
#        "rsi_overbought": "RSI 과매수 기준값을 입력하세요 (0-100):"
#    }
    
#    await state.update_data(setting_type=setting_type)
    
#    if setting_type == "direction":
#        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
#            [types.InlineKeyboardButton(text="롱", callback_data="direction:long")],
#            [types.InlineKeyboardButton(text="숏", callback_data="direction:short")],
#            [types.InlineKeyboardButton(text="양방향", callback_data="direction:both")]
#        ])
#        await callback.message.edit_text("포지션 방향을 선택하세요:", reply_markup=keyboard)
#    else:
#        await state.set_state(getattr(SettingStates, f"waiting_for_{setting_type}"))
#        await callback.message.edit_text(setting_prompts[setting_type])

#def get_settings_keyboard(settings):
#    """설정 메뉴 키보드 생성"""
#    return types.InlineKeyboardMarkup(inline_keyboard=[
#        [types.InlineKeyboardButton(
#            text=f"투입금액: {settings['investment']} USDT",
#            callback_data="setting:investment"
#        )],
#        [types.InlineKeyboardButton(
#            text=f"레버리지: {settings['leverage']}x",
#            callback_data="setting:leverage"
#        )],
#        [types.InlineKeyboardButton(
#            text=f"방향: {settings['direction']}",
#            callback_data="setting:direction"
#        )],
#        [types.InlineKeyboardButton(
#            text=f"최대 진입 횟수: {settings['max_entries']}회",
#            callback_data="setting:max_entries"
#        )],
#        [types.InlineKeyboardButton(
#            text=f"추가 진입 배율: {settings['entry_multiplier']}x",
#            callback_data="setting:entry_multiplier"
#        )],
#        [types.InlineKeyboardButton(
#            text=f"RSI 과매도: {settings['rsi_oversold']}",
#            callback_data="setting:rsi_oversold"
#        )],
#        [types.InlineKeyboardButton(
#            text=f"RSI 과매수: {settings['rsi_overbought']}",
#            callback_data="setting:rsi_overbought"
#        )]
#    ])

#@router.message(SettingStates.waiting_for_investment)
#async def process_investment(message: types.Message, state: FSMContext):
#    try:
#        investment = float(message.text)
#        if investment <= 0:
#            await message.answer("투입금액은 0보다 커야 합니다.")
#            return
        
#        user_id = str(message.from_user.id)
#        settings = await redis_service.get_user_settings(user_id)
#        settings['investment'] = investment
#        await redis_service.set_user_settings(user_id, settings)
        
#        await state.clear()
#        keyboard = get_settings_keyboard(settings)
#        await message.answer(f"✅ 투입금액이 {investment} USDT로 변경되었습니다.", reply_markup=keyboard)
#    except ValueError:
#        await message.answer("올바른 숫자를 입력해주세요.")

#@router.message(SettingStates.waiting_for_leverage)
#async def process_leverage(message: types.Message, state: FSMContext):
#    try:
#        leverage = int(message.text)
#        if not 1 <= leverage <= 125:
#            await message.answer("레버리지는 1에서 125 사이여야 합니다.")
#            return
        
#        user_id = str(message.from_user.id)
#        settings = await redis_service.get_user_settings(user_id)
#        settings['leverage'] = leverage
#        await redis_service.set_user_settings(user_id, settings)
        
#        await state.clear()
#        keyboard = get_settings_keyboard(settings)
#        await message.answer(f"✅ 레버리지가 {leverage}x로 변경되었습니다.", reply_markup=keyboard)
#    except ValueError:
#        await message.answer("올바른 숫자를 입력해주세요.")

#@router.message(SettingStates.waiting_for_max_entries)
#async def process_max_entries(message: types.Message, state: FSMContext):
#    try:
#        max_entries = int(message.text)
#        if not 1 <= max_entries <= 10:
#            await message.answer("최대 진입 횟수는 1에서 10 사이여야 합니다.")
#            return
        
#        user_id = str(message.from_user.id)
#        settings = await redis_service.get_user_settings(user_id)
#        settings['max_entries'] = max_entries
#        await redis_service.set_user_settings(user_id, settings)
        
#        await state.clear()
#        keyboard = get_settings_keyboard(settings)
#        await message.answer(f"✅ 최대 진입 횟수가 {max_entries}회로 변경되었습니다.", reply_markup=keyboard)
#    except ValueError:
#        await message.answer("올바른 숫자를 입력해주세요.")

#@router.message(SettingStates.waiting_for_entry_multiplier)
#async def process_entry_multiplier(message: types.Message, state: FSMContext):
#    try:
#        multiplier = float(message.text)
#        if not 1.0 <= multiplier <= 3.0:
#            await message.answer("추가 진입 배율은 1.0에서 3.0 사이여야 합니다.")
#            return
        
#        user_id = str(message.from_user.id)
#        settings = await redis_service.get_user_settings(user_id)
#        settings['entry_multiplier'] = multiplier
#        await redis_service.set_user_settings(user_id, settings)
        
#        await state.clear()
#        keyboard = get_settings_keyboard(settings)
#        await message.answer(f"✅ 추가 진입 배율이 {multiplier}x로 변경되었습니다.", reply_markup=keyboard)
#    except ValueError:
#        await message.answer("올바른 숫자를 입력해주세요.")

#@router.message(SettingStates.waiting_for_rsi_oversold)
#async def process_rsi_oversold(message: types.Message, state: FSMContext):
#    try:
#        rsi_value = int(message.text)
#        if not 0 <= rsi_value <= 100:
#            await message.answer("RSI 값은 0에서 100 사이여야 합니다.")
#            return
        
#        user_id = str(message.from_user.id)
#        settings = await redis_service.get_user_settings(user_id)
#        settings['rsi_oversold'] = rsi_value
#        await redis_service.set_user_settings(user_id, settings)
        
#        await state.clear()
#        keyboard = get_settings_keyboard(settings)
#        await message.answer(f"✅ RSI 과매도 기준이 {rsi_value}로 변경되었습니다.", reply_markup=keyboard)
#    except ValueError:
#        await message.answer("올바른 숫자를 입력해주세요.")

#@router.message(SettingStates.waiting_for_rsi_overbought)
#async def process_rsi_overbought(message: types.Message, state: FSMContext):
#    try:
#        rsi_value = int(message.text)
#        if not 0 <= rsi_value <= 100:
#            await message.answer("RSI 값은 0에서 100 사이여야 합니다.")
#            return
        
#        user_id = str(message.from_user.id)
#        settings = await redis_service.get_user_settings(user_id)
#        settings['rsi_overbought'] = rsi_value
#        await redis_service.set_user_settings(user_id, settings)
        
#        await state.clear()
#        keyboard = get_settings_keyboard(settings)
#        await message.answer(f"✅ RSI 과매수 기준이 {rsi_value}로 변경되었습니다.", reply_markup=keyboard)
#    except ValueError:
#        await message.answer("올바른 숫자를 입력해주세요.")

#@router.callback_query(F.data.startswith("direction:"))
#async def handle_direction_callback(callback: types.CallbackQuery, state: FSMContext):
#    direction = callback.data.split(":")[1]
#    direction_map = {
#        "long": "롱",
#        "short": "숏",
#        "both": "양방향"
#    }
    
#    user_id = str(callback.from_user.id)
#    settings = await redis_service.get_user_settings(user_id)
#    settings['direction'] = direction_map[direction]
#    await redis_service.set_user_settings(user_id, settings)
    
#    keyboard = get_settings_keyboard(settings)
#    await callback.message.edit_text(
#        f"✅ 포지션 방향이 {direction_map[direction]}으로 변경되었습니다.",
#        reply_markup=keyboard
#    )
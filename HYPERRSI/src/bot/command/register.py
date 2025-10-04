# src/bot/commands/register.py

from aiogram import types, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import time
from shared.constants.default_settings import DEFAULT_TRADING_SETTINGS, DEFAULT_PARAMS_SETTINGS , DEFAULT_DUAL_SIDE_ENTRY_SETTINGS  # 추가
import pytz
from datetime import datetime
from HYPERRSI.src.core.database import redis_client
from ..states.states import RegisterStates
from HYPERRSI.src.core.logger import get_logger
from HYPERRSI.src.utils.check_invitee import get_uid_from_api_keys
import traceback
import json

permit_uid = [
    '646396755365762614',
    '587662504768345929',
    '646325987009217441'

]

#ONLY FOR OKX API
def check_right_invitee(okx_api, okx_secret, okx_parra, user_id= None):

    invitee = True
    try:
        
        if user_id == 1709556958 or user_id == 7097155337:
            return True, 1709556958
        else:
            invitee, uid = get_uid_from_api_keys(okx_api, okx_secret, okx_parra)
            
            if str(uid) in permit_uid:
                print("관리자로부터 허용된 사용자입니다.")
                return True, str(uid)
        
        
        if invitee:
            return True, uid
        else:
            return False, None
    except Exception as e:
        print(f"Error checking invitee: {e}")
        print(traceback.format_exc())
        return False
    


router = Router()
logger = get_logger(__name__)

def get_redis_keys(user_id):
    return {
        'status': f"user:{user_id}:trading:status",
        'api_keys': f"user:{user_id}:api:keys",
        'stats': f"user:{user_id}:stats",
    }
allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267"]
def is_allowed_user(user_id):
    """허용된 사용자인지 확인"""
    return str(user_id) in allowed_uid
@router.message(Command("register"))
async def register_command(message: types.Message, state: FSMContext):
    """사용자 등록 시작"""
    user_id = message.from_user.id
    okx_uid = await redis_client.get(f"user:{user_id}:okx_uid")
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return
    keys = get_redis_keys(user_id)
    
    api_keys = await redis_client.hgetall(keys['api_keys'])
    if api_keys:
        await message.reply(
            "⚠️ 이미 등록된 사용자입니다.\n"
            "🔄 API 키를 변경하려면 /setapi 명령어를 사용하세요."
        )
        return

    await message.reply(
        "🔑 OKX API 키 등록을 시작합니다.\n\n"
        "1️⃣ API 키를 입력해주세요.\n"
        "❌ 취소하려면 /cancel 을 입력하세요"
    )
    await state.set_state(RegisterStates.waiting_for_api_key)
@router.message(Command("setapi"))
async def setapi_command(message: types.Message, state: FSMContext):
    """API 키 설정"""
    user_id = message.from_user.id
    okx_uid = await redis_client.get(f"user:{user_id}:okx_uid")
    if not is_allowed_user(okx_uid):
        await message.reply("⛔ 접근 권한이 없습니다.")
        return
    
    confirm_keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="예", callback_data="confirm_setapi"),
                types.InlineKeyboardButton(text="아니오", callback_data="cancel_setapi")
            ]
        ]
    )
    
    await message.reply(
        "⚠️ 기존 API 키를 변경하시겠습니까?\n"
        "변경 시 기존 설정이 덮어쓰기됩니다.",
        reply_markup=confirm_keyboard
    )

@router.callback_query(F.data == "confirm_setapi")
async def confirm_setapi(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔑 OKX API 키 변경을 시작합니다.\n\n"
        "1️⃣ 새로운 API 키를 입력해주세요.\n"
        "❌ 취소하려면 /cancel 을 입력하세요"
    )
    await state.set_state(RegisterStates.waiting_for_api_key)
    await state.update_data(is_update=True)  # API 키 업데이트 플래그 추가
    await callback.answer()

@router.callback_query(F.data == "cancel_setapi")
async def cancel_setapi(callback: types.CallbackQuery):
    await callback.message.edit_text("❌ API 키 변경이 취소되었습니다.")
    await callback.answer()
    
    
@router.message(RegisterStates.waiting_for_passphrase)
async def process_passphrase(message: types.Message, state: FSMContext):
    """Passphrase 처리 및 API 키 변경 완료"""
    user_id = message.from_user.id
    keys = get_redis_keys(user_id)
    
    user_data = await state.get_data()
    user_data['passphrase'] = message.text
    
    # invitee 확인
    is_valid_invitee, uid = check_right_invitee(
        user_data['api_key'], 
        user_data['api_secret'], 
        user_data['passphrase'],
        user_id = user_id
    )
    
    if not is_valid_invitee:
        await message.reply(
            "⚠️ 유효하지 않은 API 키입니다.\n"
            "🔑 API 키를 다시 확인해주세요.\n"
            "❗ 초대된 사용자만 서비스를 이용할 수 있습니다."
        )
        await state.clear()
        return
    
    try:
        # Redis에 API 키 정보 저장
        await redis_client.hmset(keys['api_keys'], {
            'api_key': user_data['api_key'],
            'api_secret': user_data['api_secret'],
            'passphrase': user_data['passphrase'],
            'uid': str(uid),
            'last_update_time': str(int(time.time())),
            'last_update_time_kr': str(datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S')),
        })
        
        is_update = user_data.get('is_update', False)
        
        if not is_update:  # 새 사용자 등록인 경우
            # DEFAULT_TRADING_SETTINGS에서 기본 설정 가져와서 저장
            await redis_client.hmset(
                f"user:{user_id}:preferences", 
                {k: str(v) for k, v in DEFAULT_TRADING_SETTINGS.items()}
            )
            await redis_client.set(
                f"user:{user_id}:settings",
                json.dumps(DEFAULT_PARAMS_SETTINGS)
            )
            await redis_client.hmset(
                f"user:{user_id}:dual_side",
                {k: str(v) for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
            )
            # 사용자 상태 초기화
            await redis_client.set(keys['status'], "stopped")
            
            # 트레이딩 통계 초기화
            await redis_client.hmset(keys['stats'], {
                'total_trades': '0',
                'entry_trade': '0',
                'successful_trades': '0',
                'profit_percentage': '0',
                'registration_date': str(int(time.time())),
                'last_trade_date': '0'
            })
            
            await message.reply(
                "✅ 등록이 완료되었습니다!\n\n"
                "📌 사용 가능한 명령어:\n\n"
                "⚙️설정 관련\n"
                "/settings - 트레이딩 설정\n"
                "/dual_settings - 양방향 매매 설정\n\n"
                "📊 거래 관련\n"
                "├ /trade - 트레이딩 시작/정지\n"
                "├ /status - 실시간 현황\n"
                "└ /balance - 포지션 + 자산 정보\n\n"
                "❓ 전체 명령어를 보시려면 /help를 입력해주세요."
            )
            logger.info(f"New user registered: {user_id}")
        else:  # API 키 업데이트인 경우
            await message.reply(
                "✅ API 키가 성공적으로 변경되었습니다!\n"
                "계속해서 기존 설정으로 트레이딩을 진행할 수 있습니다."
            )
            logger.info(f"User {user_id} updated API keys")
        
        await state.clear()
        await message.delete()
        
    except Exception as e:
        logger.error(f"Error during user registration or API update: {str(e)}")
        await state.clear()
        await message.reply(
            "⚠️ 처리 중 오류가 발생했습니다.\n"
            "🔄 다시 시도해주세요.\n"
            "❗ 문제가 지속되면 관리자에게 문의해주세요."
        )

@router.message(RegisterStates.waiting_for_api_key)
async def process_api_key(message: types.Message, state: FSMContext):
    """API 키 처리"""
    await state.update_data(api_key=message.text)
    sent_message = await message.answer(
        "2️⃣ API Secret을 입력해주세요:"
    )
    await message.delete()
    await state.set_state(RegisterStates.waiting_for_api_secret)


@router.message(RegisterStates.waiting_for_api_secret)
async def process_api_secret(message: types.Message, state: FSMContext):
    """API Secret 처리"""
    await state.update_data(api_secret=message.text)
    sent_message = await message.answer(
        "3️⃣ Passphrase를 입력해주세요:"
    )
    await message.delete()
    await state.set_state(RegisterStates.waiting_for_passphrase)
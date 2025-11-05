# src/bot/commands/register.py

import json
import time
import traceback
from datetime import datetime

import pytz
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from HYPERRSI.src.bot.states.states import RegisterStates
from HYPERRSI.src.utils.check_invitee import get_uid_from_api_keys
from shared.constants.default_settings import (  # 추가
    DEFAULT_DUAL_SIDE_ENTRY_SETTINGS,
    DEFAULT_PARAMS_SETTINGS,
    DEFAULT_TRADING_SETTINGS,
)
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils.uid_validator import UIDValidator, UIDType
from HYPERRSI.src.services.timescale_service import TimescaleUserService

permit_uid = [
    '646396755365762614',
    '587662504768345929',
    '646325987009217441'

]

#ONLY FOR OKX API
async def check_right_invitee(okx_api, okx_secret, okx_parra, user_id= None):
    """
    API 키로 OKX UID를 가져오고 초대자 여부 확인

    Args:
        okx_api: OKX API 키
        okx_secret: OKX Secret 키
        okx_parra: OKX Passphrase
        user_id: 텔레그램 ID (로깅용)

    Returns:
        tuple: (초대 여부, OKX UID)
    """
    try:
        # 모든 사용자에 대해 실제 OKX API에서 UID 가져오기
        invitee, uid = await get_uid_from_api_keys(okx_api, okx_secret, okx_parra)

        # 허용된 UID 목록 확인
        if str(uid) in permit_uid:
            logger.info(f"Allowed user: telegram_id={user_id}, okx_uid={uid}")
            return True, str(uid)

        if invitee:
            logger.info(f"Valid invitee: telegram_id={user_id}, okx_uid={uid}")
            return True, str(uid)
        else:
            logger.warning(f"Not an invitee: telegram_id={user_id}, okx_uid={uid}")
            return False, None

    except Exception as e:
        logger.error(f"Error checking invitee for telegram_id={user_id}: {e}")
        logger.error(traceback.format_exc())
        return False, None
    


router = Router()
logger = get_logger(__name__)

def get_redis_keys(user_id):
    return {
        'status': f"user:{user_id}:trading:status",
        'api_keys': f"user:{user_id}:api:keys",
        'stats': f"user:{user_id}:stats",
    }
allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267","586156710277369942"]
def is_allowed_user(user_id):
    """허용된 사용자인지 확인"""
    return str(user_id) in allowed_uid
@router.message(Command("register"))
async def register_command(message: types.Message, state: FSMContext):
    """사용자 등록 시작"""
    redis = await get_redis_client()
    user_id = message.from_user.id
    okx_uid = await redis.get(f"user:{user_id}:okx_uid")
    if not is_allowed_user(okx_uid):
        print("okx_uid", okx_uid)
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    # OKX UID가 있으면 사용, 없으면 체크하지 않음 (신규 등록)
    if okx_uid:
        okx_uid = okx_uid.decode('utf-8') if isinstance(okx_uid, bytes) else okx_uid
        keys = get_redis_keys(okx_uid)
        api_keys = await redis.hgetall(keys['api_keys'])
    else:
        api_keys = None

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
    redis = await get_redis_client()
    user_id = message.from_user.id
    okx_uid = await redis.get(f"user:{user_id}:okx_uid")
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
    redis = await get_redis_client()
    telegram_id = message.from_user.id  # 텔레그램 ID 저장
    keys_temp = get_redis_keys(telegram_id)  # 임시로 텔레그램 ID 기반 키 사용

    user_data = await state.get_data()
    user_data['passphrase'] = message.text

    # invitee 확인 (async 함수이므로 await 필요)
    is_valid_invitee, uid = await check_right_invitee(
        user_data['api_key'],
        user_data['api_secret'],
        user_data['passphrase'],
        user_id = telegram_id
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
        is_update = user_data.get('is_update', False)

        if is_update:  # API 키 업데이트인 경우
            # 기존 OKX UID 확인
            existing_okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")
            if existing_okx_uid:
                existing_okx_uid = existing_okx_uid.decode('utf-8') if isinstance(existing_okx_uid, bytes) else existing_okx_uid

                # 새 API 키의 UID와 기존 UID 비교
                new_uid = str(uid)
                if existing_okx_uid != new_uid:
                    # 계정 전환 허용 - 기존 UID 업데이트
                    await redis.set(f"user:{telegram_id}:okx_uid", new_uid)

                    # active_traders 업데이트
                    await redis.srem("active_traders", existing_okx_uid)
                    await redis.sadd("active_traders", new_uid)

                    await message.reply(
                        "⚠️ 계정이 변경되었습니다.\n"
                        f"기존 UID: {existing_okx_uid}\n"
                        f"새 API UID: {new_uid}\n\n"
                        "새 계정으로 전환됩니다."
                    )

                okx_uid = new_uid  # 새 UID로 변경
                logger.info(f"API key update: switched to new UID {okx_uid}")
            else:
                # 기존 UID가 없는 경우 (예외 상황)
                okx_uid = str(uid)
                await redis.set(f"user:{telegram_id}:okx_uid", okx_uid)
                logger.warning(f"No existing UID found for telegram_id={telegram_id}, creating new mapping")
        else:  # 새 사용자 등록인 경우
            # OKX UID로 Redis 키 생성
            okx_uid = str(uid)

            # UID 검증
            try:
                okx_uid = UIDValidator.ensure_okx_uid(okx_uid)
                telegram_id_str = UIDValidator.ensure_telegram_id(str(telegram_id))
                logger.info(f"✅ UID 검증 성공 - OKX: {okx_uid}, Telegram: {telegram_id_str}")
            except ValueError as e:
                await message.reply(
                    f"⚠️ UID 검증 실패: {str(e)}\n"
                    "관리자에게 문의하세요."
                )
                await state.clear()
                return

            # 텔레그램 ID -> OKX UID 매핑 저장
            await redis.set(f"user:{telegram_id}:okx_uid", okx_uid)
            logger.info(f"New user registration: telegram_id={telegram_id}, okx_uid={okx_uid}")

        keys = get_redis_keys(okx_uid)

        # Redis에 API 키 정보 저장 (OKX UID 사용)
        logger.info(f"🔑 Saving API keys to Redis: {keys['api_keys']}")
        api_data = {
            'api_key': user_data['api_key'],
            'api_secret': user_data['api_secret'],
            'passphrase': user_data['passphrase'],
            'uid': str(uid),
            'last_update_time': str(int(time.time())),
            'last_update_time_kr': str(datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S')),
        }
        await redis.hset(keys['api_keys'], mapping=api_data)

        # 저장 확인
        saved_keys = await redis.hgetall(keys['api_keys'])
        if saved_keys:
            logger.info(f"✅ API keys successfully saved to Redis: {list(saved_keys.keys())}")
        else:
            logger.error(f"❌ Failed to save API keys to Redis: {keys['api_keys']}")
        
        is_update = user_data.get('is_update', False)

        if not is_update:  # 새 사용자 등록인 경우
            # DEFAULT_TRADING_SETTINGS에서 기본 설정 가져와서 Redis에 저장 (OKX UID 사용)
            await redis.hset(
                f"user:{okx_uid}:preferences",
                mapping={k: str(v) for k, v in DEFAULT_TRADING_SETTINGS.items()}
            )
            await redis.set(
                f"user:{okx_uid}:settings",
                json.dumps(DEFAULT_PARAMS_SETTINGS)
            )
            await redis.hset(
                f"user:{okx_uid}:dual_side",
                mapping={k: str(v) for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
            )
            # 사용자 상태 초기화
            await redis.set(keys['status'], "stopped")

            # 트레이딩 통계 초기화
            await redis.hset(keys['stats'], mapping={
                'total_trades': '0',
                'entry_trade': '0',
                'successful_trades': '0',
                'profit_percentage': '0',
                'registration_date': str(int(time.time())),
                'last_trade_date': '0'
            })

            # TimescaleDB에도 저장
            try:
                # 1. 사용자 존재 확인 및 생성
                await TimescaleUserService.ensure_user_exists(
                    okx_uid=okx_uid,
                    telegram_id=str(telegram_id),
                    display_name=f"User {okx_uid}",
                    telegram_username=None
                )

                # 2. API 키 저장
                await TimescaleUserService.upsert_api_credentials(
                    identifier=okx_uid,
                    api_key=user_data['api_key'],
                    api_secret=user_data['api_secret'],
                    passphrase=user_data['passphrase']
                )

                # 3. 모든 설정 저장
                await TimescaleUserService.save_all_user_settings(
                    identifier=okx_uid,
                    preferences=DEFAULT_TRADING_SETTINGS,
                    params=DEFAULT_PARAMS_SETTINGS,
                    dual_side=DEFAULT_DUAL_SIDE_ENTRY_SETTINGS
                )

                logger.info(f"✅ TimescaleDB 저장 완료: okx_uid={okx_uid}, telegram_id={telegram_id}")
            except Exception as ts_error:
                logger.error(f"⚠️ TimescaleDB 저장 실패 (Redis는 성공): {ts_error}")
                # TimescaleDB 저장 실패해도 Redis 저장은 성공했으므로 계속 진행

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
            logger.info(f"New user registered: telegram_id={telegram_id}, okx_uid={okx_uid}")
        else:  # API 키 업데이트인 경우
            await message.reply(
                "✅ API 키가 성공적으로 변경되었습니다!\n"
                "계속해서 기존 설정으로 트레이딩을 진행할 수 있습니다."
            )
            logger.info(f"User telegram_id={telegram_id}, okx_uid={okx_uid} updated API keys")
        
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
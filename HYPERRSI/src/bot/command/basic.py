# src/bot/commands/basic.py

import logging

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state

from HYPERRSI.src.bot.states.states import RegisterStates
from HYPERRSI.src.services.timescale_service import TimescaleUserService
from shared.database.redis_helper import get_redis_client

router = Router()
logger = logging.getLogger(__name__)
redis = None

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

@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext) -> None:
    """시작 명령어 처리"""
    global redis
    if redis is None:
        redis = await get_redis_client()

    if not message.from_user:
        return
    user_id = message.from_user.id

    telegram_uid_key = f"user:{user_id}:okx_uid"
   
    # 이미 등록된 UID가 있는지 확인
    okx_uid = await redis.get(telegram_uid_key)

    if okx_uid:
        if isinstance(okx_uid, bytes):
            okx_uid = okx_uid.decode()

        display_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name])).strip()
        username = message.from_user.username

        try:
            await TimescaleUserService.set_telegram_link(
                str(okx_uid),
                str(user_id),
                display_name=display_name or None,
                telegram_username=username,
            )
            logger.info(f"TimescaleDB link ensured for existing user {okx_uid} (telegram {user_id})")
        except Exception as exc:
            logger.error(f"TimescaleDB 링크 처리 중 오류: {exc}")

        await message.reply(
            f"👋 안녕하세요! 이미 연동이 완료되었습니다.\n\n"
            f"연동된 UID: {okx_uid}\n"
            f"설정을 초기화하려면 /reset 명령어를 사용하세요."
        )
        return

    # 등록되지 않은 경우 UID 입력 요청
    await message.reply(
        "👋 안녕하세요! 트레이딩 알림 봇입니다.\n\n"
        "🔑 시스템과 연동하기 위해 UID를 입력해주세요:"
    )
   
    # UID 입력 상태로 전환
    await state.set_state("waiting_for_uid")

# UID 입력 상태에서의 메시지 처리
@router.message(StateFilter("waiting_for_uid"))
async def process_uid(message: types.Message, state: FSMContext) -> None:
    """UID 입력 처리"""
    global redis
    if redis is None:
        redis = await get_redis_client()
    if not message.from_user or not message.text:
        return
    user_id = message.from_user.id

    telegram_uid_key = f"user:{user_id}:okx_uid"

    # 입력된 텍스트가 UID
    okx_uid = message.text.strip()
    
    try:
        # UID를 숫자로 변환 시도하여 유효성 검사
        okx_uid_int = int(okx_uid)
        
        # Redis에 UID 저장
        await redis.set(telegram_uid_key, okx_uid)
        
        display_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name])).strip()
        username = message.from_user.username

        timescale_status = "TimescaleDB 연동 완료"
        try:
            # 먼저 기존 telegram_id 연결을 제거 (다른 UID와 연결되어 있을 수 있음)
            from HYPERRSI.src.services.timescale_service import TimescalePool
            try:
                async with TimescalePool.acquire() as conn:
                    # 이 telegram_id를 사용하는 기존 연결 모두 제거
                    await conn.execute(
                        """
                        UPDATE app_users
                        SET telegram_id = NULL,
                            telegram_linked = FALSE,
                            updated_at = now()
                        WHERE telegram_id = $1
                        """,
                        str(user_id)
                    )
                    logger.info(f"기존 telegram_id {user_id} 연결 해제 완료")
            except Exception as e:
                logger.warning(f"기존 연결 해제 중 오류 (무시됨): {e}")

            # 새로운 연결 생성
            record = await TimescaleUserService.set_telegram_link(
                str(okx_uid),
                str(user_id),
                display_name=display_name or None,
                telegram_username=username,
            )
            if record is None:
                timescale_status = "⚠️ TimescaleDB에 사용자 정보를 생성할 수 없습니다. 관리자에게 문의해주세요."
                logger.warning(f"TimescaleDB에서 사용자 {user_id} / {okx_uid}를 생성하지 못했습니다.")
            else:
                logger.info(f"TimescaleDB link established for user {user_id} with OKX UID {okx_uid}")
        except Exception as exc:
            timescale_status = f"⚠️ 데이터베이스 연동 중 오류가 발생했습니다: {exc}"
            logger.error(f"TimescaleDB 등록 오류: {exc}")
        
        # 상태 초기화
        await state.clear()
        
        # 기본 설정 초기화
        try:
            from HYPERRSI.src.services.redis_service import RedisService
            from shared.constants.default_settings import (
                DEFAULT_DUAL_SIDE_ENTRY_SETTINGS,
                DEFAULT_PARAMS_SETTINGS,
            )
            redis_service = RedisService()
            
            # 사용자 설정 초기화
            default_settings = DEFAULT_PARAMS_SETTINGS.copy()
            await redis_service.set_user_settings(str(okx_uid), default_settings)
            
            # 양방향 매매 설정 초기화
            default_dual_settings = {k: v for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
            settings_key = f"user:{okx_uid}:dual_side"
            settings_to_save = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in default_dual_settings.items()}
            await redis.hset(settings_key, mapping=settings_to_save)
            
            await message.reply(
                f"✅ UID ({okx_uid}) 등록 완료!\n"
                "이제 트레이딩 알림을 받으실 수 있습니다.\n"
            )

            if timescale_status.startswith("⚠️"):
                await message.reply(timescale_status)
        except Exception as e:
            await message.reply(
                f"⚠️ UID는 등록되었으나 설정 초기화 중 오류가 발생했습니다: {str(e)}\n"
                "관리자에게 문의해주세요."
            )
            
    except ValueError:
        await message.reply(
            "❌ 유효하지 않은 UID 형식입니다. 숫자만 입력해주세요."
        )

@router.message(Command("reset"))
async def reset_command(message: types.Message) -> None:
    """UID 리셋 명령어 처리"""
    global redis
    if redis is None:
        redis = await get_redis_client()
    if not message.from_user:
        return
    user_id = message.from_user.id

    telegram_uid_key = f"user:{user_id}:okx_uid"

    # 등록된 UID 확인
    okx_uid = await redis.get(telegram_uid_key)

    if not okx_uid:
        await message.reply(
            "❌ 등록된 UID가 없습니다.\n"
            "/start 명령어로 먼저 UID를 등록해주세요."
        )
        return

    # Redis에서 UID 삭제
    await redis.delete(telegram_uid_key)

    # TimescaleDB에서 사용자 상태 업데이트
    okx_uid_str = okx_uid.decode() if isinstance(okx_uid, bytes) else str(okx_uid)
    try:
        # DB에서 telegram_id를 완전히 제거
        from HYPERRSI.src.services.timescale_service import TimescalePool
        async with TimescalePool.acquire() as conn:
            await conn.execute(
                """
                UPDATE app_users
                SET telegram_id = NULL,
                    telegram_linked = FALSE,
                    updated_at = now()
                WHERE telegram_id = $1 OR okx_uid = $2
                """,
                str(user_id),
                okx_uid_str
            )
        timescale_status = "✅ 텔레그램 연결 해제됨"
        logger.info(f"사용자 {user_id} / UID {okx_uid_str} 연결 해제 완료")
    except Exception as exc:
        logger.error(f"TimescaleDB 상태 업데이트 오류: {exc}")
        timescale_status = f"❌ 오류: {exc}"
    
    await message.reply(
        f"✅ UID ({okx_uid}) 연동이 해제되었습니다.\n"

        "다시 등록하려면 /start 명령어를 사용하세요."
    )
    if timescale_status and timescale_status != "✅ 텔레그램 연결 해제됨":
        await message.reply(timescale_status)

@router.message(Command("cancel"), StateFilter(any_state))
async def cancel_command(message: types.Message, state: FSMContext) -> None:
    """현재 진행 중인 상태/명령어 취소"""
    if not message.from_user:
        return
    user_id = message.from_user.id

    current_state = await state.get_state()
    
    if current_state is None:
        await message.reply(
            "취소할 진행 중인 작업이 없습니다."
        )
        return
    
    # FSM 상태 초기화
    await state.clear()
    
    # 취소 확인 메시지
    if current_state == "waiting_for_uid":
        await message.reply(
            "✅ UID 등록이 취소되었습니다.\n"
            "다시 시작하시려면 /start 명령어를 사용해주세요."
        )
    else:
        await message.reply("✅ 진행 중인 작업이 취소되었습니다.")

@router.message(Command("help"))
async def help_command(message: types.Message) -> None:
    """도움말 표시"""
    global redis
    if redis is None:
        redis = await get_redis_client()

    if not message.from_user:
        return
    user_id = message.from_user.id

    okx_uid_bytes = await redis.get(f"user:{user_id}:okx_uid")
    okx_uid = okx_uid_bytes.decode('utf-8') if isinstance(okx_uid_bytes, bytes) else okx_uid_bytes if okx_uid_bytes else None
    if not is_allowed_user(okx_uid):
        print("okx_uid", okx_uid)
        await message.reply("⛔ 접근 권한이 없습니다.")
        return

    # OKX UID로 키 생성
    keys = get_redis_keys(okx_uid if okx_uid else str(user_id))
    api_keys = await redis.hgetall(keys['api_keys'])
    is_registered = bool(api_keys)

    basic_commands = (
        "🎯 명령어\n"
        "├ 🚀 /trade - 봇 시작하기\n"
        "├ 📊 /status - 실시간 포지션 및 수익 현황\n"
        "├ 💰 /balance - 포지션 + 계좌 잔고 확인\n"
        "├ 📜 /history - 거래 내역 조회\n"
        "├ 📊 /stats - 트레이딩 통계\n"
        "├ ⚙️ /settings - 트레이딩 설정\n"
        "├ 🔄 /dual_settings - 양방향 매매 설정\n"
        "├ ❓ /help - 도움말 보기\n"
        "└ ⛔ /stop - 봇 종료\n"
    )

    if not is_registered:
        commands = (
            f"{basic_commands}\n"
            "🔐 계정 설정\n"
            "└ 📝 /register - 새 사용자 등록 (API 키 설정)\n"
            "\n⚠️ 트레이딩을 시작하려면 먼저 등록이 필요합니다."
        )
    else:
        trading_status = await redis.get(keys['status'])
        is_trading = trading_status == "running"
        commands = (
            f"{basic_commands}"
        )

        status_text = "🟢 활성화" if is_trading else "🔴 비활성화"
        commands += f"\n\n📡 현재 트레이딩 상태: {status_text}"

    await message.reply(commands)

@router.message(Command("commands"))
async def commands_command(message: types.Message) -> None:
    """전체 명령어 목록 표시 (권한 체크 없음)"""
    if not message.from_user:
        return

    commands_text = (
        "📋 HYPERRSI 트레이딩 봇 명령어 목록\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "🔧 기본 설정\n"
        "├ /start - 계정 연동 (UID 등록)\n"
        "├ /reset - 계정 연동 해제\n"
        "├ /cancel - 진행 중인 작업 취소\n"
        "└ /commands - 명령어 목록 보기\n\n"

        "🚀 트레이딩 제어\n"
        "├ /trade - 트레이딩 시작/중지\n"
        "├ /stop - 트레이딩 강제 중지\n"
        "└ /settings - 트레이딩 설정 변경\n\n"

        "📊 정보 조회\n"
        "├ /status - 포지션 및 수익 현황\n"
        "├ /balance - 계좌 잔고 확인\n"
        "├ /history - 거래 내역 조회\n"
        "└ /stats - 트레이딩 통계\n\n"

        "⚙️ 고급 설정\n"
        "├ /dual_settings - 양방향 매매 설정\n"
        "├ /sl - 손절가(Stop Loss) 설정\n"
        "└ /tp - 익절가(Take Profit) 설정\n\n"

        "❓ 도움말\n"
        "└ /help - 상세 도움말\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 처음 사용하시나요?\n"
        "1️⃣ /start 로 계정 연동\n"
        "2️⃣ /settings 로 설정 확인\n"
        "3️⃣ /trade 로 트레이딩 시작!"
    )

    await message.reply(commands_text)

@router.message(Command("menu"))
async def menu_command(message: types.Message) -> None:
    """명령어 목록 표시 (commands와 동일)"""
    await commands_command(message)
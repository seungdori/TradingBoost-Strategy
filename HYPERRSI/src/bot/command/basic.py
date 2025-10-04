# src/bot/commands/basic.py

from aiogram import types, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from HYPERRSI.src.core.database import redis_client
import logging
import os
import httpx
from dotenv import load_dotenv

from ..states.states import RegisterStates  

# 환경변수 로드
load_dotenv()

# Supabase 연결 정보
SUPABASE_URL = "https://fsobvtcxqndccnekasqw.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZzb2J2dGN4cW5kY2NuZWthc3F3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzA2NDEyMjcsImV4cCI6MjA0NjIxNzIyN30.kdbn5f89xxeAbDX7SMUF_SX561PX1jDISr1sKTY1ka4"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZzb2J2dGN4cW5kY2NuZWthc3F3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczMDY0MTIyNywiZXhwIjoyMDQ2MjE3MjI3fQ.Pni49lbWfdQBt7azJE_I_-1rM5jjp7Ri1L44I3F_hNQ"

router = Router()
logger = logging.getLogger(__name__)

# Supabase API 클라이언트 함수
async def supabase_api_call(endpoint, method="GET", data=None, auth_key=SUPABASE_SERVICE_KEY):
    """Supabase API 호출 함수"""
    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    
    async with httpx.AsyncClient() as client:
        if method == "GET":
            response = await client.get(url, headers=headers)
        elif method == "POST":
            response = await client.post(url, json=data, headers=headers)
        elif method == "PUT":
            response = await client.put(url, json=data, headers=headers)
        elif method == "PATCH":
            response = await client.patch(url, json=data, headers=headers)
        elif method == "DELETE":
            response = await client.delete(url, headers=headers)
        
        return response

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

@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """시작 명령어 처리"""
    user_id = message.from_user.id
    
    telegram_uid_key = f"user:{user_id}:okx_uid"
   
    # 이미 등록된 UID가 있는지 확인
    okx_uid = await redis_client.get(telegram_uid_key)
   
    if okx_uid:
        # Supabase에서 사용자 정보 확인
        try:
            # okx_uid로 사용자 확인
            response = await supabase_api_call(f"users?okx_uid=eq.{okx_uid}", method="GET")
            
            if response.status_code == 200 and response.json():
                # 이미 okx_uid가 등록되어 있는 경우
                supabase_user = response.json()[0]
                
                # telegram_id 업데이트 필요한지 확인
                if supabase_user.get('telegram_id') != str(user_id):
                    # telegram_id 업데이트
                    update_data = {
                        "telegram_id": str(user_id),
                        "telegram_linked": True,
                        "updated_at": "now()"
                    }
                    await supabase_api_call(f"users?okx_uid=eq.{okx_uid}", method="PATCH", data=update_data)
                    supabase_msg = "텔레그램 ID 업데이트됨"
                else:
                    supabase_msg = "기존 연결 확인됨"
                    
                await message.reply(
                    f"👋 안녕하세요! 이미 연동이 완료되었습니다.\n\n"
                    f"연동된 UID: {okx_uid}\n"
                    f"설정을 초기화하려면 /reset 명령어를 사용하세요."
                )
            else:
                # okx_uid는 Redis에 있지만 Supabase에는 없는 경우
                user_data = {
                    "telegram_id": str(user_id),
                    "okx_uid": str(okx_uid),
                    "name": message.from_user.first_name or "" + " " + (message.from_user.last_name or ""),
                    "telegram_linked": True,
                    "created_at": "now()",
                    "updated_at": "now()"
                }
                await supabase_api_call("users", method="POST", data=user_data)
                
                await message.reply(
                    f"👋 안녕하세요! 이미 연동이 완료되었습니다.\n\n"
                    f"연동된 UID: {okx_uid}\n"
                    f"설정을 초기화하려면 /reset 명령어를 사용하세요."
                )
        except Exception as e:
            logger.error(f"Supabase 연결 오류: {str(e)}")
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
async def process_uid(message: types.Message, state: FSMContext):
    """UID 입력 처리"""
    user_id = message.from_user.id
    
    telegram_uid_key = f"user:{user_id}:okx_uid"
    
    # 입력된 텍스트가 UID
    okx_uid = message.text.strip()
    
    try:
        # UID를 숫자로 변환 시도하여 유효성 검사
        okx_uid_int = int(okx_uid)
        
        # Redis에 UID 저장
        await redis_client.set(telegram_uid_key, okx_uid)
        
        # Supabase에 사용자 정보 저장
        try:
            # 먼저 okx_uid로 사용자 확인
            response = await supabase_api_call(f"users?okx_uid=eq.{okx_uid}", method="GET")
            
            if response.status_code == 200 and response.json():
                # okx_uid가 이미 존재하면 telegram_id를 업데이트
                update_data = {
                    "telegram_id": str(user_id),
                    "telegram_linked": True,
                    "updated_at": "now()"
                }
                await supabase_api_call(f"users?okx_uid=eq.{okx_uid}", method="PATCH", data=update_data)
                supabase_status = "기존 OKX UID에 텔레그램 ID 연결됨"
                logger.info(f"기존 OKX UID {okx_uid}에 텔레그램 ID {user_id} 연결 성공")
            else:
                # okx_uid가 없으면 새로 생성
                user_data = {
                    "telegram_id": str(user_id),
                    "okx_uid": str(okx_uid),
                    "name": message.from_user.first_name or "" + " " + (message.from_user.last_name or ""),
                    "telegram_linked": True,
                    "created_at": "now()",
                    "updated_at": "now()"
                }
                create_response = await supabase_api_call("users", method="POST", data=user_data)
                
                if create_response.status_code in [200, 201]:
                    supabase_status = "새 사용자로 등록됨"
                    logger.info(f"신규 사용자 등록: 텔레그램 ID {user_id}, OKX UID {okx_uid}")
                else:
                    logger.error(f"Supabase 사용자 생성 실패: {create_response.text}")
                    supabase_status = f"등록 실패: {create_response.status_code}"
                    
        except Exception as e:
            logger.error(f"Supabase 등록 오류: {str(e)}")
            supabase_status = f"오류: {str(e)}"
        
        # 상태 초기화
        await state.clear()
        
        # 기본 설정 초기화
        try:
            from shared.constants.default_settings import DEFAULT_PARAMS_SETTINGS, DEFAULT_DUAL_SIDE_ENTRY_SETTINGS
            from HYPERRSI.src.services.redis_service import RedisService
            redis_service = RedisService()
            
            # 사용자 설정 초기화
            default_settings = DEFAULT_PARAMS_SETTINGS.copy()
            await redis_service.set_user_settings(str(okx_uid), default_settings)
            
            # 양방향 매매 설정 초기화
            default_dual_settings = {k: v for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
            settings_key = f"user:{okx_uid}:dual_side"
            settings_to_save = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in default_dual_settings.items()}
            await redis_client.hset(settings_key, mapping=settings_to_save)
            
            await message.reply(
                f"✅ UID ({okx_uid}) 등록 완료!\n"
                "이제 트레이딩 알림을 받으실 수 있습니다.\n"
            )
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
async def reset_command(message: types.Message):
    """UID 리셋 명령어 처리"""
    user_id = message.from_user.id
    
    telegram_uid_key = f"user:{user_id}:okx_uid"
    
    # 등록된 UID 확인
    okx_uid = await redis_client.get(telegram_uid_key)
    
    if not okx_uid:
        await message.reply(
            "❌ 등록된 UID가 없습니다.\n"
            "/start 명령어로 먼저 UID를 등록해주세요."
        )
        return
    
    # Redis에서 UID 삭제
    await redis_client.delete(telegram_uid_key)
    
    # Supabase에서 사용자 상태 업데이트
    try:
        # telegram_id 필드 비우고 telegram_linked 상태 변경
        update_data = {
            "telegram_id": None,  # telegram_id 연결 해제
            "telegram_linked": False,
            "updated_at": "now()"
        }
        await supabase_api_call(f"users?okx_uid=eq.{okx_uid}", method="PATCH", data=update_data)
        supabase_status = "✅ 텔레그램 연결 해제됨"
    except Exception as e:
        logger.error(f"Supabase 상태 업데이트 오류: {str(e)}")
        supabase_status = f"❌ 오류: {str(e)}"
    
    await message.reply(
        f"✅ UID ({okx_uid}) 연동이 해제되었습니다.\n"

        "다시 등록하려면 /start 명령어를 사용하세요."
    )

#@router.message(Command("check"))
#async def check_command(message: types.Message):
#    """현재 UID 확인 명령어 처리"""
#    user_id = message.from_user.id
    
#    # 허용된 사용자만 사용 가능
#    if not is_allowed_user(user_id):
#        await message.reply("⛔ 접근 권한이 없습니다.")
#        return
        
#    telegram_uid_key = f"user:{user_id}:okx_uid"
    
#    # 등록된 UID 확인
#    okx_uid = await redis_client.get(telegram_uid_key)
    
#    if okx_uid:
#        await message.reply(
#            f"✅ 연동 상태: 활성화\n\n"
#            f"연동된 UID: {okx_uid}"
#        )
#    else:
#        await message.reply(
#            "❌ 연동 상태: 미연동\n\n"
#            "UID 등록이 필요합니다.\n"
#            "/start 명령어를 통해 UID를 등록해주세요."
#        )

@router.message(Command("cancel"), StateFilter(any_state))
async def cancel_command(message: types.Message, state: FSMContext):
    """현재 진행 중인 상태/명령어 취소"""
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
async def help_command(message: types.Message):
   """도움말 표시"""
   user_id = message.from_user.id
   
   okx_uid = await redis_client.get(f"user:{user_id}:okx_uid")
   if not is_allowed_user(okx_uid):
       await message.reply("⛔ 접근 권한이 없습니다.")
       return
   
   keys = get_redis_keys(user_id)
   api_keys = await redis_client.hgetall(keys['api_keys'])
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
       trading_status = await redis_client.get(keys['status'])
       is_trading = trading_status == "running"
       commands = (
           f"{basic_commands}"
       )

       status_text = "🟢 활성화" if is_trading else "🔴 비활성화"
       commands += f"\n\n📡 현재 트레이딩 상태: {status_text}"

   await message.reply(commands)
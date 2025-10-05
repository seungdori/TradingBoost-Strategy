from aiogram import types, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from HYPERRSI.src.core.database import redis_client
import logging
from HYPERRSI.src.bot.states.states import RegisterStates
from shared.constants.message import CANCEL_MESSAGES
from shared.logging import get_logger

router = Router()
logger = get_logger(__name__)

@router.callback_query(F.data.endswith(":cancel"))
async def handle_global_cancel(callback: types.CallbackQuery, state: FSMContext):
    try:
        # 현재 상태 초기화
        await state.clear()
        
        # 어떤 컨텍스트에서 취소되었는지 확인
        prefix = callback.data.split(":")[0]
        
        # 취소 메시지 표시
        message = CANCEL_MESSAGES.get(prefix, CANCEL_MESSAGES["default"])
        
        # 콜백 응답
        await callback.answer("취소되었습니다.")
        
        # 현재 메시지 삭제 시도
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"메시지 삭제 실패: {e}")
            # 메시지 삭제가 실패하면 메시지 수정으로 대체
            await callback.message.edit_text(message)
            
    except Exception as e:
        logger.error(f"취소 처리 중 오류 발생: {e}")
        await callback.answer("취소 처리 중 오류가 발생했습니다.")
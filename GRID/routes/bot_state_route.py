from fastapi import APIRouter, Request
from shared.dtos.response import ResponseDto
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto
from GRID.services import bot_state_service

router = APIRouter(prefix="/state", tags=["state"])


## 전역 상태 사용 예시
#@router.get("/")
#async def get_bot_states(request: Request) -> ResponseDto[list[BotStateDto] | None]:
#    try:
#        bot_states: list[BotStateDto] = await bot_state_service.get_all_bot_state(request.app)
#
#        return ResponseDto[list[BotStateDto]](
#            success=True,
#            message="All bot state",
#            data=bot_states
#        )
#    except Exception as e:
#        return ResponseDto[None](
#            success=False,
#            message=f"Get bot states fail",
#            meta={"error": str(e)},
#            data=None
#        )


@router.get("/{exchange_name}/{enter_strategy}/{user_id}")
async def get_bot_state(exchange_name: str, enter_strategy: str, user_id:int, request: Request) \
        -> ResponseDto[BotStateDto | None]:
    try:
        bot_state: BotStateDto = await bot_state_service.get_bot_state(
            dto=BotStateKeyDto(
                exchange_name=exchange_name,
                enter_strategy=enter_strategy,
                user_id = user_id
            )
        )
        
        return ResponseDto[BotStateDto](
            success=True,
            message="All bot state",
            data=bot_state
        )

    except Exception as e:
        print('[GET BOT STATE EXCEPTION]', e)
        return ResponseDto[BotStateDto](
            success=False,
            message="Get bot state fail.",
            meta={"error": str(e)},
            data=None
        )


@router.post("/")
async def set_bot_state(bot_state: BotStateDto, request: Request) -> ResponseDto[BotStateDto | None]:
    try:
        new_state = await bot_state_service.set_bot_state(new_state=bot_state)
        return ResponseDto[BotStateDto](
            success=True,
            message="All bot state",
            data=new_state
        )

    except Exception as e:
        print('[SET BOT STATE EXCEPTION]')
        return ResponseDto[None](
            success=False,
            message="Set bot state fail.",
            meta={"error": str(e)},
            data=None
        )


@router.patch("/error")
async def clear_bot_state_error(dto: BotStateKeyDto) -> ResponseDto[BotStateDto | None]:
    print('[CLEAR BOT STATE ERROR API]', dto)
    try:
        current_state = await bot_state_service.get_bot_state(dto)
        new_state = BotStateDto(
            key=current_state.key,
            exchange_name=current_state.exchange_name,
            enter_strategy=current_state.enter_strategy,
            is_running=current_state.is_running,
            error=None
        )
        updated = await bot_state_service.set_bot_state(new_state)

        return ResponseDto[BotStateDto](
            success=True,
            message="All bot state",
            data=updated
        )

    except Exception as e:
        print('[SET BOT STATE EXCEPTION]')
        return ResponseDto[None](
            success=False,
            message="Set bot state fail.",
            meta={"error": str(e)},
            data=None
        )

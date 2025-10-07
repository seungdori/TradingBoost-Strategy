from fastapi import APIRouter
from shared.dtos.response import ResponseDto
from shared.dtos.telegram import TelegramTokenDto
from GRID.services import telegram_service

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/id", response_model=ResponseDto)
async def get_telegram_id() -> ResponseDto[str]:
    telegram_id = telegram_service.get_telegram_id()
    return ResponseDto[str](
        success=True,
        message=f"Telegram ID fetch success.",
        data=telegram_id
    )


@router.get("/token/{exchange_name}", response_model=ResponseDto)
async def get_telegram_token(exchange_name: str) -> ResponseDto[TelegramTokenDto]:
    dto: TelegramTokenDto = TelegramTokenDto(
        exchange_name=exchange_name,
        token=telegram_service.get_telegram_token(exchange_name)
    )

    return ResponseDto[TelegramTokenDto](
        success=True,
        message=f"{exchange_name} telegram token fetch success.",
        data=dto
    )


# 텔레그램 ID를 업데이트합니다.
# 데스크탑 앱 실행 시, 로컬에 저장된 텔레그램 ID를 업데이트합니다.
# 이후 클라이언트에서 텔레그램 ID 업데이트를 요청할 때마다 실행됩니다.
@router.patch('/id/{telegram_id}', response_model=ResponseDto)
async def update_telegram_id(telegram_id: str) -> ResponseDto[str]:
    telegram_service.set_telegram_id(telegram_id)

    updated_id = telegram_service.get_telegram_id()

    return ResponseDto[str](
        success=True,
        message=f"Telegram ID update success.",
        data=updated_id
    )


# 텔레그램 토큰을 업데이트합니다.
# 데스크탑 앱 실행 시, 로컬에 저장된 모든 거래소의 텔레그램 토큰을 업데이트합니다.
# 이후 클라이언트에서 특정 거래소의 텔레그램 토큰 업데이트를 요청할 때마다 실행됩니다.
@router.patch('/token', response_model=ResponseDto)
async def update_telegram_token(dto: TelegramTokenDto) -> ResponseDto[TelegramTokenDto | None]:
    print('[UPDATE TELEGRAM TOKEN]', dto)

    try:
        telegram_service.set_telegram_token(dto)  # type: ignore[arg-type]
        updated_token = telegram_service.get_telegram_token(dto.exchange_name)
        updated_token_dto: TelegramTokenDto = TelegramTokenDto(
            exchange_name=dto.exchange_name,
            token=updated_token
        )

        return ResponseDto[TelegramTokenDto | None](
            success=True,
            message=f"{dto.exchange_name} telegram token update success",
            data=updated_token_dto
        )
    except Exception as e:
        print('[TELEGRAM TOKEN UPDATE EXCEPTION]', e)
        return ResponseDto[TelegramTokenDto | None](
            success=False,
            message=f"{dto.exchange_name} telegram token update fail",
            meta={'error': str(e)},
            data=None
        )

from typing import Any, List
from fastapi import APIRouter
from shared.dtos.exchange import ExchangeApiKeyDto, WalletDto, ApiKeys
from shared.dtos.response import ResponseDto
from GRID.services import exchange_service, api_key_service

router = APIRouter(prefix="/exchange", tags=["exchange"])


@router.get("/{exchange_name}/wallet", response_model=ResponseDto)
async def get_wallet(exchange_name: str) -> ResponseDto[WalletDto | None]:
    try:
        wallet: WalletDto = await exchange_service.get_wallet(exchange_name)
        return ResponseDto[WalletDto](
            success=True,
            message=f"Get {exchange_name} wallet success",
            data=wallet
        )

    except Exception as e:
        print(e)
        return ResponseDto[None](
            success=False,
            message=f"{e}",
            data=None
        )


@router.post('/{exchange_name}', response_model=ResponseDto)
async def get_balance(exchange_name: str) -> ResponseDto[List[Any]]:
    try:
        positions = await exchange_service.fetch_position(exchange_name)

        return ResponseDto[List[Any]](
            success=True,
            message=exchange_name,
            data=positions
        )

    except Exception as e:
        print(e)
        return ResponseDto[List[Any]](
            success=False,
            message=f"{e}",
            data=[]
        )


@router.get('/keys/{exchange_name}', response_model=ResponseDto)
async def get_exchange_keys(exchange_name: str) -> ResponseDto[ApiKeys]:
    api_keys: ApiKeys = await api_key_service.get_exchange_api_keys(exchange_name)

    return ResponseDto[ApiKeys](
        success=True,
        message=f"Get {exchange_name} api key success.",
        data=api_keys
    )


# 거래소 api key, secret, password를 받아 ccxt 인스턴스를 업데이트합니다.
# 데스크탑 앱 실행 시, 로컬에 저장된 모든 거래소 api key, secret, password를 업데이트합니다.
# 이후 클라이언트에서 특정 거래소의 api key, secret, password 업데이트를 요청할 때마다 실행됩니다.
@router.patch('/keys', response_model=ResponseDto)
async def update_api_keys(dto: ExchangeApiKeyDto) -> ResponseDto[ApiKeys | None]:
    try:
        updated_api_keys: ApiKeys = await api_key_service.update_exchange_api_keys(dto)

        exchange_service.revalidate_cache(dto.exchange_name)

        return ResponseDto[ApiKeys](
            success=True,
            message=f"{dto.exchange_name} credential update success",
            data=updated_api_keys
        )
    except Exception as e:
        print('[UPDATE API KEYS EXCEPTION]', e)
        return ResponseDto[None](
            success=False,
            message=f"{dto.exchange_name} credential update fail",
            meta={"error": str(e)},
            data=None
        )


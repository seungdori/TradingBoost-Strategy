from typing import List, Optional, Union

from pydantic import BaseModel, Field


class AiSearchStartFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["binance","upbit", "bitget",  "okx", "binance_spot", "bitget_spot", "okx_spot"])
    enter_strategy: str = Field(examples=["long-short", "short", "long"])


class StartFeatureDto(BaseModel):
    """
    그리드 트레이딩 봇 시작 설정

    그리드 트레이딩 전략으로 봇을 시작할 때 필요한 모든 설정값입니다.
    """

    exchange_name: str = Field(
        ...,
        description="거래소 이름",
        examples=["okx", "binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"]
    )

    enter_strategy: str = Field(
        ...,
        description="진입 전략. long(롱 포지션만), short(숏 포지션만), long-short(양방향)",
        examples=["long", "short", "long-short"]
    )

    enter_symbol_count: int = Field(
        ...,
        description="동시에 거래할 심볼(코인) 개수. 1-20 권장",
        examples=[8, 5, 10],
        ge=1,
        le=20
    )

    enter_symbol_amount_list: Optional[List[float]] = Field(
        default=None,
        description="각 그리드 레벨별 투자 금액 리스트 (USDT). 길이는 grid_num과 같아야 함. 미지정 시 균등 배분",
        examples=[
            [5.0, 5.0, 5.0, 5.0, 5.0],  # 균등 배분
            [3.0, 4.0, 5.0, 6.0, 7.0],  # 점진적 증가
            [10.0, 8.0, 6.0, 4.0, 2.0]  # 점진적 감소
        ]
    )

    grid_num: int = Field(
        default=20,
        description="그리드 레벨 개수. 가격 범위를 몇 개의 구간으로 나눌지 결정. 1-40 사이",
        examples=[20, 15, 30],
        ge=1,
        le=40
    )

    leverage: Optional[int] = Field(
        None,
        description="레버리지 배수. 선물 거래 시 사용. 1-125 사이. 높을수록 리스크 증가",
        examples=[20, 10, 5, 1],
        ge=1,
        le=125
    )

    stop_loss: Optional[float] = Field(
        None,
        description="손절매 비율 (%). 포지션 손실이 이 비율을 초과하면 자동 청산",
        examples=[5.0, 10.0, 3.0],
        ge=0.1,
        le=50.0
    )

    custom_stop: Optional[int] = Field(
        None,
        description="사용자 정의 정지 조건 (분). 지정 시간 후 봇 자동 중지",
        examples=[2880, 1440, 4320],  # 2일, 1일, 3일
        ge=1
    )

    telegram_id: Optional[int] = Field(
        None,
        description="텔레그램 사용자 ID. 알림을 받을 텔레그램 계정",
        examples=[1709556958, 987654321]
    )

    user_id: Optional[Union[int, str]] = Field(
        None,
        description="사용자 ID",
        examples=[1234, "12345"]
    )

    api_key: Optional[str] = Field(
        None,
        description="거래소 API 키. 미리 등록된 경우 생략 가능",
        examples=["89d5cdd8-192b-4b7e-a4ce-d5666b7cdb42"]
    )

    api_secret: Optional[str] = Field(
        None,
        description="거래소 Secret 키. 미리 등록된 경우 생략 가능",
        examples=["135CF39F458BC20E0FA9FB3A9EA32B90"]
    )

    password: Optional[str] = Field(
        None,
        description="거래소 API Passphrase (OKX 등). 미리 등록된 경우 생략 가능",
        examples=["MyPassphrase123"]
    )

class StopFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","bitget", "upbit", "binance", "binance_spot", "bitget_spot", "okx_spot"])
    enter_strategy: str = Field(examples=["long-short", "short", "long-short"])
    user_id: int = Field(examples=[1234])


class TestFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["upbit","binance", "okx", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    leverage: Optional[int] = Field(None, examples=[1])


class CoinSellAllFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit",  "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    user_id:int = Field(examples=[1234])


class CoinDto(BaseModel):
    symbol: str = Field(examples=["BTCUSDT","ETC-USDT-SWAP","BTCUSDT", "BTC-KRW"])
    # amount: float = Field(examples=[0]) # Todo: 클라이언트에서 코인 갯수 필요한지 확인


class CoinSellFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    user_id: int = Field(examples=[1234])
    qty_percent: Optional[int] = Field(None, examples=[50])
    coins: List[CoinDto]
    # symbol: List[str] = Field(examples=["BTCUSDT", "BTC-KRW"])
    # coin amount? # Todo: 클라이언트에서 코인 갯수 필요한지 확인

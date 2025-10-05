import asyncio
from typing import List, Any, Dict
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Body
from pydantic import Field
from GRID.dtos.feature import CoinDto
from shared.dtos.response import ResponseDto
from GRID.dtos.symbol import AccessListDto

from GRID.routes.connection_manager import ConnectionManager
from shared.dtos.trading import WinrateDto
from GRID.services import trading_data_service, trading_service
import aiosqlite
router = APIRouter(prefix="/trading", tags=["trading"])
import logging

logging.basicConfig(level=logging.DEBUG)


        
#@router.get("/messages/{user_id}")
#async def get_user_messages(user_id: int):
#    messages = manager.get_user_messages(user_id)  # 저장된 메시지를 조회합니다.
#    print("[GET USER MESSAGES]", messages)
#    return {"user_id": user_id, "messages": messages}
        
#@router.post("/logs/{user_id}/")
#async def add_log_endpoint(user_id: int, log_message: str = Query(...)):
#    message = f"User {user_id}: {log_message}"
#    await manager.add_user_message(user_id, message)  # 메시지를 저장합니다.
#    print("[LOG BROADCASTED]", message)
#    return {"message": "Log broadcasted successfully"}
#
# Do not remove {enter_strategy}
@router.get('/{exchange_name}/{enter_strategy}/winrate', response_model=ResponseDto)
async def get_winrate(exchange_name: str, enter_strategy: str) -> ResponseDto[List[WinrateDto]]:
    print('[GET WIN RATE]', exchange_name, enter_strategy)
    win_rates: List[WinrateDto] = await trading_data_service.get_win_rates(
        exchange_name=exchange_name, enter_strategy=enter_strategy
    )
    return ResponseDto[List[WinrateDto]](
        success=True,
        message="Success to fetch win rates.",
        meta={'win_rates_length': len(win_rates)},
        data=win_rates,
    )


@router.post('/{exchange_name}/target_pnl')
async def set_target_pnl(exchange_name : str, user_id : int, target_pnl : float, target_type : str):
    print('[SET TARGET PNL]', exchange_name, user_id, target_pnl, target_type)
    



# Do not remove {enter_strategy}
@router.post('/{exchange_name}/{enter_strategy}/chart', response_model=ResponseDto)
async def create_chart_image(exchange_name: str, dto: CoinDto, enter_strategy: str,) -> ResponseDto[str | None]:
    print("[CREATE CHART]", exchange_name, dto)
    try:
        file_url = await trading_data_service.create_chart_image(
            exchange_name=exchange_name,
            selected_coin_name=dto.symbol,
            enter_strategy=enter_strategy
        )
        return ResponseDto[str](
            success=True,
            message="Success to fetch trading logs.",
            data=file_url
        )

    except Exception as e:
        return ResponseDto[str](
            success=False,
            message=str(e),
            data=None
        )





async def get_black_list(exchange_name: str, user_id: int):
    db_path = f'{exchange_name}_users.db'
    logging.debug(f"Connecting to database: {db_path}")
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('SELECT symbol FROM blacklist WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()
        logging.debug(f"Fetched symbols: {symbols}")
    return [symbol[0] for symbol in symbols] if symbols else []


@router.get("/blacklist/{exchange_name}/{user_id}", response_model=ResponseDto)
async def get_black_list_endpoint(exchange_name: str, user_id: int) -> ResponseDto:
    try:
        symbols = await get_black_list(exchange_name, user_id)
        logging.debug(f"Returning symbols: {symbols}")
        return ResponseDto(
            success=True,
            message="Success to get blacklist",
            data=symbols
        )
    except Exception as e:
        logging.error(f"Error: {e}")
        return ResponseDto(
            success=False,
            message="Error to get blacklist",
            meta={"error": str(e)},
            data=None
        )

async def get_white_list(exchange_name: str, user_id: int):
    db_path = f'{exchange_name}_users.db'
    logging.debug(f"Connecting to database: {db_path}")
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('SELECT symbol FROM whitelist WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()
        logging.debug(f"Fetched symbols: {symbols}")
    return [symbol[0] for symbol in symbols] if symbols else []

@router.get("/whitelist/{exchange_name}/{user_id}", response_model=ResponseDto)
async def get_white_list_endpoint(exchange_name: str, user_id: int) -> ResponseDto:
    try:
        symbols = await get_white_list(exchange_name, user_id)
        logging.debug(f"Returning symbols: {symbols}")
        return ResponseDto(
            success=True,
            message="Success to get whitelist",
            data=symbols
        )
    except Exception as e:
        logging.error(f"Error: {e}")
        return ResponseDto(
            success=False,
            message="Error to get whitelist",
            meta={"error": str(e)},
            data=None
        )

async def add_symbol_to_db(exchange_name: str, user_id: int, symbol: str, list_type: str):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        await db.execute(f'INSERT INTO {list_type} (user_id, symbol) VALUES (?, ?)', (user_id, symbol))
        await db.commit()

@router.put('/symbols/access', response_model=ResponseDto)
async def add_symbol_access_list(
    exchange_name: str = Query(..., description="Name of the exchange", example="okx"),
    user_id: int = Query(..., description="User ID", example=1234),
    symbols: str = Query(..., description="Comma-separated symbols to add", example="BTC,ETH,XRP"),
    type: str = Query(..., description="Type of the list, either 'blacklist' or 'whitelist'", example="blacklist")
) -> ResponseDto:
    try:
        # Split the comma-separated string into a list and strip whitespace
        symbol_list = [symbol.strip() for symbol in symbols.split(',')]
        
        for symbol in symbol_list:
            await add_symbol_to_db(exchange_name, user_id, symbol, type)
        
        updated = await trading_service.get_list_from_db(exchange_name, user_id, type)
        return ResponseDto(
            success=True,
            message="Success to add symbols to list",
            data=updated
        )
    except Exception as e:
        return ResponseDto(
            success=False,
            message="Error to add symbols to list",
            meta={"error": str(e)},
            data=None
        )


async def delete_symbol_from_db(exchange_name: str, user_id: int, symbol: str, list_type: str):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        await db.execute(f'DELETE FROM {list_type} WHERE user_id = ? AND symbol = ?', (user_id, symbol))
        await db.commit()


@router.delete('/symbols/access', response_model=ResponseDto)
async def delete_symbol_access_item(dto: AccessListDto = Body(...)) -> ResponseDto:
    print("[SYMBOL ACCESS LIST]", dto)
    try:
        for symbol in dto.symbols:
            await delete_symbol_from_db(dto.exchange_name, dto.user_id, symbol, dto.type)
        
        updated = await trading_service.get_list_from_db(dto.exchange_name, dto.user_id, dto.type)

        return ResponseDto(
            success=True,
            message="Success to delete symbols from list",
            data=updated
        )
    except Exception as e:
        return ResponseDto(
            success=False,
            message="Error to delete symbols from list",
            meta={"error": str(e)},
            data=None
        )
        
        

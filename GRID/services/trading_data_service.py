import os
from typing import List
import asyncio
import shared.exchange_apis
from shared.dtos.trading import TradingDataDto, WinrateDto
from GRID.repositories import trading_data_repository, trading_log_repository
from GRID.strategies import grid


async def fetch_trading_data(exchange_name: str, symbols: List[str]) -> List[TradingDataDto]:
    fetch_results: List[TradingDataDto] = []
    for symbol in symbols:
        trading_data = await trading_data_repository.fetch_db_prices(exchange_name=exchange_name, symbol=symbol)
        if trading_data:
            fetch_results.append(trading_data)

    return fetch_results


def get_trading_logs(exchange_name: str) -> List[str]:
    result: list[str] = trading_log_repository.get_trading_messages(exchange_name)
    return result


def put_trading_log(log: str) -> None:
    trading_log_repository.put_trading_message(log)


async def create_chart_image(exchange_name: str, selected_coin_name: str, enter_strategy : str) -> str:
    relative_file_path = f"./{selected_coin_name}_chart.png"
    full_path = os.path.abspath(relative_file_path)
    
    # 경로확인 
    if not os.path.exists(full_path):
        # 차트가 없는 경우, 차트 새로 생성
        try:
            await grid.read_csv_and_plot(exchange_name=exchange_name, coin_name=selected_coin_name, direction=enter_strategy)  # type: ignore[attr-defined]
            print(f"{selected_coin_name}에 대한 차트를 생성했습니다. {full_path}에 저장되었습니다.")
        except Exception as e:
            print(f"Error creating chart: {e}")
            
    else:
        print(f"{selected_coin_name}에 대한 차트는 {full_path}에 존재합니다.")
    
    return full_path

async def get_win_rates(exchange_name: str, enter_strategy : str) -> List[WinrateDto]:
    try:
        result: list[WinrateDto] = await grid.build_sort_ai_trading_data(exchange_name, enter_strategy)
        return result
    except Exception as e:
        print('[GET WIN RATE EXCEPTION]', e)
        return []

def process_data(data):
    # 튜플에서 DataFrame 추출
    long_data, short_data, total_data = data

    # 필요한 컬럼 선택
    processed_data = total_data[['name', 'long_win_rate', 'short_win_rate', 'total_win_rate']]
    return processed_data


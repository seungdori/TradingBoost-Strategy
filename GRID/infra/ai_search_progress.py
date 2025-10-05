from GRID.dtos.ai_search import AiSearchProgress


class AiSearchProgressStore:
    def __init__(self):
        # Use a dictionary to store AiSearchProgress instances, keyed by (exchange, enter_strategy)
        self.__progress = {
            ('binance','그리드','long'): AiSearchProgress(
                exchange_name='binance' ,enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('binance','그리드','short'): AiSearchProgress(
                exchange_name='binance',enter_strategy='short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('binance','그리드','long-short'): AiSearchProgress(
                exchange_name='binance',enter_strategy='long-short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('binance_spot', '그리드', 'long'): AiSearchProgress(
                exchange_name='binance_spot', enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('binance_spot', '그리드', 'short'): AiSearchProgress(
                exchange_name='binance_spot', enter_strategy='short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('binance_spot', '그리드', 'long-short'): AiSearchProgress(
                exchange_name='binance_spot', enter_strategy='long-short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),

            ('bitget','그리드','long'): AiSearchProgress(
                exchange_name='bitget' ,enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('bitget','그리드','short'): AiSearchProgress(
                exchange_name='bitget',enter_strategy='short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('bitget','그리드','long-short'): AiSearchProgress(
                exchange_name='bitget',enter_strategy='long-short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('bitget_spot', '그리드', 'long'): AiSearchProgress(
                exchange_name='bitget_spot', enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('okx','그리드','long'): AiSearchProgress(
                exchange_name='okx',enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('okx','그리드','short'): AiSearchProgress(
                exchange_name='okx',enter_strategy='short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('okx','그리드','long-short'): AiSearchProgress(
                exchange_name='okx',enter_strategy='long-short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('okx_spot', '그리드', 'long'): AiSearchProgress(
                exchange_name='okx_spot', enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('okx_spot', '그리드', 'short'): AiSearchProgress(
                exchange_name='okx_spot', enter_strategy='short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('okx_spot', '그리드', 'long-short'): AiSearchProgress(
                exchange_name='okx_spot', enter_strategy='long-short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),

            ('upbit','그리드','long'): AiSearchProgress(
                exchange_name='upbit' ,enter_strategy='long', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('upbit','그리드','short'): AiSearchProgress(
                exchange_name='upbit' ,enter_strategy='short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
            ('upbit','그리드','long-short'): AiSearchProgress(
                exchange_name='upbit',enter_strategy='long-short', current_progress_symbol='x',
                completed_symbol_count=0, total_symbol_count=0, status='stopped'
            ),
        }

    def get_progress(self, exchange_name: str, enter_strategy: str) -> AiSearchProgress:
        key = (exchange_name.lower() ,enter_strategy.lower())
        if key in self.__progress:
            return self.__progress[key]
        else:
            # Handle case where specific strategy is not required/used
            for (exchange, enter_strategy), progress in self.__progress.items():
                if exchange == exchange_name.lower():
                    return progress
            raise ValueError(f'Unknown exchange or strategy combination: {exchange_name}, {enter_strategy}')

    def update(
            self,
            exchange_name: str, enter_strategy: str, current_progress_symbol: str,
            current_completed_symbol_count: int, current_total_symbol_count: int, status: str
    ):
        key = (exchange_name.lower(), enter_strategy.lower())
        if key in self.__progress:
            progress = self.__progress[key]
            progress.current_progress_symbol = current_progress_symbol
            progress.completed_symbol_count = current_completed_symbol_count
            progress.total_symbol_count = current_total_symbol_count
            progress.status = status
        else:
            raise ValueError(f'Unknown exchange or strategy combination: {exchange_name}, {enter_strategy}')


ai_search_progress_store = AiSearchProgressStore()
from dtos.ai_search import AiSearchProgress
from infra.ai_search_progress import ai_search_progress_store


def get_progress(exchange_name: str, enter_strategy: str) -> AiSearchProgress:
    return ai_search_progress_store.get_progress(exchange_name=exchange_name, enter_strategy=enter_strategy)


def update_progress(dto: AiSearchProgress):
    ai_search_progress_store.update(
        exchange_name=dto.exchange_name,
        enter_strategy=dto.enter_strategy,
        current_progress_symbol=dto.current_progress_symbol,
        current_completed_symbol_count=dto.completed_symbol_count,
        current_total_symbol_count=dto.total_symbol_count,
        status=dto.status
    )

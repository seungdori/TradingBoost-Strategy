from GRID.dtos.ai_search import AiSearchProgress
from GRID.dtos.feature import AiSearchStartFeatureDto
from GRID.repositories import ai_search_repository


def get_progress(exchange_name: str, enter_strategy: str) -> AiSearchProgress:
    return ai_search_repository.get_progress(exchange_name=exchange_name,
                                             enter_strategy=enter_strategy)


def init_progress(dto: AiSearchStartFeatureDto, status: str) -> None:
    ai_search_repository.update_progress(
        dto=AiSearchProgress(
            exchange_name=dto.exchange_name,
            enter_strategy=dto.enter_strategy,
            current_progress_symbol='x',
            completed_symbol_count=0,
            total_symbol_count=0,
            status=status
        )
    )


def update_progress(dto: AiSearchProgress) -> None:
    ai_search_repository.update_progress(dto)

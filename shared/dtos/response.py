from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel as GenericModel
from pydantic import Field

DataType = TypeVar("DataType")


class ResponseDto(GenericModel, Generic[DataType]):
    """
    표준 API 응답 형식

    모든 API 엔드포인트에서 사용하는 통일된 응답 구조입니다.
    성공/실패 여부, 메시지, 추가 메타데이터, 실제 데이터를 포함합니다.

    Examples:
        성공 응답:
        ```python
        ResponseDto(
            success=True,
            message="Operation completed successfully",
            data={"user_id": 123, "name": "John"}
        )
        ```

        실패 응답:
        ```python
        ResponseDto(
            success=False,
            message="Validation failed",
            meta={"errors": ["Invalid email format"]},
            data=None
        )
        ```
    """

    success: bool = Field(
        ...,
        description="요청 성공 여부. True: 성공, False: 실패",
        examples=[True, False]
    )

    message: str = Field(
        default="",
        description="응답 메시지. 성공/실패에 대한 설명",
        examples=[
            "Operation completed successfully",
            "Bot started successfully",
            "Invalid API credentials",
            "Resource not found"
        ]
    )

    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="추가 메타데이터. 에러 상세 정보, 페이지네이션, 통계 등",
        examples=[
            {},
            {"error": "Connection timeout", "retry_after": 300},
            {"total_count": 100, "page": 1, "page_size": 20},
            {"execution_time_ms": 152}
        ]
    )

    data: Optional[DataType] = Field(
        default=None,
        description="실제 응답 데이터. 성공 시 요청한 리소스, 실패 시 None"
    )

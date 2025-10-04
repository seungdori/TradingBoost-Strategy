from typing import Generic, Optional, TypeVar
from pydantic import BaseModel as GenericModel

DataType = TypeVar("DataType")


class ResponseDto(GenericModel, Generic[DataType]):
    success: bool
    message: str = ""
    meta: dict = {}
    data: Optional[DataType] = None


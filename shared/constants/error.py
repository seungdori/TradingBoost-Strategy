from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TradingErrorName:
    start_feature_fail: str = "start_feature_fail"
    stop_feature_fail: str = 'stop_feature_fail'
    test_feature_fail: str = 'test_feature_fail'

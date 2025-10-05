"""GRID 전용 예외 클래스"""


class QuitException(Exception):
    """그리드 봇 종료 예외"""
    pass


class AddAnotherException(Exception):
    """그리드 추가 설정 예외"""
    pass

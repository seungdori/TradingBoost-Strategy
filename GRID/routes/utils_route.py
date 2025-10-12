from fastapi import APIRouter

from GRID.version import __version__

router = APIRouter(prefix="/utils", tags=["utils"])


@router.get(
    "/ping",
    summary="서버 상태 확인",
    description="""
# 서버 상태 확인 (Health Check)

서버가 정상적으로 동작하는지 확인하는 헬스체크 엔드포인트입니다.

## 반환 정보

- **data** (string): "pong" 문자열

## 사용 시나리오

- 🏥 **서버 상태 모니터링**: 주기적인 헬스체크로 서버 가동 상태 확인
- ⚖️ **로드 밸런서 헬스체크**: AWS ELB, Nginx 등에서 사용
- 🌐 **네트워크 연결 테스트**: API 접근 가능 여부 확인
- 🔍 **디버깅**: 서버 응답 여부 간단 확인
- 📊 **모니터링 툴 연동**: Prometheus, Datadog 등의 uptime 체크

## 예시 URL

```
GET /utils/ping
```
""",
    responses={
        200: {
            "description": "✅ 서버 정상 동작",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "서버 응답 성공",
                            "value": "pong"
                        }
                    }
                }
            }
        }
    }
)
async def health_check() -> str:
    return "pong"


@router.get(
    "/version",
    summary="API 버전 확인",
    description="""
# API 버전 확인

현재 실행 중인 GRID Trading Strategy API의 버전 정보를 반환합니다.

## 반환 정보

- **data** (string): API 버전 문자열
  - 형식: "major.minor.patch" (Semantic Versioning)
  - 예: "1.0.0", "2.1.5"

## 사용 시나리오

- 🔄 **버전 호환성 확인**: 클라이언트와 서버 버전 호환 여부 검증
- 🚀 **배포 검증**: 새 버전이 정상 배포되었는지 확인
- 🔧 **디버깅 정보 수집**: 버그 리포트 시 실행 중인 버전 정보 제공
- 📊 **모니터링**: 프로덕션 환경의 현재 버전 추적
- 🔐 **API 게이트웨이**: 버전별 라우팅 및 로드 밸런싱

## 버전 관리

GRID Trading Strategy는 Semantic Versioning을 따릅니다:
- **MAJOR**: 하위 호환 불가능한 API 변경
- **MINOR**: 하위 호환 가능한 기능 추가
- **PATCH**: 하위 호환 가능한 버그 수정

## 예시 URL

```
GET /utils/version
```
""",
    responses={
        200: {
            "description": "✅ 버전 정보 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "current_version": {
                            "summary": "현재 버전",
                            "value": "1.0.0"
                        },
                        "beta_version": {
                            "summary": "베타 버전",
                            "value": "2.0.0-beta.1"
                        }
                    }
                }
            }
        }
    }
)
async def version_check() -> str:
    return __version__

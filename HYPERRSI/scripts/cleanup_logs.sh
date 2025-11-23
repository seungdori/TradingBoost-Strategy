#!/bin/bash

##############################################################################
# 로그 자동 정리 스크립트
# 오래된 로그 파일을 압축하고 삭제하여 디스크 공간을 관리합니다.
##############################################################################

set -euo pipefail  # 에러 발생 시 스크립트 중단

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 로그 디렉토리 경로
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"

# 설정값
COMPRESS_DAYS=7      # N일 이상 된 로그 압축
DELETE_DAYS=30       # N일 이상 된 압축 로그 삭제
MAX_SIZE_MB=100      # N MB 이상인 로그 압축
DRY_RUN=false        # 실제 삭제 안하고 테스트만

# 사용법 출력
usage() {
    cat << EOF
사용법: $0 [옵션]

옵션:
    -c DAYS     DAYS일 이상 된 로그 압축 (기본: 7일)
    -d DAYS     DAYS일 이상 된 압축 로그 삭제 (기본: 30일)
    -s SIZE_MB  SIZE_MB 이상인 로그 즉시 압축 (기본: 100MB)
    -n          DRY RUN 모드 (실제 작업 안함, 테스트만)
    -h          도움말 표시

예제:
    $0                          # 기본 설정으로 실행
    $0 -c 3 -d 14              # 3일 이상 압축, 14일 이상 삭제
    $0 -n                       # DRY RUN 모드로 테스트
    $0 -s 50                    # 50MB 이상 로그 즉시 압축

EOF
    exit 1
}

# 옵션 파싱
while getopts "c:d:s:nh" opt; do
    case $opt in
        c) COMPRESS_DAYS=$OPTARG ;;
        d) DELETE_DAYS=$OPTARG ;;
        s) MAX_SIZE_MB=$OPTARG ;;
        n) DRY_RUN=true ;;
        h) usage ;;
        *) usage ;;
    esac
done

# 로그 디렉토리 확인
if [ ! -d "$LOG_DIR" ]; then
    echo -e "${RED}❌ 로그 디렉토리가 존재하지 않습니다: $LOG_DIR${NC}"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   로그 정리 스크립트 시작${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}설정:${NC}"
echo "  로그 디렉토리: $LOG_DIR"
echo "  압축 기준: ${COMPRESS_DAYS}일 이상"
echo "  삭제 기준: ${DELETE_DAYS}일 이상 (압축 파일)"
echo "  크기 기준: ${MAX_SIZE_MB}MB 이상"
if [ "$DRY_RUN" = true ]; then
    echo -e "  ${YELLOW}모드: DRY RUN (테스트만, 실제 작업 안함)${NC}"
fi
echo ""

# 통계 변수
COMPRESSED_COUNT=0
DELETED_COUNT=0
SPACE_FREED=0

# 1. 큰 로그 파일 즉시 압축
echo -e "${YELLOW}📦 1단계: 큰 로그 파일 압축 (${MAX_SIZE_MB}MB 이상)${NC}"
while IFS= read -r -d '' file; do
    if [[ "$file" != *.gz ]]; then
        size_mb=$(du -m "$file" | cut -f1)
        if [ "$size_mb" -ge "$MAX_SIZE_MB" ]; then
            echo "  압축 중: $(basename "$file") (${size_mb}MB)"
            if [ "$DRY_RUN" = false ]; then
                gzip -f "$file"
                COMPRESSED_COUNT=$((COMPRESSED_COUNT + 1))
                SPACE_FREED=$((SPACE_FREED + size_mb))
            fi
        fi
    fi
done < <(find "$LOG_DIR" -type f -name "*.log" -print0)
echo -e "${GREEN}✅ 압축 완료: ${COMPRESSED_COUNT}개 파일, 약 ${SPACE_FREED}MB 절약${NC}"
echo ""

# 2. 오래된 로그 파일 압축
echo -e "${YELLOW}📦 2단계: 오래된 로그 파일 압축 (${COMPRESS_DAYS}일 이상)${NC}"
COMPRESSED_COUNT=0
SPACE_FREED=0
while IFS= read -r -d '' file; do
    if [[ "$file" != *.gz ]]; then
        size_mb=$(du -m "$file" | cut -f1)
        echo "  압축 중: $(basename "$file") (${size_mb}MB)"
        if [ "$DRY_RUN" = false ]; then
            gzip -f "$file"
            COMPRESSED_COUNT=$((COMPRESSED_COUNT + 1))
            SPACE_FREED=$((SPACE_FREED + size_mb))
        fi
    fi
done < <(find "$LOG_DIR" -type f -name "*.log" -mtime +"$COMPRESS_DAYS" -print0)
echo -e "${GREEN}✅ 압축 완료: ${COMPRESSED_COUNT}개 파일, 약 ${SPACE_FREED}MB 절약${NC}"
echo ""

# 3. 오래된 압축 파일 삭제
echo -e "${YELLOW}🗑️  3단계: 오래된 압축 파일 삭제 (${DELETE_DAYS}일 이상)${NC}"
DELETED_COUNT=0
SPACE_FREED=0
while IFS= read -r -d '' file; do
    size_mb=$(du -m "$file" | cut -f1)
    echo "  삭제 예정: $(basename "$file") (${size_mb}MB)"
    if [ "$DRY_RUN" = false ]; then
        rm -f "$file"
        DELETED_COUNT=$((DELETED_COUNT + 1))
        SPACE_FREED=$((SPACE_FREED + size_mb))
    fi
done < <(find "$LOG_DIR" -type f -name "*.log.gz" -mtime +"$DELETE_DAYS" -print0)
echo -e "${GREEN}✅ 삭제 완료: ${DELETED_COUNT}개 파일, 약 ${SPACE_FREED}MB 절약${NC}"
echo ""

# 4. 빈 디렉토리 정리
echo -e "${YELLOW}🧹 4단계: 빈 디렉토리 정리${NC}"
EMPTY_DIR_COUNT=0
while IFS= read -r dir; do
    echo "  삭제 예정: $dir"
    if [ "$DRY_RUN" = false ]; then
        rmdir "$dir" 2>/dev/null || true
        EMPTY_DIR_COUNT=$((EMPTY_DIR_COUNT + 1))
    fi
done < <(find "$LOG_DIR" -type d -empty)
echo -e "${GREEN}✅ 빈 디렉토리 삭제: ${EMPTY_DIR_COUNT}개${NC}"
echo ""

# 5. 최종 통계
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   로그 정리 완료${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}📊 최종 통계:${NC}"
du -sh "$LOG_DIR"
echo ""
echo -e "${GREEN}✅ 모든 작업이 완료되었습니다!${NC}"

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo -e "${YELLOW}⚠️  DRY RUN 모드였습니다. 실제로는 아무 작업도 수행되지 않았습니다.${NC}"
    echo -e "${YELLOW}   실제 실행하려면 -n 옵션 없이 다시 실행하세요.${NC}"
fi

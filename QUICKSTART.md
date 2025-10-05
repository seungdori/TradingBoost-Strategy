# 🚀 빠른 시작 가이드

## 설치

```bash
# 1. 가상환경 활성화
source .venv/bin/activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일을 편집해서 API 키 등을 설정하세요
```

## 실행

### 방법 1: 실행 스크립트 사용 (가장 쉬움)

```bash
# 프로젝트 루트에서 어디서든 실행 가능
./run_hyperrsi.sh    # HYPERRSI 전략 실행 (포트 8000)
./run_grid.sh --port 8012    # GRID 전략 실행
```

### 방법 2: 직접 실행

```bash
# HYPERRSI
cd HYPERRSI
python main.py

# GRID
cd GRID
python main.py --port 8012
```

## Celery 워커 (HYPERRSI 필요)

```bash
cd HYPERRSI
./start_celery_worker.sh   # 워커 시작
./stop_celery_worker.sh    # 워커 중지
```

## API 문서

- HYPERRSI: http://localhost:8000/docs
- GRID: http://localhost:8012/docs

## 문제 해결

### Import 에러가 발생하면

```bash
# 프로젝트 루트에서 실행
pip install -e .
```

이제 모든 파일이 자동으로 경로를 설정하므로 PYTHONPATH 설정 없이 작동합니다!

## 더 자세한 정보

- [상세 문서](README.md)
- [개발자 가이드](CLAUDE.md)

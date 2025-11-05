# TradingBoost Redis 모니터링 스택

Prometheus와 Grafana를 사용한 Redis 풀 메트릭, 지연 시간 추적 및 운영 인사이트를 위한 종합 모니터링 설정입니다.

## 아키텍처 개요

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│ HYPERRSI/GRID   │────▶│  Prometheus  │────▶│   Grafana   │
│  FastAPI Apps   │     │   (Port 9090)│     │ (Port 3000) │
│  /metrics       │     └──────────────┘     └─────────────┘
└─────────────────┘            │
                               │
                        ┌──────▼──────┐
                        │ Node        │
                        │ Exporter    │
                        │ (Port 9100) │
                        └─────────────┘
```

## 주요 기능

### 수집되는 Prometheus 메트릭

**Redis 풀 메트릭**:
- `redis_pool_max_connections` - 최대 풀 크기
- `redis_pool_active_connections` - 현재 활성 연결 수
- `redis_pool_utilization_percent` - 풀 사용률 (0-100%)

**성능 메트릭**:
- `redis_operation_duration_seconds` - 작업 소요 시간 히스토그램
- `redis_connection_latency_ms` - 연결 지연 시간 (밀리초)

**헬스 메트릭**:
- `redis_circuit_breaker_state` - 서킷 브레이커 상태 (0=CLOSED, 1=HALF_OPEN, 2=OPEN)
- `redis_operation_errors_total` - 유형별 오류 카운터

### Grafana 대시보드 패널

1. **풀 사용률 게이지** - 임계값이 포함된 실시간 풀 사용량
2. **연결 풀 타임라인** - 시간에 따른 최대 연결 수 대 활성 연결 수
3. **서킷 브레이커 상태** - 현재 서킷 브레이커 상태
4. **지연 시간 메트릭** - p50, p95, p99 지연 시간
5. **작업 속도** - 초당 작업 수
6. **오류 비율** - 유형별 초당 오류 수

## 빠른 시작

### 사전 요구사항

- Docker 및 Docker Compose 설치
- HYPERRSI 및 GRID 애플리케이션 실행 중
- 애플리케이션에서 `/metrics` 엔드포인트 노출 (Prometheus 형식)

### 설치

1. **모니터링 스택 시작**:

```bash
docker-compose -f docker-compose.monitoring.yml up -d
```

2. **Grafana 접속**:

```
URL: http://localhost:3000
사용자명: admin
비밀번호: admin
```

3. **Prometheus 접속**:

```
URL: http://localhost:9090
```

### 설정 확인

1. Prometheus 타겟 확인:
   - http://localhost:9090/targets 로 이동
   - 모든 타겟이 "UP" 상태인지 확인 (hyperrsi, grid, node-exporter)

2. Grafana 데이터소스 확인:
   - Grafana → Configuration → Data Sources → Prometheus
   - "Test" 클릭하여 연결 확인

3. Redis 대시보드 열기:
   - Grafana → Dashboards → TradingBoost → Redis Pool Monitoring

## 설정

### Prometheus 설정

`monitoring/prometheus/prometheus.yml` 편집:

```yaml
scrape_configs:
  - job_name: 'hyperrsi'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['host.docker.internal:8000']

  - job_name: 'grid'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['host.docker.internal:8012']
```

**참고**: `host.docker.internal`은 macOS와 Windows에서 작동합니다. Linux에서는 `172.17.0.1`을 사용하거나 네트워크 브리지를 설정하세요.

### Grafana 대시보드 커스터마이징

1. 대시보드 설정으로 이동 (⚙️ 아이콘)
2. 필요에 따라 패널 편집
3. 변경사항 저장 (💾 아이콘)

## 알림 설정 (선택사항)

### 알림 규칙 예시

`monitoring/prometheus/alerts/redis_alerts.yml` 생성:

```yaml
groups:
  - name: redis_pool_alerts
    interval: 15s
    rules:
      - alert: RedisPoolHighUtilization
        expr: redis_pool_utilization_percent > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Redis 풀 사용률 높음"
          description: "풀 사용률이 {{ $value }}%입니다"

      - alert: RedisPoolCriticalUtilization
        expr: redis_pool_utilization_percent > 90
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Redis 풀 사용률 위험 수준"
          description: "풀 사용률이 {{ $value }}%입니다"

      - alert: RedisCircuitBreakerOpen
        expr: redis_circuit_breaker_state == 2
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis 서킷 브레이커 열림"
          description: "서킷 브레이커가 열렸습니다 - Redis를 사용할 수 없을 수 있습니다"

      - alert: RedisHighLatency
        expr: redis_connection_latency_ms > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Redis 지연 시간 높음"
          description: "연결 지연 시간이 {{ $value }}ms입니다"
```

알림을 활성화하려면 `prometheus.yml`의 `rule_files` 섹션 주석을 제거하세요.

## 유지보수

### 로그 보기

```bash
# Prometheus 로그
docker logs tradingboost-prometheus

# Grafana 로그
docker logs tradingboost-grafana

# 로그 실시간 모니터링
docker logs -f tradingboost-prometheus
```

### 서비스 재시작

```bash
# 전체 재시작
docker-compose -f docker-compose.monitoring.yml restart

# 특정 서비스 재시작
docker-compose -f docker-compose.monitoring.yml restart prometheus
docker-compose -f docker-compose.monitoring.yml restart grafana
```

### 모니터링 스택 중지

```bash
docker-compose -f docker-compose.monitoring.yml down

# 볼륨 제거 (데이터 손실됨)
docker-compose -f docker-compose.monitoring.yml down -v
```

### Grafana 대시보드 백업

```bash
# Grafana UI에서 대시보드 JSON 내보내기
# Dashboard → Settings → JSON Model → 클립보드에 복사

# 또는 전체 Grafana 데이터 백업
docker run --rm -v tradingboost_grafana-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/grafana-backup.tar.gz -C /data .
```

## FastAPI에서 메트릭 통합

### Prometheus 메트릭 노출

FastAPI 애플리케이션에 추가:

```python
from prometheus_client import make_asgi_app
from fastapi import FastAPI

app = FastAPI()

# Prometheus 메트릭 엔드포인트 마운트
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### 자동 메트릭 업데이트

`RedisPoolMonitor` 클래스가 자동으로 Prometheus 메트릭을 업데이트합니다:
- `health_check()`는 지연 시간과 오류 메트릭을 업데이트
- `get_pool_stats()`는 풀 사용률 메트릭을 업데이트

수동 계측이 필요하지 않습니다!

## 문제 해결

### Prometheus가 타겟을 수집할 수 없음

**증상**: Prometheus에서 타겟이 "DOWN"으로 표시됨

**해결책**:
1. 애플리케이션이 실행 중인지 확인: `curl http://localhost:8000/metrics`
2. Docker 네트워크 확인: `docker network inspect monitoring`
3. Linux에서는 prometheus.yml에서 `host.docker.internal`을 `172.17.0.1`로 변경
4. 방화벽 규칙 확인

### Grafana 대시보드에 데이터가 표시되지 않음

**증상**: 패널에 "No Data" 표시

**해결책**:
1. Prometheus 데이터소스 확인: Configuration → Data Sources → Test
2. Prometheus에 데이터가 있는지 확인: http://localhost:9090/graph
3. 쿼리 예시: `redis_pool_utilization_percent`
4. Grafana의 시간 범위 확인 (우측 상단)

### 높은 메모리 사용량

**증상**: Prometheus가 너무 많은 메모리를 사용

**해결책**:
1. docker-compose.yml에서 보관 기간 줄이기:
   ```yaml
   - '--storage.tsdb.retention.time=7d'  # 기본값은 30d
   ```
2. prometheus.yml에서 수집 간격 늘리기:
   ```yaml
   scrape_interval: 30s  # 기본값은 15s
   ```

## 참고 자료

- [Prometheus 문서](https://prometheus.io/docs/)
- [Grafana 문서](https://grafana.com/docs/)
- [Redis 모니터링 모범 사례](https://redis.io/docs/management/optimization/)

## 지원

문제가 있거나 질문이 있는 경우:
1. 애플리케이션 로그 확인: `docker logs tradingboost-prometheus`
2. Prometheus 타겟 검토: http://localhost:9090/targets
3. 메트릭 엔드포인트 확인: `curl http://localhost:8000/metrics`

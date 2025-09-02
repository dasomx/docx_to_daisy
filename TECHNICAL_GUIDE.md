# Backend Docs

## 개요

본 문서는 DOCX 문서를 DAISY 2.02 및 EPUB 3.0 형식으로 변환하는 시스템의 설치, 의존성, 아키텍처, API, 운영 방법을 설명합니다.

핵심 API는 `POST /convert-docx-to-daisy-and-epub3`로, 단일 업로드로 DAISY ZIP과 EPUB3를 동시에 생성합니다.

## 시스템 요구사항

- 운영체제: Linux, macOS, Windows (Docker 권장)
- 런타임: Python 3.9+ 또는 Docker 24+
- 외부 서비스: Redis 6+ (RQ 작업 큐 사용)
- 네트워킹:
  - API 기본 포트: 8000
  - Redis 기본 포트: 6379

## 설치 및 실행 (Docker Compose 권장)

`docker-compose.yml` 파일을 기반으로 Docker Compose를 사용하여 시스템을 설치하고 실행할 수 있습니다.

```bash
docker compose up -d --build
# API: http://localhost:8000
```

- Compose 구성 요소:

  - redis (`6389:6379`)
  - api
  - worker (자동 스케일, 복수 프로세스 지원)

## 환경 변수

- `REDIS_HOST` (기본: `localhost`, Compose: `redis`)
- `REDIS_PORT` (기본: `6379`)
- `REDIS_DB` (기본: `0`)
- `REDIS_PASSWORD` (옵션)
- `QUEUE_NAME` (기본: `daisy_queue`)
- `MAX_WORKERS` (기본: `6`, 워커 상한)

## CLI 엔트리포인트

- API 서버: `docx-to-daisy-api` (`src/docx_to_daisy/run_api.py`)
- 워커: `docx-to-daisy-worker` (`src/docx_to_daisy/worker.py`)

## 주요 의존성 (pyproject.toml)

- 문서 처리: `python-docx`, `lxml`
- 웹 서버: `fastapi`, `uvicorn`, `python-multipart`
- 비동기 처리: `redis`, `rq`
- 실시간 통신: `websockets`
- 운영 모니터링: `psutil` (GET `/queue/status`)
- TTS 확장 대비: `pyttsx3`

## 소스코드 구조

- `src/docx_to_daisy/api.py`: FastAPI 앱 (업로드/큐 등록/상태 조회/다운로드/큐 관리)
- `src/docx_to_daisy/tasks.py`: RQ 작업 정의 및 진행률 업데이트
  - `process_conversion_task`: DOCX → DAISY(+ZIP)
  - `process_epub3_conversion_task`: DOCX → EPUB3
  - `process_daisy_to_epub_task`: DAISY ZIP → EPUB3
  - `process_docx_to_daisy_and_epub_task`: DOCX → DAISY → EPUB3 → 검증 파이프라인 (핵심)
- `src/docx_to_daisy/converter/`
  - `docxTodaisy.py`: DOCX → DAISY 변환 (DTBook/NCX/SMIL/OPF/RES 생성)
  - `docxToepub.py`: DOCX → EPUB3 변환
  - `daisyToepub.py`: DAISY → EPUB3 변환
  - `utils.py`: 이미지 추출/텍스트 전처리 등
  - `validator.py`: DAISY 구조/스키마/무결성/접근성 검증
- `src/docx_to_daisy/markers.py`: 문서 내 마커 처리 (`$#1`, `$note{...}` 등)
- `src/docx_to_daisy/events.py`: Redis 이벤트 수신 → WebSocket 알림
- `src/docx_to_daisy/websocket.py`: WebSocket 커넥션 관리
- `src/docx_to_daisy/run_api.py`: API 실행 엔트리포인트
- `src/docx_to_daisy/worker.py`: 워커 실행 엔트리포인트

## 데이터 흐름

1. 클라이언트 DOCX 업로드 → API가 임시 디스크에 저장
2. API 작업 등록 → RQ 큐에 작업 등록
3. 워커 변환 수행 → 워커가 변환 실행
4. 상태 업데이트 → 진행률/메시지/타이밍 정보 Redis에 갱신 → WebSocket 브로드캐스트
5. 결과물 저장 및 제공 → `RESULTS_DIR/{task_id}.zip`, `{task_id}.epub` 저장 → 다운로드 API 제공

## API

### 변환 파이프라인 (메인)

- `POST /convert-docx-to-daisy-and-epub3`

폼 필드 예시:

```json
{
  "file": "(DOCX)",
  "title": "(string)",
  "author": "(string)",
  "publisher": "(string)",
  "language": "ko (default)",
  "priority": "1..10 (optional)"
}
```

응답 예시:

```json
{
  "task_id": "<uuid>",
  "status": "queued",
  "message": "DOCX→DAISY→EPUB3 파이프라인 작업이 큐에 추가되었습니다. 상태 조회 API를 사용하여 작업 상태를 확인하세요."
}
```

### 기타 변환

- `POST /convert`: DOCX → DAISY(+ZIP), priority 지원
- `POST /convert-epub3`: DOCX → EPUB3
- `POST /convert-batch`: 여러 DOCX 일괄 등록
- `POST /convert-daisy-to-epub`: DAISY ZIP → EPUB3

### 상태/다운로드/운영

- `GET /task/{task_id}`: 상태/진행률/메시지/시간 조회
- `GET /download/{task_id}`: DAISY ZIP 다운로드
- `GET /download-epub/{task_id}`: DOCX → EPUB3 다운로드
- `GET /download-daisy-to-epub/{task_id}`: DAISY → EPUB3 결과 다운로드
- `GET /queue/status`
- `GET /queue/clear`
- `GET /queue/retry-failed`

## WebSocket

- 경로: `/ws/task/{task_id}`

메시지 형식:

```json
{
  "task_id": "...",
  "status": "...",
  "progress": 50,
  "message": "...",
  "updated_at": "..."
}
```

브라우저 예시:

```javascript
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const socket = new WebSocket(`${protocol}//${location.host}/ws/task/${taskId}`);
socket.onmessage = (e) => console.log(JSON.parse(e.data));
```

# DOCX → DAISY/EPUB3 기술 가이드
## 개요

이 문서는 DOCX 문서를 DAISY 2.02 및 EPUB 3.0 형식으로 변환하는 시스템의 설치, 의존성, 아키텍처, API, 운영 방법을 기술합니다. 메인 API는 `POST /convert-docx-to-daisy-and-epub3`(단일 업로드로 DAISY ZIP과 EPUB3 동시 생성) 입니다.


## 시스템 요구사항
- 운영체제: Linux / macOS / Windows (Docker 권장)
- 런타임: Python 3.9+ 또는 Docker 24+
- 외부 서비스: Redis 6+ (RQ 작업 큐)
- 네트워킹: API 기본 포트 8000, Redis 기본 포트 6379


## 설치 및 실행

### Docker Compose (권장)
```bash
docker compose up -d --build
# API: http://localhost:8000
```

Compose 구성은 `docker-compose.yml`을 참고하세요. `redis`(6389:6379), `api`, `worker`(자동 스케일/복수 프로세스) 서비스가 함께 구동됩니다.
## 환경 변수
- `REDIS_HOST` (기본: `localhost` / Compose: `redis`)
- `REDIS_PORT` (기본: `6379`)
- `REDIS_DB` (기본: `0`)
- `REDIS_PASSWORD` (옵션)
- `QUEUE_NAME` (기본: `daisy_queue`)
- `MAX_WORKERS` (기본: `6`, 워커 상한)

CLI 엔트리포인트
- API 서버: `docx-to-daisy-api` (`src/docx_to_daisy/run_api.py`)
- 워커: `docx-to-daisy-worker` (`src/docx_to_daisy/worker.py`)

## 의존성
`pyproject.toml`의 주요 의존성:
- `python-docx`: DOCX 파싱
- `lxml`: XML 처리(DTBook/OPF/SMIL/NCX, EPUB 생성)
- `fastapi`, `uvicorn`: REST API 및 WebSocket 서버
- `python-multipart`: 파일 업로드 처리
- `redis`, `rq`: 작업 큐/비동기 처리
- `websockets`: 실시간 상태 전송
- `psutil`: 운영 시 리소스 모니터링(`GET /queue/status`)
- `pyttsx3`: TTS(현재 오디오 출력 비활성, 확장 대비)

## 소스코드 구조
- `src/docx_to_daisy/api.py`: FastAPI 앱. 업로드/큐 등록/상태 조회/다운로드/큐 관리 API.
- `src/docx_to_daisy/tasks.py`: RQ 작업 정의 및 진행률 업데이트.
  - `process_conversion_task`: DOCX → DAISY(+ZIP)
  - `process_epub3_conversion_task`: DOCX → EPUB3
  - `process_daisy_to_epub_task`: DAISY ZIP → EPUB3
  - `process_docx_to_daisy_and_epub_task`: DOCX → DAISY → EPUB3 파이프라인(핵심)
- `src/docx_to_daisy/converter/`
  - `docxTodaisy.py`: DOCX → DAISY 변환(구조 파싱, 마커, DTBook/NCX/SMIL/OPF/RES 생성)
  - `docxToepub.py`: DOCX → EPUB3 (표준 준수)
  - `daisyToepub.py`: DAISY → EPUB3 (컨테이너/OPF/nav 등)
  - `utils.py`: 이미지 추출/텍스트 전처리 등 유틸
  - `validator.py`: DAISY 파일 구조/스키마/무결성/접근성 검증
- `src/docx_to_daisy/markers.py`: `$#1`, `$note{...}` 등 문서 내 마커 처리
- `src/docx_to_daisy/events.py`: Redis 키스페이스/RQ 이벤트 수신 → WebSocket 알림
- `src/docx_to_daisy/websocket.py`: WebSocket 커넥션 관리
- `src/docx_to_daisy/run_api.py`: API 실행 엔트리포인트
- `src/docx_to_daisy/worker.py`: 워커 실행 엔트리포인트

## 데이터 흐름
1. 클라이언트가 DOCX 업로드 → API가 임시 디스크에 저장
2. API가 RQ 큐에 작업 등록 → 워커가 실제 변환 수행
3. 진행률/메시지/타이밍 메타는 Redis에 갱신, WebSocket으로 브로드캐스트
4. 결과물 저장(`RESULTS_DIR` 내부 `task_id.zip`/`task_id.epub`) → 다운로드 API 제공

## API

### 변환 파이프라인(메인)
- `POST /convert-docx-to-daisy-and-epub3`
  - 폼 필드: `file`(DOCX), `title?`, `author?`, `publisher?`, `language?="ko"`, `priority?=1..10`
  - 응답(예):

  ```json
  {"task_id":"<uuid>","status":"queued","message":"DOCX→DAISY→EPUB3 파이프라인 작업이 큐에 추가되었습니다. 상태 조회 API를 사용하여 작업 상태를 확인하세요."}
  ```
  - 후속: `GET /task/{task_id}` → 상태/진행률, `GET /download/{task_id}`(DAISY ZIP), `GET /download-epub/{task_id}`(EPUB3)

### 기타 변환
- `POST /convert`: DOCX → DAISY(+ZIP), `priority` 지원
- `POST /convert-epub3`: DOCX → EPUB3
- `POST /convert-batch`: 여러 DOCX 일괄 등록
- `POST /convert-daisy-to-epub`: DAISY ZIP → EPUB3

### 상태/다운로드/운영
- `GET /task/{task_id}`: 상태/진행률/메시지/단계별 시간 조회
- `GET /download/{task_id}`: DAISY ZIP 다운로드
- `GET /download-epub/{task_id}`: EPUB3 다운로드
- `GET /download-daisy-to-epub/{task_id}`: DAISY→EPUB3 결과 다운로드
- `GET /queue/status` | `GET /queue/clear` | `GET /queue/retry-failed`: 큐/워커 관리

### WebSocket
- 경로: `/ws/task/{task_id}`
- 메시지: `{ task_id, status, progress, message, updated_at, ... }`
- 브라우저 예시:
```javascript
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const socket = new WebSocket(`${protocol}//${location.host}/ws/task/${taskId}`);
socket.onmessage = (e) => console.log(JSON.parse(e.data));
```

### 요청 예시(cURL)
```bash
curl -F "file=@/path/book.docx" \
     -F "title=예제책" -F "author=홍길동" \
     http://localhost:8000/convert-docx-to-daisy-and-epub3
```
## 운영/모니터링
- Compose 구동 후 상태 확인: `GET /queue/status` (대기작업/워커/시스템 리소스)
- 대기열 비움: `GET /queue/clear`
- 실패 재시도: `GET /queue/retry-failed`
- Redis 헬스체크: `redis-cli -p 6389 ping` (Compose 기본 포워딩)
- 결과 보존: 작업/결과 TTL 24h, 영속화를 원하면 외부 볼륨 마운트 권장
## 제한사항
- 지원: 제목/단락/헤딩(1–3), 특수 마커(페이지/각주/사이드바 등)
- 미지원(현재): 오디오 출력, 복잡한 표/목록/수식 일부, 이미지 고급 처리 일부
## 라이선스/기여
- 라이선스: MIT (루트 `README.md` 참고)
- 기여: 버그 리포트/PR 환영



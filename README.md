# DOCX to DAISY/EPUB3 변환기

Microsoft Word 문서(DOCX)를 DAISY 형식으로 변환하는 파이썬 도구입니다.

## 기능

- DOCX → DAISY 2.02 변환 (DTBook, NCX, SMIL, OPF, Resources)
- DOCX → EPUB3 변환 지원
- 단일 요청으로 DAISY ZIP + EPUB3를 동시에 생성하는 파이프라인
- DAISY ZIP → EPUB3 변환 지원
- 제목/단락 구조 보존, Heading 수준(1~3) 처리
- 특수 마커(페이지, 각주, 사이드바 등) 처리
- RQ 기반 비동기 처리 및 작업 우선순위(priority) 지원
- WebSocket 실시간 진행률/상태 알림(`/ws/task/{task_id}`)
- 큐/워커 운영 API 제공(`/queue/status`, `/queue/clear`, `/queue/retry-failed`)

## 설치

```bash
# 가상 환경 생성 (선택사항)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 또는
venv\Scripts\activate  # Windows

# 필요한 패키지 설치
pip install -e .
```

## 빠른 시작

### Docker Compose

```bash
docker compose up -d --build
# API: http://localhost:8000
```

기본 환경 변수:

- `REDIS_HOST` (기본: `redis`)
- `REDIS_PORT` (기본: `6379`)
- `REDIS_DB` (기본: `0`)
- `QUEUE_NAME` (기본: `daisy_queue`)
- `MAX_WORKERS` (기본: `6`)

### 로컬 설치 (개발용)

## API 사용법

### 1) DOCX → DAISY 변환 (POST /convert)

DOCX 파일을 업로드하여 DAISY 변환 작업을 시작합니다.

**요청:**

```http
POST /convert
Content-Type: multipart/form-data

file: <DOCX 파일>
title: 책 제목 (선택 사항)
author: 저자 (선택 사항)
publisher: 출판사 (선택 사항)
language: ko (기본값)
```

**응답:**

```json
{
  "task_id": "f513056f-4cc7-405a-8051-b0f4f471c73c",
  "status": "queued",
  "message": "변환 작업이 큐에 추가되었습니다. 상태 조회 API를 사용하여 작업 상태를 확인하세요."
}
```

### 2) 작업 상태 확인 (GET /task/{task_id})

변환 작업의 상태를 확인합니다.

**요청:**

```http
GET /task/f513056f-4cc7-405a-8051-b0f4f471c73c
```

**응답:**

```json
{
  "task_id": "f513056f-4cc7-405a-8051-b0f4f471c73c",
  "status": "started",
  "progress": 20,
  "message": "DAISY 파일 생성 중...",
  "updated_at": 1630000000.123,
  "filename": "example.docx",
  "title": "책 제목",
  "author": "저자",
  "publisher": "출판사",
  "language": "ko"
}
```

**가능한 상태값:**

- `queued`: 작업이 큐에 등록되어 대기 중
- `started`: 작업이 처리 중
- `finished`: 작업이 완료됨
- `failed`: 작업이 실패함

### 3) DAISY 결과 다운로드 (GET /download/{task_id})

변환 작업이 완료된 후, 결과 ZIP 파일을 다운로드합니다.

**요청:**

```http
GET /download/f513056f-4cc7-405a-8051-b0f4f471c73c
```

**응답:**
ZIP 파일이 다운로드됩니다.

### 4) 웹소켓 실시간 상태 (WebSocket /ws/task/{task_id})

작업 상태를 실시간으로 모니터링하기 위한 웹소켓 연결입니다.

**프론트엔드 구현 예제 (JavaScript):**

```javascript
// 웹소켓 연결 생성
function connectToTaskStatus(taskId) {
  // 웹소켓 URL 생성 (프로토콜은 브라우저 URL과 일치하도록 설정)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/ws/task/${taskId}`;
  
  // 웹소켓 연결
  const socket = new WebSocket(wsUrl);
  
  // 이벤트 핸들러 설정
  socket.onopen = function(e) {
    console.log(`[WebSocket] 연결 성공: ${taskId}`);
  };
  
  socket.onmessage = function(event) {
    // 상태 정보 파싱
    const data = JSON.parse(event.data);
    console.log(`[WebSocket] 상태 업데이트:`, data);
    
    // UI 업데이트
    updateTaskUI(data);
    
    // 작업 완료 시 처리
    if (data.status === 'finished') {
      console.log(`[WebSocket] 작업 완료: ${data.task_id}`);
      
      // 결과 다운로드 URL 표시
      if (data.download_url) {
        showDownloadLink(data.download_url);
      }
    }
    
    // 작업 실패 시 처리
    if (data.status === 'failed') {
      console.error(`[WebSocket] 작업 실패: ${data.message}`);
      showErrorMessage(data.message);
    }
  };
  
  socket.onclose = function(event) {
    if (event.wasClean) {
      console.log(`[WebSocket] 연결 정상 종료, 코드=${event.code} 사유=${event.reason}`);
    } else {
      console.error('[WebSocket] 연결이 끊어졌습니다.');
    }
  };
  
  socket.onerror = function(error) {
    console.error(`[WebSocket] 오류 발생:`, error);
  };
  
  // 웹소켓 객체 반환
  return socket;
}

// UI 업데이트 예제
function updateTaskUI(data) {
  // 진행률 표시기 업데이트
  const progressBar = document.getElementById('progress-bar');
  if (progressBar && data.progress !== undefined) {
    progressBar.style.width = `${data.progress}%`;
    progressBar.setAttribute('aria-valuenow', data.progress);
  }
  
  // 상태 메시지 업데이트
  const statusMessage = document.getElementById('status-message');
  if (statusMessage && data.message) {
    statusMessage.textContent = data.message;
  }
  
  // 상태 표시기 업데이트
  const statusIndicator = document.getElementById('status-indicator');
  if (statusIndicator) {
    // 상태에 따른 클래스 적용
    statusIndicator.className = 'status-indicator';
    statusIndicator.classList.add(`status-${data.status}`);
    
    // 상태 텍스트 적용
    let statusText = '';
    switch(data.status) {
      case 'queued':
        statusText = '대기 중';
        break;
      case 'started':
        statusText = '처리 중';
        break;
      case 'finished':
        statusText = '완료됨';
        break;
      case 'failed':
        statusText = '실패함';
        break;
      default:
        statusText = data.status;
    }
    statusIndicator.textContent = statusText;
  }
}

// 다운로드 링크 표시 예제
function showDownloadLink(downloadUrl) {
  const downloadSection = document.getElementById('download-section');
  if (downloadSection) {
    downloadSection.style.display = 'block';
    
    const downloadLink = document.getElementById('download-link');
    if (downloadLink) {
      downloadLink.href = downloadUrl;
    }
  }
}

// 오류 메시지 표시 예제
function showErrorMessage(message) {
  const errorSection = document.getElementById('error-section');
  if (errorSection) {
    errorSection.style.display = 'block';
    
    const errorMessage = document.getElementById('error-message');
    if (errorMessage) {
      errorMessage.textContent = message;
    }
  }
}

// 예제: 변환 작업 시작 및 상태 모니터링
async function startConversion() {
  // 파일 업로드 및 변환 요청
  const formData = new FormData();
  const fileInput = document.getElementById('docx-file');
  
  formData.append('file', fileInput.files[0]);
  formData.append('title', document.getElementById('book-title').value);
  formData.append('author', document.getElementById('book-author').value);
  formData.append('publisher', document.getElementById('book-publisher').value);
  
  try {
    // API 호출
    const response = await fetch('/convert', {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      throw new Error(`요청 실패: ${response.status} ${response.statusText}`);
    }
    
    const data = await response.json();
    console.log('변환 작업 시작:', data);
    
    // 작업 ID 저장
    const taskId = data.task_id;
    
    // UI 업데이트
    document.getElementById('task-id').textContent = taskId;
    document.getElementById('conversion-status').style.display = 'block';
    
    // 웹소켓으로 실시간 상태 모니터링 시작
    const socket = connectToTaskStatus(taskId);
    
    // 타이머로 백업 폴링 (웹소켓 연결 실패 시 대비)
    const pollingInterval = setInterval(async () => {
      if (socket.readyState !== WebSocket.OPEN) {
        // 웹소켓 연결이 끊어진 경우 API로 상태 확인
        try {
          const statusResponse = await fetch(`/task/${taskId}`);
          if (statusResponse.ok) {
            const statusData = await statusResponse.json();
            updateTaskUI(statusData);
            
            // 작업이 종료된 경우 폴링 중지
            if (statusData.status === 'finished' || statusData.status === 'failed') {
              clearInterval(pollingInterval);
            }
          }
        } catch (error) {
          console.error('폴링 중 오류 발생:', error);
        }
      }
    }, 5000); // 5초 간격으로 폴링
    
  } catch (error) {
    console.error('변환 작업 시작 중 오류 발생:', error);
    showErrorMessage(`변환 작업 시작 중 오류가 발생했습니다: ${error.message}`);
  }
}
```

### 5) 일괄 변환 (POST /convert-batch)

### 6) DOCX → EPUB3 (POST /convert-epub3)

```http
POST /convert-epub3
Content-Type: multipart/form-data

file: <DOCX 파일>
title/author/publisher/language: 선택
```

응답 예시는 `/convert`와 동일한 형태(`task_id`, `status`, `message`).

### 7) DOCX → DAISY → EPUB3 파이프라인 (POST /convert-docx-to-daisy-and-epub3)

```http
POST /convert-docx-to-daisy-and-epub3
Content-Type: multipart/form-data

file: <DOCX 파일>
title/author/publisher/language: 선택
priority: 1..10 (선택)
```

완료 시 두 개의 다운로드 URL이 제공됩니다:

```json
{
  "download_urls": {
    "daisy": "/download/{task_id}",
    "epub3": "/download-epub/{task_id}"
  }
}
```

### 8) DAISY ZIP → EPUB3 (POST /convert-daisy-to-epub)

```http
POST /convert-daisy-to-epub
Content-Type: multipart/form-data

file: <DAISY ZIP>
```

다운로드: `GET /download-daisy-to-epub/{task_id}`

여러 DOCX 파일을 한 번에 업로드하여 DAISY 변환 작업을 시작합니다.

**요청:**

```http
POST /convert-batch
Content-Type: multipart/form-data

files: <DOCX 파일1>, <DOCX 파일2>, ...
title: 책 제목 접두사 (선택 사항)
author: 저자 (선택 사항)
publisher: 출판사 (선택 사항)
language: ko (기본값)
```

**응답:**

```json
{
  "total": 3,
  "success": 2,
  "error": 1,
  "tasks": [
    {
      "filename": "book1.docx",
      "task_id": "f513056f-4cc7-405a-8051-b0f4f471c73c",
      "status": "queued",
      "message": "변환 작업이 큐에 추가되었습니다."
    },
    {
      "filename": "book2.docx",
      "task_id": "a1b2c3d4-5e6f-7g8h-9i0j-k1l2m3n4o5p6",
      "status": "queued",
      "message": "변환 작업이 큐에 추가되었습니다."
    },
    {
      "filename": "invalid.txt",
      "status": "error", 
      "message": "DOCX 파일만 업로드 가능합니다."
    }
  ]
}
```

**참고사항:**

- 한 번에 최대 10개의 파일을 처리할 수 있습니다.
- 제목(title)이 제공되면 "제목 - 파일명" 형식으로 각 파일에 적용됩니다.
- 모든 파일에 동일한 저자와 출판사 정보가 적용됩니다.
- 각 파일은 개별 작업으로 처리되며, 각각 고유한 task_id가 할당됩니다.
- 각 작업의 상태는 `/task/{task_id}` API를 통해 확인할 수 있습니다.
- 결과 파일은 `/download/{task_id}` API를 통해 다운로드할 수 있습니다.

**프론트엔드 구현 예제 (JavaScript):**

```javascript
// 여러 파일 변환 요청 함수
async function startBatchConversion() {
  // 폼 데이터 생성
  const formData = new FormData();
  
  // 파일 입력 필드에서 선택된 모든 파일 추가
  const fileInput = document.getElementById('docx-files');
  for (let i = 0; i < fileInput.files.length; i++) {
    formData.append('files', fileInput.files[i]);
  }
  
  // 메타데이터 추가
  formData.append('title', document.getElementById('book-title-prefix').value);
  formData.append('author', document.getElementById('book-author').value);
  formData.append('publisher', document.getElementById('book-publisher').value);
  
  try {
    // API 호출
    const response = await fetch('/convert-batch', {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      throw new Error(`요청 실패: ${response.status} ${response.statusText}`);
    }
    
    const data = await response.json();
    console.log('일괄 변환 작업 시작:', data);
    
    // 결과 표시
    displayBatchResults(data);
    
    // 각 작업에 대한 상태 모니터링 시작
    for (const task of data.tasks) {
      if (task.status === 'queued') {
        // 웹소켓으로 실시간 상태 모니터링 시작
        connectToTaskStatus(task.task_id);
      }
    }
    
  } catch (error) {
    console.error('일괄 변환 작업 시작 중 오류 발생:', error);
    showErrorMessage(`일괄 변환 작업 시작 중 오류가 발생했습니다: ${error.message}`);
  }
}

// 일괄 변환 결과 표시 함수
function displayBatchResults(data) {
  const resultsContainer = document.getElementById('batch-results');
  if (!resultsContainer) return;
  
  // 결과 컨테이너 초기화
  resultsContainer.innerHTML = '';
  
  // 요약 정보 표시
  const summary = document.createElement('div');
  summary.className = 'batch-summary';
  summary.innerHTML = `
    <p>총 ${data.total}개 파일 중 ${data.success}개 성공, ${data.error}개 실패</p>
  `;
  resultsContainer.appendChild(summary);
  
  // 각 작업별 상태 표시
  const tasksList = document.createElement('div');
  tasksList.className = 'batch-tasks-list';
  
  data.tasks.forEach(task => {
    const taskItem = document.createElement('div');
    taskItem.className = `task-item ${task.status}`;
    taskItem.innerHTML = `
      <div class="filename">${task.filename}</div>
      <div class="status">${task.status === 'queued' ? '대기 중' : '오류'}</div>
      <div class="message">${task.message}</div>
    `;
    
    // 작업 ID가 있으면 상태 모니터링을 위한 컨테이너 추가
    if (task.task_id) {
      taskItem.setAttribute('data-task-id', task.task_id);
      const statusContainer = document.createElement('div');
      statusContainer.className = 'task-status-container';
      statusContainer.id = `status-${task.task_id}`;
      statusContainer.innerHTML = `
        <div class="progress">
          <div class="progress-bar" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
        <div class="status-message">대기 중...</div>
      `;
      taskItem.appendChild(statusContainer);
    }
    
    tasksList.appendChild(taskItem);
  });
  
  resultsContainer.appendChild(tasksList);
}
```


## 생성되는 파일

- `dtbook.xml`: DAISY 텍스트 콘텐츠
- `book.opf`: DAISY 패키지 파일
- `navigation.ncx`: 네비게이션 컨트롤 파일
- `mo0.smil`: 텍스트 동기화 정보
- `resources.res`: 리소스 정보

## 운영/관리 API

- `GET /queue/status`: 큐 길이, 워커 상태, 시스템 리소스
- `GET /queue/clear`: 대기 작업 비우기
- `GET /queue/retry-failed`: 실패 작업 재시도

## 제한사항

현재 버전은 다음 기능을 지원하지 않습니다:
- 오디오 콘텐츠
- 이미지
- 표
- 목록
- 수식

## 지원하는 DOCX 요소

- 제목 (Heading 1-3)
- 일반 문단
- 문서 메타데이터 (제목, 저자, 출판사, 언어)
- 특수 마커를 통한 페이지, 각주, 사이드바 등

## 라이선스

MIT License

## 기여하기

버그 리포트, 기능 제안, 풀 리퀘스트를 환영합니다.

## 명령행 도구 실행

### API 서버 실행

```bash
docx-to-daisy-api --host 0.0.0.0 --port 8000 \
  --redis-host localhost --redis-port 6379 --redis-db 0 --queue-name daisy_queue
```

### 워커 실행

```bash
docx-to-daisy-worker --workers 2
# 자동 스케일링(코어 수 기준): --auto-scale
# 풀 모드(복수 프로세스): --pool --workers 4
```

### Docker로 실행

```bash
docker compose up -d --build
```

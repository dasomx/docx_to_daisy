import os
import tempfile
import uuid
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form, WebSocket, WebSocketDisconnect, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import urllib.parse
import redis
from rq import Queue
from rq.job import Job, NoSuchJobError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from fastapi.params import Path as FastAPIPath
from rq.worker import Worker

from docx_to_daisy.converter.docxTodaisy import create_daisy_book, zip_daisy_output
from docx_to_daisy.converter.docxToepub import create_epub3_book
from .tasks import process_conversion_task, process_epub3_conversion_task
from .websocket import status_listener, manager
from .events import start_event_listener, stop_event_listener

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 로깅 미들웨어 클래스 정의
class NoLoggingMiddleware(BaseHTTPMiddleware):
    """특정 경로에 대한 FastAPI 액세스 로그를 비활성화하는 미들웨어"""
    
    def __init__(self, app: ASGIApp, exclude_paths: list = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or []
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        
        # 제외할 경로인지 확인
        for exclude_path in self.exclude_paths:
            if exclude_path in path:
                # 로깅 레벨을 일시적으로 변경
                uvicorn_logger = logging.getLogger("uvicorn.access")
                original_level = uvicorn_logger.level
                uvicorn_logger.setLevel(logging.WARNING)
                
                response = await call_next(request)
                
                # 로깅 레벨 복원
                uvicorn_logger.setLevel(original_level)
                return response
        
        # 제외 경로가 아닌 경우 정상 처리
        return await call_next(request)

app = FastAPI(
    title="DOCX to DAISY/EPUB3 API",
    description="DOCX 파일을 DAISY 및 EPUB3 형식으로 변환하는 API",
    version="0.2.0"
)

# 미들웨어 추가 - /task/ 경로에 대한 로깅 비활성화
app.add_middleware(NoLoggingMiddleware, exclude_paths=["/task/"])

# 이벤트 리스너 시작 및 종료
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 호출되는 이벤트 핸들러"""
    start_event_listener()
    logger.info("애플리케이션 시작: 이벤트 리스너 초기화 완료")

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 호출되는 이벤트 핸들러"""
    stop_event_listener()
    logger.info("애플리케이션 종료: 이벤트 리스너 정리 완료")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용 (프로덕션에서는 특정 출처만 허용하는 것이 좋습니다)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis 연결 정보
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
QUEUE_NAME = os.environ.get('QUEUE_NAME', 'daisy_queue')

# 임시 파일 저장 디렉토리
TEMP_DIR = Path(tempfile.gettempdir()) / "docx_to_daisy_api"
TEMP_DIR.mkdir(exist_ok=True)

# 변환 결과 저장 디렉토리
RESULTS_DIR = Path(tempfile.gettempdir()) / "docx_to_daisy_results"
RESULTS_DIR.mkdir(exist_ok=True)

# 작업 상태 (Redis에 저장되지만 여기서는 메모리에 임시 저장)
job_statuses: Dict[str, Any] = {}

def get_redis_connection():
    """Redis 연결을 생성하고 반환합니다."""
    try:
        redis_conn = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
        # 연결 테스트
        redis_conn.ping()
        return redis_conn
    except redis.ConnectionError as e:
        logger.error(f"Redis 연결 실패: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Redis 서버에 연결할 수 없습니다: {str(e)}")
    except Exception as e:
        logger.error(f"Redis 연결 중 예상치 못한 오류: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Redis 연결 중 오류가 발생했습니다: {str(e)}")

def get_queue():
    """RQ 큐를 생성하고 반환합니다."""
    try:
        return Queue(QUEUE_NAME, connection=get_redis_connection())
    except Exception as e:
        logger.error(f"큐 생성 실패: {str(e)}")
        raise HTTPException(status_code=503, detail=f"작업 큐를 생성할 수 없습니다: {str(e)}")

@app.post("/convert")
async def convert_docx_to_daisy(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    publisher: Optional[str] = Form(None),
    language: str = Form("ko"),
    priority: Optional[int] = Form(5),  # 우선순위 (1-10, 1이 가장 높음)
    background_tasks: BackgroundTasks = None
):
    """
    DOCX 파일을 DAISY 형식으로 변환하고 작업 ID를 반환합니다.
    
    - **file**: 변환할 DOCX 파일
    - **title**: 책 제목 (선택 사항)
    - **author**: 저자 (선택 사항)
    - **publisher**: 출판사 (선택 사항)
    - **language**: 언어 코드 (기본값: ko)
    - **priority**: 작업 우선순위 (1-10, 1이 가장 높음, 기본값: 5)
    """
    logger.info(f"변환 요청 받음: 파일명={file.filename}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}, 우선순위={priority}")
    
    # 파일 확장자 확인
    if not file.filename.lower().endswith('.docx'):
        logger.error(f"잘못된 파일 형식: {file.filename}")
        raise HTTPException(status_code=400, detail="DOCX 파일만 업로드 가능합니다.")
    
    # 우선순위 검증
    if priority is not None:
        try:
            priority = int(priority)
            if priority < 1 or priority > 10:
                raise ValueError("우선순위는 1-10 사이의 값이어야 합니다.")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="우선순위는 1-10 사이의 정수여야 합니다.")
    else:
        priority = 5  # 기본 우선순위
    
    # 고유 ID 생성
    task_id = str(uuid.uuid4())
    logger.info(f"작업 ID 생성: {task_id}")
    
    # 임시 파일 경로 설정
    temp_docx_path = TEMP_DIR / f"{task_id}.docx"
    zip_file_path = RESULTS_DIR / f"{task_id}.zip"
    
    try:
        # 업로드된 파일 저장
        logger.info(f"임시 파일 저장 시작: {temp_docx_path}")
        with open(temp_docx_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info("임시 파일 저장 완료")
        
        # 큐에 작업 추가 (우선순위 적용)
        queue = get_queue()
        job = queue.enqueue(
            process_conversion_task,
            args=(
                str(temp_docx_path),
                str(zip_file_path),
                title,
                author,
                publisher,
                language
            ),
            job_id=task_id,
            timeout=3600,  # 1시간 제한
            job_timeout=3600,
            result_ttl=86400,  # 결과는 24시간 유지
            ttl=86400,  # 작업은 24시간 유지
            priority=priority  # 우선순위 설정
        )
        
        # 작업 상태 설정
        job_statuses[task_id] = {
            "status": "queued",
            "filename": file.filename,
            "title": title,
            "author": author,
            "publisher": publisher,
            "language": language,
            "priority": priority
        }
        
        # 임시 파일은 작업 완료 후 정리 - 이미 큐에 포함된 작업이 처리함
        logger.info(f"작업이 큐에 추가됨: {task_id} (우선순위: {priority})")
        
        return {
            "task_id": task_id,
            "status": "queued",
            "priority": priority,
            "message": f"변환 작업이 큐에 추가되었습니다. (우선순위: {priority}) 상태 조회 API를 사용하여 작업 상태를 확인하세요."
        }
    
    except HTTPException:
        # HTTPException은 그대로 전달
        raise
    except redis.ConnectionError as e:
        logger.error(f"Redis 연결 오류로 인한 변환 작업 등록 실패: {str(e)}")
        # 임시 파일 정리
        if temp_docx_path.exists():
            temp_docx_path.unlink()
        raise HTTPException(status_code=503, detail=f"Redis 서버에 연결할 수 없어 변환 작업을 등록할 수 없습니다: {str(e)}")
    except Exception as e:
        logger.error(f"변환 작업 등록 중 오류 발생: {str(e)}", exc_info=True)
        # 오류 발생 시 임시 파일 정리
        if temp_docx_path.exists():
            temp_docx_path.unlink()
        raise HTTPException(status_code=500, detail=f"변환 작업 등록 중 오류가 발생했습니다: {str(e)}")

@app.get("/task/{task_id}")
async def get_task_status(task_id: str = FastAPIPath(..., description="변환 작업 ID")):
    """
    주어진 작업 ID에 대한 변환 작업 상태를 반환합니다.
    """
    # logger.info(f"작업 상태 조회: {task_id}") - 로그 남기지 않도록 주석 처리
    
    try:
        # Redis에서 작업 상태 확인
        redis_conn = get_redis_connection()
        queue = Queue(connection=redis_conn)
        
        try:
            job = Job.fetch(task_id, connection=redis_conn)
            status = job.get_status()
            
            # 결과 확인
            result = job.result
            error = job.exc_info
            
            response = {
                "task_id": task_id,
                "status": status
            }
            
            # 진행률 정보 추가
            job_meta = job.meta
            if job_meta:
                progress = job_meta.get('progress', 0)
                message = job_meta.get('message', '')
                updated_at = job_meta.get('updated_at')
                
                response.update({
                    "progress": progress,
                    "message": message,
                    "updated_at": updated_at
                })
            
            # 로컬 상태 정보 추가
            if task_id in job_statuses:
                response.update({
                    "filename": job_statuses[task_id].get("filename"),
                    "title": job_statuses[task_id].get("title"),
                    "author": job_statuses[task_id].get("author"),
                    "publisher": job_statuses[task_id].get("publisher"),
                    "language": job_statuses[task_id].get("language")
                })
            
            # 오류 정보 추가
            if error:
                response["error"] = error
                response["error_type"] = "job_execution_error"
            
            # 결과 파일 정보 추가
            if status == "finished":
                zip_file_path = RESULTS_DIR / f"{task_id}.zip"
                epub_file_path = RESULTS_DIR / f"{task_id}.epub"
                
                if zip_file_path.exists():
                    response["download_url"] = f"/download/{task_id}"
                    response["format"] = "daisy"
                    if "message" not in response or not response["message"]:
                        response["message"] = "DAISY 변환 작업이 완료되었습니다. 다운로드 URL을 사용하여 결과를 받으세요."
                elif epub_file_path.exists():
                    response["download_url"] = f"/download-epub/{task_id}"
                    response["format"] = "epub3"
                    if "message" not in response or not response["message"]:
                        response["message"] = "EPUB3 변환 작업이 완료되었습니다. 다운로드 URL을 사용하여 결과를 받으세요."
                else:
                    if "message" not in response or not response["message"]:
                        response["message"] = "변환 작업이 완료되었지만 결과 파일을 찾을 수 없습니다."
            elif status == "failed":
                if "message" not in response or not response["message"]:
                    response["message"] = "변환 작업이 실패했습니다."
                response["error_type"] = "job_failed"
            elif status == "started":
                if "message" not in response or not response["message"]:
                    response["message"] = "변환 작업이 진행 중입니다."
            else:
                if "message" not in response or not response["message"]:
                    response["message"] = "변환 작업이 대기 중입니다."
            
            return response
            
        except NoSuchJobError:
            # 작업을 찾을 수 없는 경우, 결과 파일이 있는지 확인
            zip_file_path = RESULTS_DIR / f"{task_id}.zip"
            epub_file_path = RESULTS_DIR / f"{task_id}.epub"
            
            if zip_file_path.exists():
                return {
                    "task_id": task_id,
                    "status": "finished",
                    "progress": 100,
                    "download_url": f"/download/{task_id}",
                    "format": "daisy",
                    "message": "DAISY 변환 작업이 완료되었습니다. 다운로드 URL을 사용하여 결과를 받으세요."
                }
            elif epub_file_path.exists():
                return {
                    "task_id": task_id,
                    "status": "finished",
                    "progress": 100,
                    "download_url": f"/download-epub/{task_id}",
                    "format": "epub3",
                    "message": "EPUB3 변환 작업이 완료되었습니다. 다운로드 URL을 사용하여 결과를 받으세요."
                }
            else:
                raise HTTPException(status_code=404, detail=f"작업 ID {task_id}를 찾을 수 없습니다.")
    
    except HTTPException:
        raise
    except redis.ConnectionError as e:
        logger.error(f"Redis 연결 오류로 인한 작업 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Redis 서버에 연결할 수 없어 작업 상태를 조회할 수 없습니다: {str(e)}")
    except Exception as e:
        logger.error(f"작업 상태 조회 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"작업 상태 조회 중 오류가 발생했습니다: {str(e)}")

@app.get("/download/{task_id}")
async def download_result(task_id: str = FastAPIPath(..., description="다운로드할 변환 작업 ID")):
    """
    완료된 DAISY 변환 작업의 결과를 다운로드합니다.
    """
    logger.info(f"DAISY 결과 다운로드 요청: {task_id}")
    
    try:
        # DAISY ZIP 파일 경로
        zip_file_path = RESULTS_DIR / f"{task_id}.zip"
        
        if not zip_file_path.exists():
            logger.error(f"DAISY 결과 파일을 찾을 수 없음: {zip_file_path}")
            raise HTTPException(status_code=404, detail="DAISY 변환 결과 파일을 찾을 수 없습니다.")
        
        # 파일명 설정
        if task_id in job_statuses and job_statuses[task_id].get("filename"):
            original_filename = job_statuses[task_id]["filename"]
            filename = f"{Path(original_filename).stem}.zip"
        else:
            filename = f"daisy_{task_id}.zip"
        
        # FileResponse를 사용하여 DAISY 파일 다운로드 제공
        return FileResponse(
            path=str(zip_file_path),
            filename=filename,
            media_type="application/zip"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DAISY 결과 다운로드 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"DAISY 결과 다운로드 중 오류가 발생했습니다: {str(e)}")

@app.get("/download-epub/{task_id}")
async def download_epub_result(task_id: str = FastAPIPath(..., description="다운로드할 EPUB3 변환 작업 ID")):
    """
    완료된 EPUB3 변환 작업의 결과를 다운로드합니다.
    """
    logger.info(f"EPUB3 결과 다운로드 요청: {task_id}")
    
    try:
        # EPUB3 파일 경로
        epub_file_path = RESULTS_DIR / f"{task_id}.epub"
        
        if not epub_file_path.exists():
            logger.error(f"EPUB3 결과 파일을 찾을 수 없음: {epub_file_path}")
            raise HTTPException(status_code=404, detail="EPUB3 변환 결과 파일을 찾을 수 없습니다.")
        
        # 파일명 설정
        if task_id in job_statuses and job_statuses[task_id].get("filename"):
            original_filename = job_statuses[task_id]["filename"]
            filename = f"{Path(original_filename).stem}.epub"
        else:
            filename = f"epub3_{task_id}.epub"
        
        # FileResponse를 사용하여 EPUB3 파일 다운로드 제공
        return FileResponse(
            path=str(epub_file_path),
            filename=filename,
            media_type="application/epub+zip"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"EPUB3 결과 다운로드 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"EPUB3 결과 다운로드 중 오류가 발생했습니다: {str(e)}")

@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """
    작업 상태를 실시간으로 수신하는 WebSocket 엔드포인트
    """
    logger.info(f"WebSocket 연결 요청: {task_id}")
    await status_listener(websocket, task_id)

@app.get("/")
async def root():
    """API 루트 경로"""
    redis_status = "연결됨"
    try:
        redis_conn = get_redis_connection()
        redis_conn.ping()
    except Exception as e:
        redis_status = f"연결 실패: {str(e)}"
    
    return {
        "message": "DOCX to DAISY/EPUB3 API에 오신 것을 환영합니다.",
        "redis_status": redis_status,
        "queue": QUEUE_NAME,
        "endpoints": {
            "daisy": {
                "convert": "/convert",
                "download": "/download/{task_id}",
                "status": "/task/{task_id}"
            },
            "epub3": {
                "convert": "/convert-epub3",
                "download": "/download-epub/{task_id}",
                "status": "/task/{task_id}"
            },
            "websocket": "/ws/task/{task_id}"
        }
    }

# 작업 상태 업데이트 이벤트 처리
def update_job_status(job_id: str, status: str, message: str = None, result: Any = None):
    """
    작업 상태를 업데이트하고 WebSocket을 통해 클라이언트에게 알립니다.
    """
    if job_id in job_statuses:
        job_statuses[job_id]["status"] = status
        
        if message:
            job_statuses[job_id]["message"] = message
            
        if result:
            job_statuses[job_id]["result"] = result
    
    # WebSocket 통지 전송
    status_data = {
        "task_id": job_id,
        "status": status
    }
    
    if message:
        status_data["message"] = message
        
    if result:
        status_data["result"] = result
    
    # asyncio.create_task를 직접 호출할 수 없으므로 이벤트를 발생시키는 방식으로 처리해야 함
    # 이 부분은 RQ의 작업 이벤트를 구독하는 별도의 이벤트 리스너에서 처리되어야 함

# 매 시간마다 오래된 결과 파일 정리 (실제 구현은 별도의 스케줄러를 사용하는 것이 좋음)
def cleanup_old_results():
    """24시간 이상 지난 결과 파일을 정리합니다."""
    import time
    current_time = time.time()
    
    # DAISY ZIP 파일 정리
    for file_path in RESULTS_DIR.glob("*.zip"):
        file_age = current_time - file_path.stat().st_mtime
        if file_age > 86400:  # 24시간 (초 단위)
            try:
                file_path.unlink()
                logger.info(f"오래된 DAISY 결과 파일 삭제: {file_path}")
            except Exception as e:
                logger.error(f"DAISY 파일 삭제 중 오류 발생: {str(e)}")
    
    # EPUB3 파일 정리
    for file_path in RESULTS_DIR.glob("*.epub"):
        file_age = current_time - file_path.stat().st_mtime
        if file_age > 86400:  # 24시간 (초 단위)
            try:
                file_path.unlink()
                logger.info(f"오래된 EPUB3 결과 파일 삭제: {file_path}")
            except Exception as e:
                logger.error(f"EPUB3 파일 삭제 중 오류 발생: {str(e)}")

@app.post("/convert-batch")
async def convert_docx_to_daisy_batch(
    files: list[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    language: str = Form("ko"),
    background_tasks: BackgroundTasks = None
):
    """
    여러 DOCX 파일을 일괄 업로드하여 DAISY 형식으로 변환합니다.
    
    - **files**: 변환할 DOCX 파일 목록
    - **metadata**: 파일별 메타데이터 (JSON 형식, 선택 사항)
        예: [{"title": "제목1", "author": "저자1", "publisher": "출판사1"}, 
             {"title": "제목2", "author": "저자2", "publisher": "출판사2"}]
    - **language**: 언어 코드 (기본값: ko)
    """
    logger.info(f"일괄 변환 요청 받음: 파일 수={len(files)}, 메타데이터={metadata}, 언어={language}")
    
    # 메타데이터 파싱
    metadata_list = []
    if metadata:
        try:
            import json
            metadata_list = json.loads(metadata)
            if not isinstance(metadata_list, list):
                raise ValueError("메타데이터는 배열 형식이어야 합니다.")
             
            # 메타데이터 개수가 파일 개수와 일치하는지 확인
            if len(metadata_list) != len(files):
                logger.warning(f"메타데이터 개수({len(metadata_list)})와 파일 개수({len(files)})가 일치하지 않습니다.")
        except Exception as e:
            logger.error(f"메타데이터 파싱 오류: {str(e)}")
            raise HTTPException(status_code=400, detail=f"메타데이터 형식이 올바르지 않습니다: {str(e)}")
    
    # 파일 수 제한 (필요시 조정)
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="한 번에 최대 10개의 파일만 처리할 수 있습니다.")
    
    # 응답 준비
    response_tasks = []
    
    for i, file in enumerate(files):
        # 파일 확장자 확인
        if not file.filename.lower().endswith('.docx'):
            logger.error(f"잘못된 파일 형식: {file.filename}")
            response_tasks.append({
                "filename": file.filename,
                "status": "error",
                "message": "DOCX 파일만 업로드 가능합니다."
            })
            continue
        
        # 고유 ID 생성
        task_id = str(uuid.uuid4())
        
        # 파일별 메타데이터 가져오기
        file_metadata = metadata_list[i] if i < len(metadata_list) else {}
        file_title = file_metadata.get("title")
        file_author = file_metadata.get("author")
        file_publisher = file_metadata.get("publisher")
        
        # 파일별 제목 생성 (접두사 + 파일명)
        if not file_title:
            file_title = Path(file.filename).stem
            
        # 임시 파일 경로 설정
        temp_docx_path = TEMP_DIR / f"{task_id}.docx"
        zip_file_path = RESULTS_DIR / f"{task_id}.zip"
        
        try:
            # 업로드된 파일 저장
            logger.info(f"임시 파일 저장 시작: {temp_docx_path}")
            with open(temp_docx_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            logger.info("임시 파일 저장 완료")
            
            # 큐에 작업 추가
            queue = get_queue()
            job = queue.enqueue(
                process_conversion_task,
                args=(
                    str(temp_docx_path),
                    str(zip_file_path),
                    file_title,
                    file_author,
                    file_publisher,
                    language
                ),
                job_id=task_id,
                timeout=3600,  # 1시간 제한
                job_timeout=3600,
                result_ttl=86400,  # 결과는 24시간 유지
                ttl=86400  # 작업은 24시간 유지
            )
            
            # 작업 상태 설정
            job_statuses[task_id] = {
                "status": "queued",
                "filename": file.filename,
                "title": file_title,
                "author": file_author,
                "publisher": file_publisher,
                "language": language
            }
            
            # 응답에 작업 정보 추가
            response_tasks.append({
                "filename": file.filename,
                "task_id": task_id,
                "status": "queued",
                "message": "변환 작업이 큐에 추가되었습니다."
            })
            
            logger.info(f"작업이 큐에 추가됨: {task_id}, 파일: {file.filename}")
            
        except Exception as e:
            logger.error(f"변환 작업 등록 중 오류 발생: {str(e)}", exc_info=True)
            # 오류 발생 시 임시 파일 정리
            if temp_docx_path.exists():
                temp_docx_path.unlink()
                
            # 오류 정보 응답에 추가
            response_tasks.append({
                "filename": file.filename,
                "status": "error",
                "message": f"변환 작업 등록 중 오류가 발생했습니다: {str(e)}"
            })
    
    return {
        "total": len(files),
        "success": sum(1 for task in response_tasks if task["status"] == "queued"),
        "error": sum(1 for task in response_tasks if task["status"] == "error"),
        "tasks": response_tasks
    }

@app.post("/convert-epub3")
async def convert_docx_to_epub3(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    publisher: Optional[str] = Form(None),
    language: str = Form("ko"),
    background_tasks: BackgroundTasks = None
):
    """
    DOCX 파일을 EPUB3 형식으로 변환하고 작업 ID를 반환합니다.
    
    - **file**: 변환할 DOCX 파일
    - **title**: 책 제목 (선택 사항)
    - **author**: 저자 (선택 사항)
    - **publisher**: 출판사 (선택 사항)
    - **language**: 언어 코드 (기본값: ko)
    """
    logger.info(f"EPUB3 변환 요청 받음: 파일명={file.filename}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}")
    
    # 파일 확장자 확인
    if not file.filename.lower().endswith('.docx'):
        logger.error(f"잘못된 파일 형식: {file.filename}")
        raise HTTPException(status_code=400, detail="DOCX 파일만 업로드 가능합니다.")
    
    # 고유 ID 생성
    task_id = str(uuid.uuid4())
    logger.info(f"EPUB3 작업 ID 생성: {task_id}")
    
    # 임시 파일 경로 설정
    temp_docx_path = TEMP_DIR / f"{task_id}.docx"
    epub_file_path = RESULTS_DIR / f"{task_id}.epub"
    
    try:
        # 업로드된 파일 저장
        logger.info(f"임시 파일 저장 시작: {temp_docx_path}")
        with open(temp_docx_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info("임시 파일 저장 완료")
        
        # 큐에 작업 추가
        queue = get_queue()
        job = queue.enqueue(
            process_epub3_conversion_task,
            args=(
                str(temp_docx_path),
                str(epub_file_path),
                title,
                author,
                publisher,
                language
            ),
            job_id=task_id,
            timeout=3600,  # 1시간 제한
            job_timeout=3600,
            result_ttl=86400,  # 결과는 24시간 유지
            ttl=86400  # 작업은 24시간 유지
        )
        
        # 작업 상태 설정
        job_statuses[task_id] = {
            "status": "queued",
            "filename": file.filename,
            "title": title,
            "author": author,
            "publisher": publisher,
            "language": language,
            "format": "epub3"
        }
        
        logger.info(f"EPUB3 작업이 큐에 추가됨: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "queued",
            "message": "EPUB3 변환 작업이 큐에 추가되었습니다. 상태 조회 API를 사용하여 작업 상태를 확인하세요."
        }
    
    except HTTPException:
        # HTTPException은 그대로 전달
        raise
    except redis.ConnectionError as e:
        logger.error(f"Redis 연결 오류로 인한 EPUB3 변환 작업 등록 실패: {str(e)}")
        # 임시 파일 정리
        if temp_docx_path.exists():
            temp_docx_path.unlink()
        raise HTTPException(status_code=503, detail=f"Redis 서버에 연결할 수 없어 EPUB3 변환 작업을 등록할 수 없습니다: {str(e)}")
    except Exception as e:
        logger.error(f"EPUB3 변환 작업 등록 중 오류 발생: {str(e)}", exc_info=True)
        # 오류 발생 시 임시 파일 정리
        if temp_docx_path.exists():
            temp_docx_path.unlink()
        raise HTTPException(status_code=500, detail=f"EPUB3 변환 작업 등록 중 오류가 발생했습니다: {str(e)}")

@app.get("/queue/status")
async def get_queue_status():
    """
    현재 큐의 상태를 반환합니다.
    """
    try:
        redis_conn = get_redis_connection()
        queue = Queue(QUEUE_NAME, connection=redis_conn)
        
        # 큐 상태 정보 수집
        queue_info = {
            "queue_name": QUEUE_NAME,
            "pending_jobs": len(queue),
            "workers": [],
            "recent_jobs": []
        }
        
        # 워커 정보 수집
        workers = Worker.all(connection=redis_conn)
        for worker in workers:
            worker_info = {
                "name": worker.name,
                "state": worker.state,
                "current_job": worker.get_current_job_id(),
                "birth_date": worker.birth_date.isoformat() if worker.birth_date else None,
                "last_heartbeat": worker.last_heartbeat.isoformat() if worker.last_heartbeat else None
            }
            queue_info["workers"].append(worker_info)
        
        # 최근 작업 정보 수집 (최근 10개)
        recent_jobs = []
        job_ids = queue.job_ids[:10]  # 최근 10개 작업 ID
        
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                job_info = {
                    "id": job_id,
                    "status": job.get_status(),
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "ended_at": job.ended_at.isoformat() if job.ended_at else None,
                    "meta": job.meta
                }
                recent_jobs.append(job_info)
            except Exception as e:
                logger.warning(f"작업 정보 조회 실패: {job_id} - {str(e)}")
        
        queue_info["recent_jobs"] = recent_jobs
        
        # 시스템 리소스 정보 추가
        import psutil
        queue_info["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent
        }
        
        return queue_info
        
    except Exception as e:
        logger.error(f"큐 상태 조회 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"큐 상태 조회 중 오류가 발생했습니다: {str(e)}")

@app.get("/queue/clear")
async def clear_queue():
    """
    큐의 모든 대기 중인 작업을 삭제합니다. (관리자용)
    """
    try:
        redis_conn = get_redis_connection()
        queue = Queue(QUEUE_NAME, connection=redis_conn)
        
        # 대기 중인 작업 수 확인
        pending_count = len(queue)
        
        # 큐 비우기
        queue.empty()
        
        return {
            "message": f"큐가 비워졌습니다. 삭제된 작업 수: {pending_count}",
            "deleted_jobs": pending_count
        }
        
    except Exception as e:
        logger.error(f"큐 비우기 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"큐 비우기 중 오류가 발생했습니다: {str(e)}")

@app.get("/queue/retry-failed")
async def retry_failed_jobs():
    """
    실패한 작업들을 재시도합니다. (관리자용)
    """
    try:
        redis_conn = get_redis_connection()
        failed_jobs = Job.fetch_many(
            Job.failed_job_registry.get_job_ids(), 
            connection=redis_conn
        )
        
        retry_count = 0
        for job in failed_jobs:
            if job:
                try:
                    job.requeue()
                    retry_count += 1
                except Exception as e:
                    logger.warning(f"작업 재시도 실패: {job.id} - {str(e)}")
        
        return {
            "message": f"실패한 작업 재시도 완료. 재시도된 작업 수: {retry_count}",
            "retried_jobs": retry_count
        }
        
    except Exception as e:
        logger.error(f"실패한 작업 재시도 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"실패한 작업 재시도 중 오류가 발생했습니다: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
"""
DOCX to DAISY 작업 처리 모듈 - 비동기 작업을 정의하고 처리합니다.
"""

import os
import tempfile
import logging
from pathlib import Path
import shutil
import uuid
import time
import json
from typing import Dict, Any, Optional

from .cli import create_daisy_book, zip_daisy_output

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 임시 파일 저장 디렉토리
TEMP_DIR = Path(tempfile.gettempdir()) / "docx_to_daisy_tasks"
TEMP_DIR.mkdir(exist_ok=True)

# Redis 작업 메타데이터 키 접두사
JOB_META_PREFIX = "docx_to_daisy:job_meta:"

def update_job_progress(job_id: str, progress: int, message: str, meta: Optional[Dict[str, Any]] = None):
    """
    작업 진행 상태를 업데이트합니다.
    
    Args:
        job_id (str): 작업 ID
        progress (int): 진행률 (0-100)
        message (str): 상태 메시지
        meta (dict, optional): 추가 메타데이터
    """
    from rq.job import Job
    from redis import Redis
    import os
    
    # 현재 작업 객체 가져오기
    try:
        redis_conn = Redis(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            db=int(os.environ.get('REDIS_DB', 0)),
            password=os.environ.get('REDIS_PASSWORD', None)
        )
        
        # 작업 메타데이터 업데이트
        job = Job.fetch(job_id, connection=redis_conn)
        job_meta = job.meta or {}
        
        # 진행 정보 업데이트
        job_meta.update({
            'progress': progress,
            'message': message,
            'updated_at': time.time()
        })
        
        # 추가 메타데이터가 있으면 업데이트
        if meta:
            job_meta.update(meta)
        
        # 메타데이터 저장
        job.meta = job_meta
        job.save_meta()
        
        # Redis에 진행 상태 별도로 저장 (웹소켓 이벤트용)
        status_key = f"{JOB_META_PREFIX}{job_id}"
        redis_conn.set(status_key, json.dumps({
            'id': job_id,
            'progress': progress,
            'message': message,
            'status': job.get_status(),
            'updated_at': time.time()
        }))
        
        # 키스페이스 이벤트 발생을 위해 키 만료 시간 설정 (24시간)
        redis_conn.expire(status_key, 86400)
        
        logger.info(f"작업 진행 상태 업데이트: {job_id} - {progress}%, {message}")
        return True
    except Exception as e:
        logger.error(f"작업 진행 상태 업데이트 실패: {str(e)}")
        return False

def process_conversion_task(file_path, output_path, title=None, author=None, publisher=None, language="ko"):
    """
    DOCX 파일을 DAISY 형식으로 변환하는 작업을 처리합니다.
    
    Args:
        file_path (str): 변환할 DOCX 파일 경로
        output_path (str): 결과 ZIP 파일 경로
        title (str, optional): 책 제목
        author (str, optional): 저자
        publisher (str, optional): 출판사
        language (str, optional): 언어 코드 (기본값: ko)
        
    Returns:
        str: 생성된 ZIP 파일 경로
    """
    # 현재 작업 ID 가져오기 (RQ는 현재 작업 컨텍스트 제공)
    from rq import get_current_job
    job = get_current_job()
    job_id = job.id if job else None
    
    logger.info(f"변환 작업 시작: {file_path}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}")
    
    try:
        if job_id:
            update_job_progress(job_id, 0, "변환 작업이 시작되었습니다.")
        
        # 고유 ID 생성
        unique_id = str(uuid.uuid4())
        logger.info(f"작업 ID: {unique_id}")
        
        # 임시 출력 디렉토리
        output_dir = TEMP_DIR / f"output_{unique_id}"
        
        # DOCX 파일 검증
        if job_id:
            update_job_progress(job_id, 10, "DOCX 파일 검증 중...")
        
        # DAISY 파일 생성
        if job_id:
            update_job_progress(job_id, 20, "DAISY 파일 생성 중...")
        
        logger.info("DAISY 파일 생성 시작")
        
        # 메타데이터 추출을 위한 임시 함수
        def extract_metadata(docx_file_path):
            from docx import Document
            try:
                document = Document(docx_file_path)
                core_props = document.core_properties
                
                extracted_title = title
                extracted_author = author
                
                # 메타데이터에서 제목 추출 시도
                if core_props.title and isinstance(core_props.title, str) and len(core_props.title.strip()) > 0:
                    extracted_title = core_props.title
                    logger.info(f"문서 메타데이터에서 제목 추출: {extracted_title}")
                
                # 메타데이터에서 저자 정보 추출 시도
                if core_props.author and isinstance(core_props.author, str) and len(core_props.author.strip()) > 0:
                    extracted_author = core_props.author
                    logger.info(f"문서 메타데이터에서 저자 추출: {extracted_author}")
                
                return extracted_title, extracted_author
            except Exception as e:
                logger.error(f"메타데이터 추출 중 오류 발생: {str(e)}")
                return title, author
        
        # 메타데이터 추출
        extracted_title, extracted_author = extract_metadata(file_path)
        
        # 추출된 메타데이터로 작업 상태 업데이트
        if job_id:
            update_job_progress(
                job_id, 
                30, 
                "메타데이터 추출 완료, DAISY 파일 생성 중...", 
                {
                    "extracted_title": extracted_title,
                    "extracted_author": extracted_author
                }
            )
        
        # DAISY 파일 생성 (추출된 메타데이터 사용)
        create_daisy_book(
            docx_file_path=file_path,
            output_dir=str(output_dir),
            book_title=extracted_title,
            book_author=extracted_author,
            book_publisher=publisher,
            book_language=language
        )
        logger.info("DAISY 파일 생성 완료")
        
        if job_id:
            update_job_progress(job_id, 80, "DAISY 파일 생성 완료, ZIP 파일 생성 중...")
        
        # ZIP 파일 생성
        logger.info("ZIP 파일 생성 시작")
        zip_daisy_output(str(output_dir), output_path)
        logger.info(f"ZIP 파일 생성 완료: {output_path}")
        
        if job_id:
            update_job_progress(job_id, 95, "ZIP 파일 생성 완료, 임시 파일 정리 중...")
        
        # 임시 파일 정리
        cleanup_temp_files(output_dir)
        
        if job_id:
            update_job_progress(job_id, 100, "변환 작업이 완료되었습니다.", {
                "output_path": output_path,
                "extracted_title": extracted_title,
                "extracted_author": extracted_author
            })
        
        return output_path
    
    except Exception as e:
        logger.error(f"변환 작업 중 오류 발생: {str(e)}", exc_info=True)
        
        # 오류 상태 업데이트
        if job_id:
            update_job_progress(job_id, -1, f"변환 작업 중 오류 발생: {str(e)}")
        
        # 임시 파일 정리
        cleanup_temp_files(output_dir)
        raise

def cleanup_temp_files(output_dir):
    """임시 파일들을 정리합니다."""
    logger.info("임시 파일 정리 시작")
    try:
        if output_dir.exists():
            shutil.rmtree(output_dir)
            logger.info(f"임시 출력 디렉토리 삭제: {output_dir}")
    except Exception as e:
        logger.error(f"임시 파일 정리 중 오류 발생: {str(e)}", exc_info=True) 
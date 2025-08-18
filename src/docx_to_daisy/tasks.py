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
import zipfile
from typing import Dict, Any, Optional

from .converter.docxTodaisy import create_daisy_book, zip_daisy_output
from .converter.docxToepub import create_epub3_book
from .converter.daisyToepub import create_epub3_from_daisy, zip_epub_output

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
    from redis.exceptions import ConnectionError, TimeoutError
    import os
    
    # 현재 작업 객체 가져오기
    try:
        redis_conn = Redis(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            db=int(os.environ.get('REDIS_DB', 0)),
            password=os.environ.get('REDIS_PASSWORD', None),
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
        
        # Redis 연결 테스트
        redis_conn.ping()
        
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
        
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Redis 연결 오류로 인한 작업 진행 상태 업데이트 실패: {str(e)}")
        return False
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
    
    # 작업 시작 시간 기록
    start_time = time.time()
    
    logger.info(f"변환 작업 시작: {file_path}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}")
    
    # 임시 출력 디렉토리 초기화
    output_dir = None
    
    try:
        stage_times: Dict[str, float] = {}
        if job_id:
            update_job_progress(job_id, 0, "변환 작업이 시작되었습니다.", {"start_time": start_time})
        
        # 고유 ID 생성
        unique_id = str(uuid.uuid4())
        logger.info(f"작업 ID: {unique_id}")
        
        # 임시 출력 디렉토리
        output_dir = TEMP_DIR / f"output_{unique_id}"
        
        # DOCX 파일 검증
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 10, f"DOCX 파일 검증 중... (경과: {elapsed_time:.1f}초)")
        
        # 파일 존재 확인
        t_validate_docx = time.time()
        if not os.path.exists(file_path):
            error_msg = f"DOCX 파일을 찾을 수 없습니다: {file_path}"
            logger.error(error_msg)
            if job_id:
                elapsed_time = time.time() - start_time
                update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
            raise FileNotFoundError(error_msg)
        stage_times["validate_docx"] = time.time() - t_validate_docx
        
        # DAISY 파일 생성
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 20, f"DAISY 파일 생성 중... (경과: {elapsed_time:.1f}초)")
        
        logger.info("DAISY 파일 생성 시작")
        t_daisy = time.time()
        daisy_timings = create_daisy_book(
            docx_file_path=file_path,
            output_dir=str(output_dir),
            book_title=title,
            book_author=author,
            book_publisher=publisher,
            book_language=language
        )
        # 내부 단계별 시간 병합
        if isinstance(daisy_timings, dict):
            stage_times.update(daisy_timings)
        stage_times["generate_daisy_total"] = time.time() - t_daisy
        logger.info("DAISY 파일 생성 완료")
        
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 80, f"DAISY 파일 생성 완료, ZIP 파일 생성 중... (경과: {elapsed_time:.1f}초)")
        
        # ZIP 파일 생성
        logger.info("ZIP 파일 생성 시작")
        t_zip = time.time()
        zip_daisy_output(str(output_dir), output_path)
        stage_times["zip_output"] = time.time() - t_zip
        logger.info(f"ZIP 파일 생성 완료: {output_path}")
        
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 95, f"ZIP 파일 생성 완료, 임시 파일 정리 중... (경과: {elapsed_time:.1f}초)")
        
        # 임시 파일 정리
        t_cleanup = time.time()
        cleanup_temp_files(output_dir)
        stage_times["cleanup"] = time.time() - t_cleanup
        
        # 총 소요 시간 계산
        total_time = time.time() - start_time
        
        if job_id:
            update_job_progress(job_id, 100, f"변환 작업이 완료되었습니다. (총 소요시간: {total_time:.1f}초)", {
                "output_path": output_path,
                "total_time": total_time,
                "elapsed_time": total_time,
                "stage_times": stage_times
            })
        
        return output_path
    
    except FileNotFoundError as e:
        error_msg = f"파일을 찾을 수 없습니다: {str(e)}"
        logger.error(error_msg)
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        raise
    except ValueError as e:
        error_msg = f"입력 데이터 오류: {str(e)}"
        logger.error(error_msg)
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        raise
    except Exception as e:
        error_msg = f"변환 작업 중 예상치 못한 오류 발생: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 오류 상태 업데이트
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        
        # 임시 파일 정리
        if output_dir and output_dir.exists():
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

def process_epub3_conversion_task(file_path, output_path, title=None, author=None, publisher=None, language="ko"):
    """
    DOCX 파일을 EPUB3 형식으로 변환하는 작업을 처리합니다.
    
    Args:
        file_path (str): 변환할 DOCX 파일 경로
        output_path (str): 결과 EPUB 파일 경로
        title (str, optional): 책 제목
        author (str, optional): 저자
        publisher (str, optional): 출판사
        language (str, optional): 언어 코드 (기본값: ko)
        
    Returns:
        str: 생성된 EPUB 파일 경로
    """
    # 현재 작업 ID 가져오기
    from rq import get_current_job
    job = get_current_job()
    job_id = job.id if job else None
    
    # 작업 시작 시간 기록
    start_time = time.time()
    
    logger.info(f"EPUB3 변환 작업 시작: {file_path}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}")
    
    # 임시 출력 디렉토리 초기화
    output_dir = None
    
    try:
        if job_id:
            update_job_progress(job_id, 0, "EPUB3 변환 작업이 시작되었습니다.", {"start_time": start_time})
        
        # 고유 ID 생성
        unique_id = str(uuid.uuid4())
        logger.info(f"작업 ID: {unique_id}")
        
        # 임시 출력 디렉토리
        output_dir = TEMP_DIR / f"epub_output_{unique_id}"
        
        # DOCX 파일 검증
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 10, f"DOCX 파일 검증 중... (경과: {elapsed_time:.1f}초)")
        
        # 파일 존재 확인
        if not os.path.exists(file_path):
            error_msg = f"DOCX 파일을 찾을 수 없습니다: {file_path}"
            logger.error(error_msg)
            if job_id:
                elapsed_time = time.time() - start_time
                update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
            raise FileNotFoundError(error_msg)
        
        # EPUB3 파일 생성
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 20, f"EPUB3 파일 생성 중... (경과: {elapsed_time:.1f}초)")
        
        logger.info("EPUB3 파일 생성 시작")
        create_epub3_book(
            docx_file_path=file_path,
            output_path=output_path,
            book_title=title,
            book_author=author,
            book_publisher=publisher,
            book_language=language
        )
        logger.info("EPUB3 파일 생성 완료")
        
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 95, f"EPUB3 파일 생성 완료, 임시 파일 정리 중... (경과: {elapsed_time:.1f}초)")
        
        # 임시 파일 정리
        if output_dir and output_dir.exists():
            cleanup_temp_files(output_dir)
        
        # 총 소요 시간 계산
        total_time = time.time() - start_time
        
        if job_id:
            update_job_progress(job_id, 100, f"EPUB3 변환 작업이 완료되었습니다. (총 소요시간: {total_time:.1f}초)", {
                "output_path": output_path,
                "total_time": total_time,
                "elapsed_time": total_time
            })
        
        return output_path
    
    except FileNotFoundError as e:
        error_msg = f"파일을 찾을 수 없습니다: {str(e)}"
        logger.error(error_msg)
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        raise
    except ValueError as e:
        error_msg = f"입력 데이터 오류: {str(e)}"
        logger.error(error_msg)
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        raise
    except Exception as e:
        error_msg = f"EPUB3 변환 작업 중 예상치 못한 오류 발생: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 오류 상태 업데이트
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        
        # 임시 파일 정리
        if output_dir and output_dir.exists():
            cleanup_temp_files(output_dir)
        
        raise


def process_daisy_to_epub_task(zip_file_path, output_path, title=None, author=None, publisher=None, language="ko"):
    """
    DAISY ZIP 파일을 EPUB3 형식으로 변환하는 작업을 처리합니다.
    
    Args:
        zip_file_path (str): 변환할 DAISY ZIP 파일 경로
        output_path (str): 결과 EPUB 파일 경로
        title (str, optional): 책 제목
        author (str, optional): 저자
        publisher (str, optional): 출판사
        language (str, optional): 언어 코드 (기본값: ko)
        
    Returns:
        str: 생성된 EPUB 파일 경로
    """
    # 현재 작업 ID 가져오기
    from rq import get_current_job
    job = get_current_job()
    job_id = job.id if job else None
    
    # 작업 시작 시간 기록
    start_time = time.time()
    
    logger.info(f"DAISY to EPUB3 변환 작업 시작: {zip_file_path}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}")
    
    # 임시 출력 디렉토리 초기화
    output_dir = None
    
    try:
        if job_id:
            update_job_progress(job_id, 0, "DAISY to EPUB3 변환 작업이 시작되었습니다.", {"start_time": start_time})
        
        # 고유 ID 생성
        unique_id = str(uuid.uuid4())
        logger.info(f"작업 ID: {unique_id}")
        
        # 임시 출력 디렉토리
        output_dir = TEMP_DIR / f"daisy_to_epub_output_{unique_id}"
        
        # DAISY ZIP 파일 검증
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 10, f"DAISY ZIP 파일 검증 중... (경과: {elapsed_time:.1f}초)")
        
        # 파일 존재 확인
        if not os.path.exists(zip_file_path):
            error_msg = f"DAISY ZIP 파일을 찾을 수 없습니다: {zip_file_path}"
            logger.error(error_msg)
            if job_id:
                elapsed_time = time.time() - start_time
                update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
            raise FileNotFoundError(error_msg)
        
        # EPUB3 파일 생성
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 20, f"DAISY to EPUB3 변환 중... (경과: {elapsed_time:.1f}초)")
        
        logger.info("DAISY to EPUB3 변환 시작")
        
        # ZIP 파일을 임시 디렉토리에 압축 해제
        temp_daisy_dir = TEMP_DIR / f"daisy_temp_{unique_id}"
        temp_daisy_dir.mkdir(exist_ok=True)
        
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_daisy_dir)
        
        # EPUB 출력 디렉토리 생성
        temp_epub_dir = TEMP_DIR / f"epub_temp_{unique_id}"
        temp_epub_dir.mkdir(exist_ok=True)
        
        # DAISY를 EPUB3로 변환
        epub_file_path = create_epub3_from_daisy(
            daisy_dir=str(temp_daisy_dir),
            output_dir=str(temp_epub_dir),
            book_title=title,
            book_author=author,
            book_publisher=publisher,
            book_language=language
        )
        
        # 생성된 EPUB 파일을 최종 출력 경로로 복사
        if epub_file_path and os.path.exists(epub_file_path):
            shutil.copy2(epub_file_path, output_path)
        else:
            # 디렉토리에서 EPUB 파일 찾기
            epub_files = list(temp_epub_dir.glob("*.epub"))
            if epub_files:
                shutil.copy2(epub_files[0], output_path)
            else:
                raise RuntimeError("EPUB 파일이 생성되지 않았습니다.")
        
        # 임시 DAISY 및 EPUB 디렉토리 정리
        if temp_daisy_dir.exists():
            shutil.rmtree(temp_daisy_dir)
        if temp_epub_dir.exists():
            shutil.rmtree(temp_epub_dir)
        
        logger.info("DAISY to EPUB3 변환 완료")
        
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, 95, f"DAISY to EPUB3 변환 완료, 임시 파일 정리 중... (경과: {elapsed_time:.1f}초)")
        
        # 임시 파일 정리
        if output_dir and output_dir.exists():
            cleanup_temp_files(output_dir)
        
        # 총 소요 시간 계산
        total_time = time.time() - start_time
        
        if job_id:
            update_job_progress(job_id, 100, f"DAISY to EPUB3 변환 작업이 완료되었습니다. (총 소요시간: {total_time:.1f}초)", {
                "output_path": output_path,
                "total_time": total_time,
                "elapsed_time": total_time
            })
        
        return output_path
    
    except FileNotFoundError as e:
        error_msg = f"파일을 찾을 수 없습니다: {str(e)}"
        logger.error(error_msg)
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        raise


def process_docx_to_daisy_and_epub_task(
    file_path: str,
    daisy_zip_output_path: str,
    epub_output_path: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    publisher: Optional[str] = None,
    language: str = "ko",
):
    """
    DOCX 파일을 DAISY로 변환한 뒤, 해당 결과를 사용해 EPUB3까지 생성하는 파이프라인 작업을 처리합니다.

    Args:
        file_path (str): 입력 DOCX 파일 경로
        daisy_zip_output_path (str): 산출 DAISY ZIP 파일 경로
        epub_output_path (str): 산출 EPUB3 파일 경로
        title (str, optional): 책 제목
        author (str, optional): 저자
        publisher (str, optional): 출판사
        language (str, optional): 언어 코드 (기본값: ko)

    Returns:
        dict: 산출물 경로 정보
    """
    from rq import get_current_job

    job = get_current_job()
    job_id = job.id if job else None

    start_time = time.time()
    logger.info(
        f"DOCX→DAISY→EPUB3 파이프라인 시작: {file_path}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}"
    )

    unique_id = str(uuid.uuid4())
    daisy_output_dir = TEMP_DIR / f"pipeline_daisy_{unique_id}"
    epub_temp_dir = TEMP_DIR / f"pipeline_epub_{unique_id}"

    try:
        if job_id:
            update_job_progress(job_id, 0, "파이프라인 작업이 시작되었습니다.", {"start_time": start_time, "stage": "start"})

        # 입력 DOCX 검증
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, 5, f"DOCX 파일 검증 중... (경과: {elapsed:.1f}초)", {"stage": "validate_docx"})

        if not os.path.exists(file_path):
            msg = f"DOCX 파일을 찾을 수 없습니다: {file_path}"
            logger.error(msg)
            if job_id:
                elapsed = time.time() - start_time
                update_job_progress(job_id, -1, msg, {"elapsed_time": elapsed})
            raise FileNotFoundError(msg)

        # DAISY 생성
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, 15, f"DAISY 생성 준비 중... (경과: {elapsed:.1f}초)", {"stage": "daisy_prepare"})

        daisy_output_dir.mkdir(exist_ok=True)
        logger.info("DAISY 파일 생성 시작")
        create_daisy_book(
            docx_file_path=file_path,
            output_dir=str(daisy_output_dir),
            book_title=title,
            book_author=author,
            book_publisher=publisher,
            book_language=language,
        )
        logger.info("DAISY 파일 생성 완료")

        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, 50, f"DAISY 생성 완료, ZIP 생성 중... (경과: {elapsed:.1f}초)", {"stage": "daisy_zip"})

        # DAISY ZIP 생성
        zip_daisy_output(str(daisy_output_dir), daisy_zip_output_path)
        logger.info(f"DAISY ZIP 생성 완료: {daisy_zip_output_path}")

        # EPUB3 변환
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, 70, f"DAISY→EPUB3 변환 중... (경과: {elapsed:.1f}초)", {"stage": "daisy_to_epub"})

        epub_temp_dir.mkdir(exist_ok=True)
        epub_generated_path = create_epub3_from_daisy(
            daisy_dir=str(daisy_output_dir),
            output_dir=str(epub_temp_dir),
            book_title=title,
            book_author=author,
            book_publisher=publisher,
            book_language=language,
        )

        # 결과 EPUB 파일 확정 및 복사
        final_epub_path = epub_generated_path if epub_generated_path and os.path.exists(epub_generated_path) else None
        if not final_epub_path:
            candidates = list(epub_temp_dir.glob("*.epub"))
            if candidates:
                final_epub_path = str(candidates[0])

        if not final_epub_path or not os.path.exists(final_epub_path):
            raise RuntimeError("EPUB3 파일이 생성되지 않았습니다.")

        shutil.copy2(final_epub_path, epub_output_path)
        logger.info(f"EPUB3 파일 확정: {epub_output_path}")

        # 정리 단계
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, 95, f"임시 파일 정리 중... (경과: {elapsed:.1f}초)", {"stage": "cleanup"})

        if daisy_output_dir.exists():
            cleanup_temp_files(daisy_output_dir)
        if epub_temp_dir.exists():
            cleanup_temp_files(epub_temp_dir)

        total_time = time.time() - start_time
        if job_id:
            update_job_progress(
                job_id,
                100,
                f"파이프라인 작업이 완료되었습니다. (총 소요시간: {total_time:.1f}초)",
                {
                    "output_paths": {
                        "daisy_zip": daisy_zip_output_path,
                        "epub3": epub_output_path,
                    },
                    "total_time": total_time,
                    "elapsed_time": total_time,
                    "stage": "finished",
                },
            )

        return {
            "daisy_zip": daisy_zip_output_path,
            "epub3": epub_output_path,
        }

    except FileNotFoundError as e:
        msg = f"파일을 찾을 수 없습니다: {str(e)}"
        logger.error(msg)
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, -1, msg, {"elapsed_time": elapsed})
        raise
    except ValueError as e:
        msg = f"입력 데이터 오류: {str(e)}"
        logger.error(msg)
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, -1, msg, {"elapsed_time": elapsed})
        raise
    except Exception as e:
        msg = f"파이프라인 작업 중 오류 발생: {str(e)}"
        logger.error(msg, exc_info=True)
        if job_id:
            elapsed = time.time() - start_time
            update_job_progress(job_id, -1, msg, {"elapsed_time": elapsed})
        # 임시 디렉토리 정리
        try:
            if daisy_output_dir.exists():
                cleanup_temp_files(daisy_output_dir)
            if epub_temp_dir.exists():
                cleanup_temp_files(epub_temp_dir)
        except Exception:
            pass
        raise
    except ValueError as e:
        error_msg = f"입력 데이터 오류: {str(e)}"
        logger.error(error_msg)
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        raise
    except Exception as e:
        error_msg = f"DAISY to EPUB3 변환 작업 중 예상치 못한 오류 발생: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 오류 상태 업데이트
        if job_id:
            elapsed_time = time.time() - start_time
            update_job_progress(job_id, -1, error_msg, {"elapsed_time": elapsed_time})
        
        # 임시 파일 정리
        if output_dir and output_dir.exists():
            cleanup_temp_files(output_dir)
        
        raise 
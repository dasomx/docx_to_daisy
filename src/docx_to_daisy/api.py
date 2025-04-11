import os
import tempfile
import uuid
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import shutil
from pathlib import Path
from typing import Optional

from .cli import create_daisy_book, zip_daisy_output

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DOCX to DAISY API",
    description="DOCX 파일을 DAISY 형식으로 변환하는 API",
    version="0.1.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용 (프로덕션에서는 특정 출처만 허용하는 것이 좋습니다)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 임시 파일 저장 디렉토리
TEMP_DIR = Path(tempfile.gettempdir()) / "docx_to_daisy_api"
TEMP_DIR.mkdir(exist_ok=True)

@app.post("/convert")
async def convert_docx_to_daisy(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    publisher: Optional[str] = Form(None),
    language: str = Form("ko"),
    background_tasks: BackgroundTasks = None
):
    """
    DOCX 파일을 DAISY 형식으로 변환하고 ZIP 파일을 반환합니다.
    
    - **file**: 변환할 DOCX 파일
    - **title**: 책 제목 (선택 사항)
    - **author**: 저자 (선택 사항)
    - **publisher**: 출판사 (선택 사항)
    - **language**: 언어 코드 (기본값: ko)
    """
    logger.info(f"변환 요청 받음: 파일명={file.filename}, 제목={title}, 저자={author}, 출판사={publisher}, 언어={language}")
    
    # 파일 확장자 확인
    if not file.filename.lower().endswith('.docx'):
        logger.error(f"잘못된 파일 형식: {file.filename}")
        raise HTTPException(status_code=400, detail="DOCX 파일만 업로드 가능합니다.")
    
    # 고유 ID 생성
    unique_id = str(uuid.uuid4())
    logger.info(f"고유 ID 생성: {unique_id}")
    
    # 임시 파일 경로 설정
    temp_docx_path = TEMP_DIR / f"{unique_id}.docx"
    output_dir = TEMP_DIR / f"output_{unique_id}"
    zip_file_path = TEMP_DIR / f"{unique_id}.zip"
    
    try:
        # 업로드된 파일 저장
        logger.info(f"임시 파일 저장 시작: {temp_docx_path}")
        with open(temp_docx_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info("임시 파일 저장 완료")
        
        # DAISY 파일 생성
        logger.info("DAISY 파일 생성 시작")
        create_daisy_book(
            docx_file_path=str(temp_docx_path),
            output_dir=str(output_dir),
            book_title=title,
            book_author=author,
            book_publisher=publisher,
            book_language=language
        )
        logger.info("DAISY 파일 생성 완료")
        
        # ZIP 파일 생성
        logger.info("ZIP 파일 생성 시작")
        zip_daisy_output(str(output_dir), str(zip_file_path))
        logger.info("ZIP 파일 생성 완료")
        
        # 임시 파일 정리 작업 등록
        background_tasks.add_task(cleanup_temp_files, temp_docx_path, output_dir, zip_file_path)
        logger.info("임시 파일 정리 작업 등록됨")
        
        # ZIP 파일 반환
        logger.info(f"ZIP 파일 반환: {zip_file_path}")
        return FileResponse(
            path=str(zip_file_path),
            filename=f"{Path(file.filename).stem}_daisy.zip",
            media_type="application/zip"
        )
    
    except Exception as e:
        logger.error(f"변환 중 오류 발생: {str(e)}", exc_info=True)
        # 오류 발생 시 임시 파일 정리
        cleanup_temp_files(temp_docx_path, output_dir, zip_file_path)
        raise HTTPException(status_code=500, detail=f"변환 중 오류가 발생했습니다: {str(e)}")

def cleanup_temp_files(docx_path, output_dir, zip_path):
    """임시 파일들을 정리합니다."""
    logger.info("임시 파일 정리 시작")
    try:
        if docx_path.exists():
            docx_path.unlink()
            logger.info(f"임시 DOCX 파일 삭제: {docx_path}")
        if output_dir.exists():
            shutil.rmtree(output_dir)
            logger.info(f"임시 출력 디렉토리 삭제: {output_dir}")
        if zip_path.exists():
            zip_path.unlink()
            logger.info(f"임시 ZIP 파일 삭제: {zip_path}")
    except Exception as e:
        logger.error(f"임시 파일 정리 중 오류 발생: {str(e)}", exc_info=True)
    logger.info("임시 파일 정리 완료")

@app.get("/")
async def root():
    """API 루트 경로"""
    return {"message": "DOCX to DAISY API에 오신 것을 환영합니다."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
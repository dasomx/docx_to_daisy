#!/usr/bin/env python
"""
DOCX to DAISY API 실행 스크립트
"""

import uvicorn
from docx_to_daisy.api import app

def main():
    """API 서버를 실행합니다."""
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main() 
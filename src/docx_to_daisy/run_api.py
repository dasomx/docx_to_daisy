#!/usr/bin/env python
"""
DOCX to DAISY API 실행 스크립트
"""

import os
import argparse
import uvicorn
from docx_to_daisy.api import app

def setup_env_vars(redis_host=None, redis_port=None, redis_db=None, redis_password=None, queue_name=None):
    """환경 변수 설정"""
    if redis_host:
        os.environ['REDIS_HOST'] = redis_host
    if redis_port:
        os.environ['REDIS_PORT'] = str(redis_port)
    if redis_db is not None:
        os.environ['REDIS_DB'] = str(redis_db)
    if redis_password:
        os.environ['REDIS_PASSWORD'] = redis_password
    if queue_name:
        os.environ['QUEUE_NAME'] = queue_name

def main():
    """API 서버를 실행합니다."""
    parser = argparse.ArgumentParser(description='DOCX to DAISY API 서버')
    
    # 서버 설정
    parser.add_argument('--host', type=str, default="0.0.0.0", help='API 서버 호스트')
    parser.add_argument('--port', type=int, default=8000, help='API 서버 포트')
    
    # Redis 설정
    parser.add_argument('--redis-host', type=str, help='Redis 서버 호스트')
    parser.add_argument('--redis-port', type=int, help='Redis 서버 포트')
    parser.add_argument('--redis-db', type=int, help='Redis 데이터베이스 번호')
    parser.add_argument('--redis-password', type=str, help='Redis 비밀번호')
    parser.add_argument('--queue-name', type=str, help='Redis 큐 이름')
    
    args = parser.parse_args()
    
    # 환경 변수 설정
    setup_env_vars(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_db=args.redis_db,
        redis_password=args.redis_password,
        queue_name=args.queue_name
    )
    
    # API 서버 실행
    print(f"DOCX to DAISY API 서버 시작: {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main() 
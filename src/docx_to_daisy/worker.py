#!/usr/bin/env python
"""
DOCX to DAISY 워커 스크립트 - Redis 큐에서 작업을 처리합니다.
"""

import os
import logging
import argparse
import redis
from rq import Worker, Queue, Connection

# 로깅 설정
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Redis 연결 정보
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
QUEUE_NAME = os.environ.get('QUEUE_NAME', 'daisy_queue')

def get_redis_connection():
    """Redis 연결을 생성하고 반환합니다."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD
    )

def start_worker(num_workers=1):
    """RQ 워커를 시작합니다."""
    redis_conn = get_redis_connection()
    
    try:
        with Connection(redis_conn):
            queues = [Queue(QUEUE_NAME)]
            logger.info(f"{num_workers}개의 워커를 시작합니다. 큐: {QUEUE_NAME}")
            
            w = Worker(queues)
            w.work(with_scheduler=True)
    except Exception as e:
        logger.error(f"워커 실행 중 오류 발생: {str(e)}")
        raise

def main():
    """워커 스크립트 메인 함수"""
    parser = argparse.ArgumentParser(description='DOCX to DAISY 워커')
    parser.add_argument('--workers', type=int, default=1, help='시작할 워커 수')
    args = parser.parse_args()
    
    logger.info(f"DOCX to DAISY 워커 시작 - Redis: {REDIS_HOST}:{REDIS_PORT}, 큐: {QUEUE_NAME}")
    start_worker(args.workers)

if __name__ == "__main__":
    main() 
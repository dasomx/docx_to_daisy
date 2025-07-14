#!/usr/bin/env python
"""
DOCX to DAISY 워커 스크립트 - Redis 큐에서 작업을 처리합니다.
"""

import os
import logging
import argparse
import redis
import multiprocessing
import uuid
import time
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
        password=REDIS_PASSWORD,
        socket_connect_timeout=30,
        socket_timeout=60,
        retry_on_timeout=True,
        max_connections=5,
        decode_responses=False
    )

def start_worker(num_workers=1, worker_name=None):
    """RQ 워커를 시작합니다."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            redis_conn = get_redis_connection()
            
            # Redis 연결 테스트
            redis_conn.ping()
            logger.info(f"Redis 연결 성공: {REDIS_HOST}:{REDIS_PORT}")
            
            with Connection(redis_conn):
                queues = [Queue(QUEUE_NAME)]
                
                # 워커 이름 설정 (고유한 이름 생성)
                if worker_name is None:
                    # 컨테이너 ID, 프로세스 ID, 타임스탬프를 조합하여 고유한 이름 생성
                    container_id = os.environ.get('HOSTNAME', 'unknown')
                    process_id = os.getpid()
                    timestamp = int(time.time())
                    unique_suffix = str(uuid.uuid4())[:8]
                    worker_name = f"daisy_worker_{container_id}_{process_id}_{timestamp}_{unique_suffix}"
                
                logger.info(f"워커 시작: {worker_name}, 큐: {QUEUE_NAME}")
                
                # 워커 설정 (최소한의 파라미터만 사용)
                w = Worker(
                    queues,
                    name=worker_name
                )
                
                # 워커 시작 (타임아웃 설정)
                w.work(logging_level=logging.INFO, with_scheduler=False)
                
        except (redis.ConnectionError, redis.TimeoutError) as e:
            retry_count += 1
            logger.error(f"Redis 연결 오류 (시도 {retry_count}/{max_retries}): {str(e)}")
            if retry_count < max_retries:
                time.sleep(5)  # 5초 대기 후 재시도
            else:
                logger.error(f"Redis 연결 실패. 최대 재시도 횟수 초과.")
                raise
        except Exception as e:
            logger.error(f"워커 실행 중 오류 발생: {str(e)}")
            raise

def start_worker_pool(num_workers=None):
    """여러 워커를 병렬로 시작합니다."""
    if num_workers is None:
        # CPU 코어 수에 기반하여 워커 수 결정 (최대 4개로 제한)
        num_workers = min(multiprocessing.cpu_count(), 4)
    
    logger.info(f"워커 풀 시작: {num_workers}개의 워커")
    
    # 각 워커를 별도 프로세스로 시작
    processes = []
    for i in range(num_workers):
        # 고유한 워커 이름 생성
        container_id = os.environ.get('HOSTNAME', 'unknown')
        timestamp = int(time.time())
        unique_suffix = str(uuid.uuid4())[:8]
        worker_name = f"daisy_worker_{container_id}_{i+1}_{timestamp}_{unique_suffix}"
        
        p = multiprocessing.Process(
            target=start_worker,
            args=(1, worker_name),
            name=worker_name
        )
        p.start()
        processes.append(p)
        logger.info(f"워커 프로세스 시작: {worker_name} (PID: {p.pid})")
        
        # 프로세스 간 간격을 두어 Redis 연결 부하 분산
        time.sleep(2)
    
    # 모든 프로세스가 종료될 때까지 대기
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        logger.info("워커 풀 종료 요청됨")
        for p in processes:
            p.terminate()
            p.join()
        logger.info("워커 풀 종료 완료")

def main():
    """워커 스크립트 메인 함수"""
    parser = argparse.ArgumentParser(description='DOCX to DAISY 워커')
    parser.add_argument('--workers', type=int, default=1, help='시작할 워커 수')
    parser.add_argument('--pool', action='store_true', help='워커 풀 모드로 실행')
    parser.add_argument('--auto-scale', action='store_true', help='CPU 코어 수에 따라 자동 스케일링')
    args = parser.parse_args()
    
    logger.info(f"DOCX to DAISY 워커 시작 - Redis: {REDIS_HOST}:{REDIS_PORT}, 큐: {QUEUE_NAME}")
    
    if args.pool or args.auto_scale:
        # 워커 풀 모드
        worker_count = args.workers if not args.auto_scale else None
        start_worker_pool(worker_count)
    else:
        # 단일 워커 모드
        start_worker(args.workers)

if __name__ == "__main__":
    main() 
"""
DOCX to DAISY 이벤트 처리 모듈 - 작업 상태 변경을 감지하고 웹소켓 통지를 발송합니다.
"""

import os
import time
import logging
import threading
import json
import asyncio
import redis
from rq import Worker, Queue, Connection
from rq.job import Job

from .tasks import JOB_META_PREFIX
from .websocket import manager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis 연결 정보
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
QUEUE_NAME = os.environ.get('QUEUE_NAME', 'daisy_queue')

class JobEventListener(threading.Thread):
    """Redis Pub/Sub을 사용하여 작업 이벤트를 수신하고 처리하는 클래스"""
    
    def __init__(self, redis_conn=None, event_loop=None):
        """
        JobEventListener 초기화
        
        Args:
            redis_conn: Redis 연결 객체 (기본값: None, 새로 생성)
            event_loop: asyncio 이벤트 루프 (기본값: None, 새로 생성)
        """
        super().__init__()
        self.daemon = True
        
        # Redis 연결
        if redis_conn is None:
            self.redis_conn = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD
            )
        else:
            self.redis_conn = redis_conn
        
        # Pub/Sub 객체
        self.pubsub = self.redis_conn.pubsub()
        
        # 이벤트 루프
        self.event_loop = event_loop or asyncio.new_event_loop()
        
        # 종료 플래그
        self.should_stop = False
    
    def run(self):
        """이벤트 리스너 스레드 실행"""
        # 이벤트 루프 설정
        asyncio.set_event_loop(self.event_loop)
        
        # 구독 패턴 설정
        # 1. 작업 상태 변경 이벤트 (rq:job:*)
        # 2. 작업 진행 상태 이벤트 (docx_to_daisy:job_meta:*)
        self.pubsub.psubscribe('__keyspace@0__:rq:job:*')
        self.pubsub.psubscribe(f'__keyspace@0__:{JOB_META_PREFIX}*')
        
        logger.info("작업 이벤트 리스너 시작됨")
        
        # 메시지 수신 루프
        for message in self.pubsub.listen():
            if self.should_stop:
                break
                
            try:
                # 키스페이스 이벤트 처리
                if message['type'] == 'pmessage':
                    channel = message['channel'].decode('utf-8')
                    event = message['data'].decode('utf-8')
                    
                    # 작업 상태 변경 이벤트 처리 (rq:job:*)
                    if 'rq:job:' in channel and event == 'set':
                        job_id = channel.split(':')[-1]
                        self._handle_job_status_event(job_id)
                    
                    # 작업 진행 상태 이벤트 처리 (docx_to_daisy:job_meta:*)
                    elif JOB_META_PREFIX in channel and event == 'set':
                        job_id = channel.split(':')[-1]
                        self._handle_job_progress_event(job_id)
            except Exception as e:
                logger.error(f"이벤트 처리 중 오류 발생: {str(e)}", exc_info=True)
    
    def _handle_job_status_event(self, job_id):
        """작업 상태 변경 이벤트 처리"""
        try:
            # 작업 정보 조회
            job = Job.fetch(job_id, connection=self.redis_conn)
            status = job.get_status()
            
            # 작업 상태에 따른 메시지 생성
            message = None
            if status == 'finished':
                message = "변환 작업이 완료되었습니다."
            elif status == 'failed':
                message = "변환 작업이 실패했습니다."
            elif status == 'started':
                message = "변환 작업이 진행 중입니다."
            else:
                message = "변환 작업이 대기 중입니다."
            
            # WebSocket 통지 전송
            status_data = {
                "task_id": job_id,
                "status": status,
                "message": message
            }
            
            # 작업 메타데이터 추가
            job_meta = job.meta
            if job_meta:
                progress = job_meta.get('progress', 0)
                custom_message = job_meta.get('message', '')
                updated_at = job_meta.get('updated_at')
                
                status_data.update({
                    "progress": progress,
                    "message": custom_message or message,
                    "updated_at": updated_at
                })
            
            # 비동기 함수를 이벤트 루프에서 실행
            asyncio.run_coroutine_threadsafe(
                manager.send_status(job_id, status_data), 
                self.event_loop
            )
            logger.info(f"작업 상태 변경: {job_id} -> {status}")
        except Exception as e:
            logger.error(f"작업 상태 이벤트 처리 중 오류 발생: {str(e)}", exc_info=True)
    
    def _handle_job_progress_event(self, job_id):
        """작업 진행 상태 이벤트 처리"""
        try:
            # 진행 상태 정보 조회
            status_key = f"{JOB_META_PREFIX}{job_id}"
            status_data_str = self.redis_conn.get(status_key)
            
            if status_data_str:
                status_data = json.loads(status_data_str)
                
                # 비동기 함수를 이벤트 루프에서 실행
                asyncio.run_coroutine_threadsafe(
                    manager.send_status(job_id, status_data), 
                    self.event_loop
                )
                logger.info(f"작업 진행 상태 변경: {job_id} -> {status_data.get('progress')}%, {status_data.get('message')}")
        except Exception as e:
            logger.error(f"작업 진행 상태 이벤트 처리 중 오류 발생: {str(e)}", exc_info=True)
    
    def stop(self):
        """이벤트 리스너 종료"""
        self.should_stop = True
        self.pubsub.unsubscribe()
        logger.info("작업 이벤트 리스너 종료됨")

# 글로벌 이벤트 리스너 인스턴스
_event_listener = None

def start_event_listener():
    """이벤트 리스너를 시작합니다."""
    global _event_listener
    
    if _event_listener is None:
        _event_listener = JobEventListener()
        _event_listener.start()
        logger.info("작업 이벤트 리스너가 시작되었습니다.")

def stop_event_listener():
    """이벤트 리스너를 종료합니다."""
    global _event_listener
    
    if _event_listener is not None:
        _event_listener.stop()
        _event_listener = None
        logger.info("작업 이벤트 리스너가 종료되었습니다.") 
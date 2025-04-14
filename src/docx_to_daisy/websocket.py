"""
DOCX to DAISY 웹소켓 모듈 - 작업 상태를 클라이언트에게 실시간으로 전송합니다.
"""

import json
import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class ConnectionManager:
    """WebSocket 연결 관리 클래스"""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, task_id: str):
        """클라이언트 웹소켓 연결 추가"""
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)
        logger.info(f"WebSocket 연결 추가: 작업 ID {task_id}")
    
    def disconnect(self, websocket: WebSocket, task_id: str):
        """클라이언트 웹소켓 연결 제거"""
        if task_id in self.active_connections:
            if websocket in self.active_connections[task_id]:
                self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        logger.info(f"WebSocket 연결 종료: 작업 ID {task_id}")
    
    async def send_status(self, task_id: str, data: Any):
        """특정 작업 ID에 대한 상태 정보 전송"""
        if task_id in self.active_connections:
            for connection in self.active_connections[task_id]:
                try:
                    await connection.send_text(json.dumps(data))
                except Exception as e:
                    logger.error(f"WebSocket 메시지 전송 중 오류: {str(e)}")
    
    async def broadcast(self, message: str):
        """모든 연결된 클라이언트에게 메시지 전송"""
        for task_id in self.active_connections:
            for connection in self.active_connections[task_id]:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    logger.error(f"WebSocket 브로드캐스트 중 오류: {str(e)}")

# 연결 관리자 인스턴스 생성
manager = ConnectionManager()

async def status_listener(websocket: WebSocket, task_id: str):
    """
    특정 작업 ID에 대한 WebSocket 연결을 처리합니다.
    
    Args:
        websocket (WebSocket): 클라이언트 WebSocket 연결
        task_id (str): 작업 ID
    """
    await manager.connect(websocket, task_id)
    try:
        # 초기 상태 전송
        await manager.send_status(task_id, {
            "status": "connected",
            "task_id": task_id,
            "message": "실시간 작업 상태 연결 완료"
        })
        
        # 클라이언트가 연결을 유지하는 동안 대기
        while True:
            # 클라이언트로부터 메시지를 수신 (ping/pong 메커니즘)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception as e:
        logger.error(f"WebSocket 처리 중 오류: {str(e)}")
        manager.disconnect(websocket, task_id) 
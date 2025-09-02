import os
import redis


# Redis 환경 변수
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
REDIS_MAX_CONNECTIONS = int(os.environ.get('REDIS_MAX_CONNECTIONS', 20))


# 프로세스 단위 전역 ConnectionPool (thread-safe)
_connection_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    max_connections=REDIS_MAX_CONNECTIONS,
    socket_connect_timeout=10,
    socket_timeout=10,
    retry_on_timeout=True,
    health_check_interval=30,
    decode_responses=False,
)


def get_connection_pool() -> redis.ConnectionPool:
    return _connection_pool


def get_redis_connection() -> redis.Redis:
    """공유 ConnectionPool을 사용하는 Redis 클라이언트 반환"""
    return redis.Redis(connection_pool=_connection_pool)


# 블로킹 대기(예: BLPOP, Pub/Sub 전용)용 ConnectionPool
_blocking_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    max_connections=REDIS_MAX_CONNECTIONS,
    socket_connect_timeout=10,
    socket_timeout=None,  # 블로킹 작업에선 읽기 타임아웃 없음
    retry_on_timeout=True,
    health_check_interval=30,
    decode_responses=False,
)


def get_blocking_redis_connection() -> redis.Redis:
    """BLPOP / PubSub 등 장시간 블로킹 대기를 위한 Redis 클라이언트 반환"""
    return redis.Redis(
        connection_pool=_blocking_pool,
        socket_keepalive=True,
    )



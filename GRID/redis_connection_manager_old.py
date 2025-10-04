import os
import time
import zlib
from redis import Redis, RedisError
import redis.asyncio as aioredis
from rq import Queue
from rq.job import Job as RQJob
import asyncio
from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

class RedisConnectionManager:
    _instance = None
    _pool = None
    _async_pool = None
    _queue = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisConnectionManager, cls).__new__(cls)
            cls._instance.setup_redis()
        return cls._instance

    def setup_redis(self):
        self.redis_host = settings.REDIS_HOST
        self.redis_port = settings.REDIS_PORT
        self.redis_db = settings.REDIS_DB
        self.redis_password = REDIS_PASSWORD
        self.max_connections = 200
        self.redis_conn = None
        self.redis_async = None
        self.task_queue = None

    def get_connection(self):
        if REDIS_PASSWORD:
            self._pool = Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=False,
                max_connections=self.max_connections
            )
        else:
            if self._pool is None:
                self._pool = Redis(
                    host=self.redis_host,
                    port=self.redis_port,
                    db=self.redis_db,
                    password=self.redis_password,
                decode_responses=False,
                max_connections=self.max_connections
            )
        return self._pool

    async def get_connection_async(self):
        if self._async_pool is None:
            if REDIS_PASSWORD:
                self._async_pool = aioredis.ConnectionPool.from_url(    
                    f'redis://{self.redis_host}:{self.redis_port}/{self.redis_db}',
                    password=self.redis_password,
                    decode_responses=False,
                    max_connections=self.max_connections
                )
            else:
                self._async_pool = aioredis.ConnectionPool.from_url(
                    f'redis://{self.redis_host}:{self.redis_port}/{self.redis_db}',
                    decode_responses=False,
                    max_connections=self.max_connections
                )
        return aioredis.Redis(connection_pool=self._async_pool)



    def get_queue(self, queue_name='grid_trading'):
        if self._queue is None:
            conn = self.get_connection()
            self._queue = Queue(queue_name, connection=conn, job_class=CustomJob)
        return self._queue



    # New method to handle UnicodeDecodeError
    def safe_decode(self, value):
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return value.decode('latin-1')
        return value

    def cleanup(self):
        """리소스 정리 메서드"""
        if hasattr(self, 'redis_conn') and self.redis_conn:
            self.redis_conn.close()
        if hasattr(self, 'task_queue'):
            # RQ의 Queue 객체에 대한 특별한 정리가 필요하다면 여기에 추가
            pass
        print("Redis connections and resources have been cleaned up.")
        
    def close_connection(self):
        if self._pool:
            self._pool.close()
        if self._async_pool:
            asyncio.create_task(self._async_pool.disconnect())
        if self._queue:
            self._queue.empty()
        
class CustomJob(RQJob):
    def restore(self, data):
        raw_data = data.get(b'data', b'')
        if isinstance(raw_data, str):
            raw_data = raw_data.encode('latin-1')
        try:
            self.data = zlib.decompress(raw_data)
        except zlib.error:
            self.data = raw_data

        #if isinstance(self.data, bytes):
        #    try:
        #        self.data = self.data.decode('utf-8')
        #    except UnicodeDecodeError:
        #        # UTF-8 디코딩 실패 시 다른 인코딩 시도 또는 바이너리 데이터로 처리
        #        try:
        #            self.data = self.data.decode('iso-8859-1')  # 또는 다른 인코딩 시도
        #        except UnicodeDecodeError:
        #            # 모든 디코딩 시도 실패 시 바이너리 데이터로 취급
        #            print("데이터를 디코딩할 수 없습니다. 바이너리 데이터로 처리합니다.")
        if not isinstance(self.data, str):
            self.data = str(self.data)  # 문자열이 아닌 경우 문자열로 변환
   
        #if isinstance(self.data, bytes):
        #    try:
        #        # 먼저 UTF-8로 디코딩을 시도
        #        self.data = self.data.decode('utf-8')
        #    except UnicodeDecodeError:
        #        # UTF-8 디코딩에 실패하면 Latin-1로 디코딩
        #        self.data = self.data.decode('latin-1')
        
        super().restore(data)

    def save(self, pipeline=None, include_meta=False, include_result=True):
        if isinstance(self.data, str):
            # 문자열을 Latin-1로 인코딩
            self.data = self.data.encode('latin-1', errors='replace')
        compressed_data = zlib.compress(self.data)
        if pipeline is not None:
            pipeline.hset(self.key, 'data', compressed_data)
        else:
            self.connection.hset(self.key, 'data', compressed_data)
        super().save(pipeline=pipeline, include_meta=include_meta, include_result=include_result)
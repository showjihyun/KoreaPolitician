"""DB 접속 설정을 환경변수에서 읽는 공통 모듈.

여러 파일이 같은 db_config 딕셔너리를 각자 만들고 있었고, 전부
`os.environ.get('POSTGRES_PORT', 5432)` 형태였다. 이 방식에는 함정이 있다.
GitHub Actions 에서 등록하지 않은 시크릿은 "없음"이 아니라 **빈 문자열**로
주입되므로, os.environ.get 은 기본값이 아니라 "" 를 돌려준다. 그 결과
int("") 가 ValueError 로 파이프라인이 시작하자마자 죽는다.

여기서는 빈 문자열을 "설정되지 않음"으로 취급한다.
"""

import os
from typing import Any, Dict, Optional


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    """환경변수를 읽되 빈 문자열은 미설정으로 본다."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_int(name: str, default: int) -> int:
    """정수 환경변수. 값이 비었거나 숫자가 아니면 기본값을 쓴다."""
    raw = env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"환경변수 {name} 은 정수여야 합니다: {raw!r}")


def env_required(name: str) -> str:
    """반드시 있어야 하는 값. 없으면 즉시 실패시킨다.

    빈 문자열을 조용히 넘기면 나중에 엉뚱한 곳에서 터지므로,
    여기서 원인이 분명한 에러를 낸다.
    """
    value = env(name)
    if value is None:
        raise RuntimeError(f"환경변수 {name} 이 설정되지 않았습니다.")
    return value


def db_config_from_env() -> Dict[str, Any]:
    """psycopg 접속 설정. 모든 진입점(API·크롤러·스크립트)이 이걸 쓴다."""
    return {
        "host": env("POSTGRES_HOST", "localhost"),
        "port": env_int("POSTGRES_PORT", 5432),
        "user": env("POSTGRES_USER", "postgres"),
        "password": env("POSTGRES_PASSWORD", "1234"),
        "dbname": env("POSTGRES_DB", "postgres"),
    }


def api_base_url() -> str:
    """크롤러가 관계를 POST 할 API 주소."""
    return env("API_BASE_URL", "http://localhost:5000").rstrip("/")


# --- 동기(크롤러)용 공유 커넥션 풀 ---------------------------------------
# 크롤러는 저장 1건마다 psycopg.connect() 로 새 커넥션 + TLS 핸드셰이크를
# 했다. ThreadPoolExecutor 로 수백 명을 병렬 처리하면 관리형 Postgres 의
# 커넥션 한도(Supabase 무료: 직결 ~60, Supavisor pool_size 15)를 즉시
# 소진해 "too many clients" 로 수집분이 통째로 유실된다.
# 풀 하나를 공유하고, 워커가 풀보다 많으면 대기시킨다.

import threading

_sync_pool = None
_sync_pool_lock = threading.Lock()


def get_sync_pool():
    """크롤러가 공유하는 동기 커넥션 풀. 스레드 안전."""
    global _sync_pool
    with _sync_pool_lock:
        if _sync_pool is None:
            from psycopg.conninfo import make_conninfo
            from psycopg_pool import ConnectionPool

            _sync_pool = ConnectionPool(
                make_conninfo(**db_config_from_env()),
                min_size=1,
                max_size=env_int("DB_POOL_MAX_SIZE", 5),
                open=True,
                # 관리형 Postgres 가 끊은 유휴 커넥션을 걸러낸다.
                check=ConnectionPool.check_connection,
                # Supavisor 트랜잭션 풀러는 prepared statement 를 지원하지 않는다.
                kwargs={"prepare_threshold": None},
            )
        return _sync_pool


def close_sync_pool():
    """배치 종료 시 풀을 닫는다."""
    global _sync_pool
    with _sync_pool_lock:
        pool, _sync_pool = _sync_pool, None
    if pool is not None:
        pool.close()

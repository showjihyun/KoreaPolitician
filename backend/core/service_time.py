"""사람이 읽는 날짜와 시각은 한국시간으로 맞춘다.

러너도 DB 도 UTC 로 돈다. 그대로 찍으면 한국시간 새벽에 돈 회차가 전날
날짜로 남는다. 2026-09-17 21:51 UTC(한국시간 09-18 06:51)에 돈 회차가
기준일을 2026-09-17 로 적었고, 화면의 "최근 7일" 범위도 하루 뒤처져
보였다. 한국 국회를 보는 화면에서 날짜가 UTC 인 것은 설명하기 어렵다.

저장하는 시각(observed_at, collected_at)은 UTC 그대로 둔다. 시각 자체는
시간대와 무관하고, 옮기면 이미 쌓인 행과 뒤섞인다. 여기서 바꾸는 것은
날짜를 새로 찍는 자리와 화면에 내보내는 자리뿐이다.

윈도우와 도커, GitHub 러너가 모두 같은 값을 내야 하므로 zoneinfo 대신
고정 오프셋을 쓴다. 한국은 1988년 이후 서머타임이 없다.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9), "KST")


def now_kst() -> datetime:
    """지금 시각을 한국시간으로."""
    return datetime.now(KST)


def service_date(fmt: str = "%Y%m%d") -> str:
    """이 회차가 쓸 기준일. 한국시간 기준이다."""
    return now_kst().strftime(fmt)


def to_kst(value: datetime) -> datetime:
    """시각을 한국시간으로 옮긴다.

    시간대가 없는 값은 UTC 로 본다. DB 의 TIMESTAMP 열(turing_logs.timestamp,
    politician_sns_hotness.collected_at)이 그렇게 들어 있다.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST)


def kst_stamp(value: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> Optional[str]:
    """화면에 내보낼 시각 문구. 값이 없으면 None 을 그대로 돌려준다."""
    return to_kst(value).strftime(fmt) if value else None

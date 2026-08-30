"""유튜브 조회수 파싱 회귀 테스트.

운영 크롤링에서 영상 1,948개를 찾고도 수집이 0건이었다. 원인은 파서가
한국어 표기만 처리하는데 CI 러너 로케일이 en-US 라 유튜브가 영어로
응답한 것이었다. 아래가 깨지면 같은 일이 다시 벌어진다.

    PYTHONPATH=backend pytest backend/tests/test_view_count.py -v
    PYTHONPATH=backend python backend/tests/test_view_count.py
"""

from crawlers.view_count import parse_view_count


def test_korean_units():
    """ko-KR 로케일 표기. 로컬에서는 이 형식만 들어왔다."""
    assert parse_view_count("조회수 5만회 6일 전") == 50_000
    assert parse_view_count("조회수 23만회 9일 전") == 230_000
    assert parse_view_count("조회수 1.2만회 1시간 전") == 12_000
    assert parse_view_count("조회수 5천회 3일 전") == 5_000
    assert parse_view_count("조회수 1,234회 2일 전") == 1_234
    assert parse_view_count("조회수 1.5억회 1년 전") == 150_000_000


def test_english_units():
    """en-US 로케일 표기. CI 러너가 받던 형식이고 0 으로 처리되고 있었다."""
    assert parse_view_count("144K views 4 days ago") == 144_000
    assert parse_view_count("94K views 4 days ago") == 94_000
    assert parse_view_count("1.2M views 2 weeks ago") == 1_200_000
    assert parse_view_count("1,234 views 1 day ago") == 1_234
    assert parse_view_count("3B views 5 years ago") == 3_000_000_000


def test_live_stream_format():
    """라이브 영상은 조회수 뒤에 다른 정보가 더 붙는다."""
    assert parse_view_count("조회수 9.3만회 스트리밍 시간: 2시간 전") == 93_000
    assert parse_view_count("조회수 1,024회 스트리밍 시간: 30분 전") == 1_024


def test_unparseable_returns_zero():
    """읽지 못하면 0 을 돌려주고 예외를 던지지 않아야 한다."""
    for meta in ["", None, "2시간 전", "Premieres tomorrow", "조회수 회", "views"]:
        assert parse_view_count(meta) == 0, meta


def test_threshold_behaviour_matches_crawler():
    """크롤러는 1,000회 초과만 채택한다. 경계를 고정해 둔다."""
    assert parse_view_count("조회수 1,000회 1일 전") == 1_000     # 채택 안 됨
    assert parse_view_count("조회수 1,001회 1일 전") == 1_001     # 채택
    assert parse_view_count("144K views") > 1_000                 # 예전에는 0 이라 버려졌다


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed.append(fn.__name__)
            print(f"  FAIL  {fn.__name__}: {exc}")
        else:
            print(f"  OK    {fn.__name__}")
    print()
    if failed:
        raise SystemExit(f"{len(failed)}개 실패")
    print(f"{len(tests)}개 테스트 통과")

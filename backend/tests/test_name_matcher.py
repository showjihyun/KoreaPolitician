"""이름 매칭 회귀 테스트.

크롤러는 원래 `if name in text` 로 이름을 찾았고, 그 결과 실제 언급이 없는
관계가 만들어졌다. 첫 크롤링에서 생성된 유일한 관계 `김윤덕 -> 김윤` 이
그 사례다. 아래 케이스가 다시 깨지면 같은 오염이 재발한다.

    PYTHONPATH=backend pytest backend/tests/test_name_matcher.py -v
    PYTHONPATH=backend python backend/tests/test_name_matcher.py
"""

from core.name_matcher import find_names, mentions

# 22대 국회의원 296명 중 충돌 위험이 있는 이름들 + 대조군
NAMES = [
    "김윤", "김윤덕",          # 부분문자열 관계 (실제 오탐 발생)
    "김현", "김현정",
    "박정", "박정하", "박정현", "박정훈",
    "김건", "허영", "황희", "손솔",
    "이재명", "나경원", "안철수", "정청래", "권성동",
]


def test_longer_name_wins():
    """긴 이름이 잡힌 자리에서 짧은 이름이 또 잡히면 안 된다."""
    assert find_names("김윤덕 의원이 발언했다", NAMES) == ["김윤덕"]
    assert find_names("김현정 의원", NAMES) == ["김현정"]
    assert find_names("박정훈 의원과 박정하 의원", NAMES) == ["박정하", "박정훈"]


def test_non_member_proper_nouns_are_rejected():
    """의원이 아닌 고유명사의 일부를 이름으로 오인하면 안 된다."""
    assert find_names("김건희 여사가 참석한 정치 행사", NAMES) == []
    assert find_names("박정희 전 대통령 기념관", NAMES) == []
    assert find_names("황희 정승의 일화", NAMES) == []


def test_common_noun_is_rejected():
    """'허영' 처럼 일반명사와 겹치는 이름을 걸러야 한다."""
    assert find_names("허영심이 가득한 발언", NAMES) == []
    assert find_names("허영을 버려야 한다", NAMES) == ["허영"]  # 조사 '을' 뒤 -> 정상 언급


def test_particles_are_allowed():
    """이름 뒤 조사·호칭은 정상 언급으로 인정한다."""
    for text, expected in [
        ("김윤은 반대했다", "김윤"),
        ("김윤이 말했다", "김윤"),
        ("김건 의원실", "김건"),
        ("황희 장관", "황희"),
        ("이재명 대표의 발언", "이재명"),
        ("나경원과 안철수", "나경원"),
    ]:
        assert expected in find_names(text, NAMES), f"{text!r} 에서 {expected} 누락"


def test_short_name_still_found_when_standalone():
    """긴 이름이 없을 때는 짧은 이름이 정상적으로 잡혀야 한다."""
    assert find_names("김윤 의원과 김현 의원이 만났다", NAMES) == ["김윤", "김현"]


def test_both_found_when_both_present():
    """긴 이름과 짧은 이름이 각각 따로 등장하면 둘 다 잡아야 한다."""
    got = find_names("김윤덕 의원과 김윤 의원이 함께", NAMES)
    assert got == ["김윤", "김윤덕"], got


def test_name_inside_word_is_rejected():
    """낱말 중간에서 시작하는 매칭은 버린다."""
    assert find_names("호남박정 지역구", NAMES) == []


def test_multiple_members_in_one_text():
    text = "이재명 대표와 나경원 의원, 그리고 권성동 의원이 정치 현안을 논의했다"
    assert find_names(text, NAMES) == ["권성동", "나경원", "이재명"]


def test_mentions_helper():
    """mentions() 는 후보 전체를 넘겨야 오탐을 막는다."""
    assert mentions("김윤덕 의원", "김윤덕", NAMES)
    assert not mentions("김윤덕 의원", "김윤", NAMES)
    assert not mentions("김건희 여사", "김건", NAMES)


def test_empty_and_no_match():
    assert find_names("", NAMES) == []
    assert find_names("오늘 날씨가 맑습니다", NAMES) == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed.append((fn.__name__, e))
            print(f"  FAIL  {fn.__name__}: {e}")
        else:
            print(f"  OK    {fn.__name__}")
    print()
    if failed:
        raise SystemExit(f"{len(failed)}개 실패")
    print(f"{len(tests)}개 테스트 통과")

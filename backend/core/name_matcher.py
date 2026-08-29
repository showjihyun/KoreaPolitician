"""텍스트에서 국회의원 이름을 찾아내는 매처.

기존 크롤러는 `if name in text` 단순 부분일치를 썼다. 한국어 이름은 다른
고유명사의 앞부분과 자주 겹치기 때문에, 이 방식은 실제 언급이 없는데도
관계를 만들어낸다. 22대 국회의원 296명 중 2글자 이름이 7명 있는데
(김건·김윤·김현·박정·손솔·허영·황희) 전부 위험하다.

  "김건희 여사"   -> '김건' 추출
  "박정희 전 대통령" -> '박정' 추출
  "허영심"        -> '허영' 추출
  "김윤덕 의원"    -> '김윤덕' 과 '김윤' 둘 다 추출

마지막 사례는 실제로 관측됐다. 첫 크롤링에서 만들어진 유일한 관계가
`김윤덕 -> 김윤` 이었고, 이는 실제 관계가 아니라 매칭 아티팩트였다.

여기서는 두 가지로 막는다.

1. 긴 이름 우선 매칭 후 해당 구간을 소비 처리 — '김윤덕' 이 잡힌 자리에서
   '김윤' 이 다시 잡히지 않는다.
2. 경계 검사 — 앞뒤가 한글이면 더 긴 낱말의 일부로 보고 버린다. 단 뒤에
   오는 글자가 조사/호칭이면 정상적인 언급이므로 통과시킨다.
"""

from typing import Iterable, List, Set

# 이름 뒤에 올 수 있는 조사/호칭의 첫 글자.
# 한 글자만 보고 판단하므로 넉넉히 잡되, 이름의 일부가 될 만한 글자는 뺀다.
_FOLLOWING_PARTICLES = set(
    "은는이가을를의에와과도만께랑라나든밖부까처보마조커대뿐등및"  # 조사
    "측씨님계파전현안"  # 호칭·접미
)


# 이름 바로 뒤에 오면 현직 의원이 아니라 동명의 다른 인물을 가리키는 낱말.
# 경계 검사만으로는 "황희 정승" 과 "황희 장관" 을 구분할 수 없어서 필요하다.
# 완전한 해결은 개체명 인식이 필요하므로, 관측된 충돌만 좁게 막는다.
_DISAMBIGUATING_WORDS = ("정승", "여사", "대통령", "선생", "장군")


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _boundary_ok(text: str, start: int, end: int) -> bool:
    """매칭 구간이 더 긴 한글 낱말의 일부가 아닌지 확인한다."""
    # 앞: 한글이 붙어 있으면 이름이 낱말 중간에서 시작한 것이다.
    if start > 0 and _is_hangul(text[start - 1]):
        return False

    # 뒤: 한글이 붙어 있으면 조사/호칭일 때만 인정한다.
    if end < len(text):
        nxt = text[end]
        if _is_hangul(nxt) and nxt not in _FOLLOWING_PARTICLES:
            return False

    # 뒤따르는 낱말이 동명이인을 가리키면 버린다. ("황희 정승")
    tail = text[end:].lstrip()
    if tail.startswith(_DISAMBIGUATING_WORDS):
        return False
    # "박정희 전 대통령" 처럼 한 칸 건너뛴 경우도 본다.
    parts = tail.split()
    if len(parts) >= 2 and parts[0] in ("전", "前") and parts[1].startswith(_DISAMBIGUATING_WORDS):
        return False

    return True


def find_names(text: str, names: Iterable[str]) -> List[str]:
    """text 에서 실제로 언급된 이름만 돌려준다.

    긴 이름부터 검사하고 매칭된 구간을 소비 처리하므로, 짧은 이름이 긴 이름
    안에서 중복으로 잡히지 않는다. 같은 이름이 다른 위치에 또 나오면 그
    자리는 정상적으로 매칭된다.
    """
    if not text:
        return []

    consumed = [False] * len(text)
    found: Set[str] = set()

    for name in sorted(set(n for n in names if n), key=len, reverse=True):
        pos = 0
        while True:
            idx = text.find(name, pos)
            if idx == -1:
                break
            end = idx + len(name)
            if not any(consumed[idx:end]) and _boundary_ok(text, idx, end):
                for i in range(idx, end):
                    consumed[i] = True
                found.add(name)
            pos = idx + 1

    return sorted(found)


def mentions(text: str, name: str, names: Iterable[str]) -> bool:
    """text 가 name 을 실제로 언급하는지 확인한다.

    names 에는 후보 이름 전체를 넘겨야 한다. '김윤' 하나만 넘기면 '김윤덕'
    이 더 긴 이름이라는 사실을 알 수 없어 오탐을 막지 못한다.
    """
    return name in find_names(text, names)

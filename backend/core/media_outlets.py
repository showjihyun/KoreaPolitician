"""언론사를 진영(camp)으로 묶는다.

왜 필요한가. 관계 하나가 어느 언론사에서 나왔는지 모르면, 한 진영만 쓴
갈등 기사와 양쪽 진영이 각자 취재해서 쓴 갈등 기사를 구분할 수 없다.
Mullainathan & Shleifer(2005)와 Gentzkow & Shapiro(2006)의 요지는
"독자가 여러 매체를 교차해 읽으면 편향이 상쇄된다" 인데, 그 교차 검증을
사람 대신 파이프라인이 하려면 매체를 진영으로 묶어 둬야 한다.

진영 구분은 그 자체로 논쟁적인 판단이다. 그래서 다음 원칙을 지킨다.

1. 표를 코드에 숨기지 않고 여기 한 곳에 모아 두고, 근거를 함께 적는다.
2. 모르는 매체는 억지로 배정하지 않고 중도로 둔다. 잘못 배정하는 것보다
   교차 검증에 기여하지 않는 편이 낫다.
3. 이 표는 1단계의 출발점이다. 관측이 쌓이면 언론사x정당 논조 기준선을
   데이터로 추정해(문서 알고리즘 1) 이 정적 표를 대체한다.

근거

- 최창식·임영호(2021), "대통령 관련 보도의 감성 분석과 정파성의 지형",
  한국언론학보 65(1). 10개 신문 약 9만 건의 감성지수. 한겨레가 가장 긍정,
  조선일보가 유일하게 부정으로 나타났다.
- 이재완·김용환(2023), "언론사의 정파성에 따른 이태원 참사 뉴스 프레임
  비교 연구", 정치커뮤니케이션연구 71. 조선·중앙·동아 대 한겨레·경향.
- Kim, Lee & Na(2023), KoPolitic 벤치마크. 보수 2 / 중도 2 / 진보 2 구성.
- 최선규·유수정·양성은(2012), "뉴스 시장의 경쟁과 미디어 편향성",
  정보통신정책연구 19(2). 신문이 방송보다 이념 분산이 크다.

자세한 배경은 docs/MEDIA_BIAS_RESEARCH.md 를 본다.
"""

from typing import Dict, Iterable, List, Optional, Set

CAMP_CONSERVATIVE = "보수"
CAMP_PROGRESSIVE = "진보"
CAMP_CENTER = "중도"

#: 교차 검증에서 세는 진영. 순서는 화면 표기 순서이기도 하다.
CAMPS: List[str] = [CAMP_CONSERVATIVE, CAMP_CENTER, CAMP_PROGRESSIVE]

#: 진영을 배정하지 못했을 때 쓰는 값. 통신사와 지상파도 여기 들어간다.
DEFAULT_CAMP = CAMP_CENTER


# 매체명은 네이버가 돌려주는 표기를 그대로 쓴다("조선일보", "한겨레").
# 같은 매체가 "한겨레신문" 처럼 들어오는 경우가 있어 별칭도 함께 둔다.
_CONSERVATIVE = {
    "조선일보", "중앙일보", "동아일보", "문화일보", "세계일보",
    "TV조선", "채널A", "MBN", "조선비즈", "중앙SUNDAY",
    "매일경제", "한국경제", "서울경제", "헤럴드경제", "아시아경제",
    "파이낸셜뉴스", "데일리안", "뉴데일리", "스카이데일리", "미디어펜",
}

_PROGRESSIVE = {
    "한겨레", "한겨레신문", "경향신문", "오마이뉴스", "프레시안",
    "미디어오늘", "민중의소리", "뉴스타파", "시사IN", "시사인",
}

# 통신사·지상파·종합편성 일부·경제 이외 일간지. 명시적으로 중도에 둔다.
# 통신사(연합·뉴시스·뉴스1)를 여기 두는 이유는 이들이 정파적이지 않아서가
# 아니라, 전재 기사가 모든 진영에 동시에 실려 진영 신호로 쓸 수 없기
# 때문이다. 전재 묶음 처리는 relation_evidence 의 사건 클러스터링이 맡는다.
_CENTER = {
    "연합뉴스", "연합뉴스TV", "뉴시스", "뉴스1",
    "KBS", "MBC", "SBS", "YTN", "JTBC", "CBS", "노컷뉴스",
    "한국일보", "서울신문", "국민일보", "머니투데이", "이데일리",
    "아이뉴스24", "전자신문", "디지털타임스", "코리아헤럴드",
    "Naver", "네이버",
}

#: press 문자열 -> 진영. 조회는 정규화한 이름으로 한다.
_CAMP_BY_PRESS: Dict[str, str] = {}
for _name in _CONSERVATIVE:
    _CAMP_BY_PRESS[_name] = CAMP_CONSERVATIVE
for _name in _PROGRESSIVE:
    _CAMP_BY_PRESS[_name] = CAMP_PROGRESSIVE
for _name in _CENTER:
    _CAMP_BY_PRESS[_name] = CAMP_CENTER


def normalize_press(press: Optional[str]) -> str:
    """매체명 표기 흔들림을 줄인다.

    네이버 목록은 "조선일보 " 처럼 공백이 붙거나 "조선일보 언론사 선정"
    같은 꼬리표가 붙어 오는 경우가 있다.
    """
    if not press:
        return ""
    name = str(press).strip()
    for suffix in ("언론사 선정", "언론사선정", "PICK", "pick"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def camp_of(press: Optional[str]) -> str:
    """매체명을 진영으로 바꾼다. 모르는 매체는 중도로 둔다."""
    name = normalize_press(press)
    if not name:
        return DEFAULT_CAMP
    if name in _CAMP_BY_PRESS:
        return _CAMP_BY_PRESS[name]
    # "조선일보(온라인)" 처럼 접미가 붙는 경우를 위한 부분 일치.
    # 짧은 이름이 다른 매체명에 섞이지 않도록 3글자 이상만 본다.
    for known, camp in _CAMP_BY_PRESS.items():
        if len(known) >= 3 and known in name:
            return camp
    return DEFAULT_CAMP


def is_known_press(press: Optional[str]) -> bool:
    """표에 등재된 매체인지. 중도 기본값과 명시적 중도를 구분할 때 쓴다."""
    name = normalize_press(press)
    if not name:
        return False
    if name in _CAMP_BY_PRESS:
        return True
    return any(len(known) >= 3 and known in name for known in _CAMP_BY_PRESS)


def camps_of(presses: Iterable[Optional[str]]) -> Set[str]:
    """매체 목록에 걸친 진영 집합."""
    return {camp_of(p) for p in presses if normalize_press(p)}


def cluster_camp(presses: Iterable[Optional[str]]) -> str:
    """사건 클러스터 하나에 진영 하나를 배정한다.

    같은 원문이 여러 진영에 실렸다면 그것은 각 진영의 편집 판단이 아니라
    통신사 한 곳의 판단이 퍼진 것이다. 이런 클러스터를 양쪽 진영이 모두
    보도한 것으로 세면 교차 검증이 항상 통과해 버린다. 그래서 진영이
    둘 이상 걸치면 중도(통신)로 접는다.
    """
    camps = camps_of(presses)
    if len(camps) == 1:
        return next(iter(camps))
    return CAMP_CENTER


def coverage_table() -> Dict[str, List[str]]:
    """감사용. 어느 매체를 어느 진영으로 보고 있는지 그대로 내보낸다."""
    table: Dict[str, List[str]] = {camp: [] for camp in CAMPS}
    for press, camp in sorted(_CAMP_BY_PRESS.items()):
        table[camp].append(press)
    return table

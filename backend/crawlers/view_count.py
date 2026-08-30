"""유튜브 검색 결과의 조회수 메타데이터 파싱.

원래 파서는 한국어 표기만 처리했다.

    if '조회수' in meta:
        ...

GitHub Actions 러너는 로케일이 en-US 라 유튜브가 영어로 응답하고, 그러면
위 조건이 거짓이 되어 조회수가 0 으로 남는다. 0 은 1,000회 임계값에 걸려
전부 버려진다. 실제로 운영 크롤링에서 영상 1,948개를 찾고도 수집이 0건이었고,
집계는 '파싱 1477 / 조회수미달 1477' 이었다. 로컬(ko-KR)에서만 동작하고
CI 에서만 0건이던 이유가 이것이다.

    ko-KR : '조회수 5만회 6일 전'        -> 50000
    en-US : '144K views 4 days ago'      -> 0   (버려짐)

브라우저 컨텍스트에 ko-KR 을 지정해 근본 원인을 없애되, 유튜브가 로케일을
무시하는 경우를 대비해 이 파서는 두 표기를 모두 처리한다.
"""

import re

# 한국어: '조회수 1.2만회', '조회수 5천회', '조회수 1,234회'
# 라이브 영상은 '조회수 9.3만회 스트리밍 시간: 2시간 전' 처럼 뒤가 더 붙는다.
_KO_PATTERN = re.compile(r"조회수\s*([\d,.]+)\s*([만천억])?\s*회")

# 영어: '144K views', '1.2M views', '1,234 views'
_EN_PATTERN = re.compile(r"([\d,.]+)\s*([KMB])?\s*views", re.IGNORECASE)

_KO_UNITS = {"천": 1_000, "만": 10_000, "억": 100_000_000}
_EN_UNITS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _to_int(number: str, unit: str, units: dict) -> int:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return 0
    if unit:
        value *= units.get(unit.upper() if units is _EN_UNITS else unit, 1)
    return int(value)


def parse_view_count(meta: str) -> int:
    """메타데이터 문자열에서 조회수를 뽑는다. 못 읽으면 0.

    한국어/영어 표기를 모두 처리하며, 라이브 영상처럼 뒤에 다른 정보가
    붙어 있어도 조회수 부분만 정확히 잡는다.
    """
    if not meta:
        return 0

    match = _KO_PATTERN.search(meta)
    if match:
        return _to_int(match.group(1), match.group(2), _KO_UNITS)

    match = _EN_PATTERN.search(meta)
    if match:
        return _to_int(match.group(1), match.group(2), _EN_UNITS)

    return 0

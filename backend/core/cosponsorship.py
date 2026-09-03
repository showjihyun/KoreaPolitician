"""국회 공동발의 그래프.

왜 뉴스 밖에서 근거를 가져오나
------------------------------
뉴스만 보면 우호 관계가 구조적으로 사라진다. 갈등은 보도되고 협력은 보도되지
않기 때문이다. Galtung & Ruge(1965)와 Harcup & O'Neill(2001)의 뉴스 가치
목록에서 부정성과 갈등은 상위 항목이고, Soroka(2006)는 언론이 부정 정보를
긍정 정보보다 훨씬 크게 다룬다는 것을 보였다. 국내에서도 정성호·이준호(2011)
가 국회 보도에서 부정 논조가 긍정을 앞선다고 보고했다.

실제로 이 저장소의 관계도는 갈등 36건 대 우호 3건이었다. 이 비대칭이 현실인지
추출기 결함인지는 뉴스 안에서는 가릴 수 없다. 그래서 뉴스 선택을 거치지 않는
자료가 필요하다.

공동발의는 그 조건을 만족한다. 두 의원이 같은 법안에 이름을 올린 사실은
기자의 판단과 무관하게 기록되며, 협력의 직접적인 증거다.

지금 무엇에 쓰나
----------------
1. DCP 의 '동맹' 정의를 대체한다. 예전 정의는 "같은 정당" 이었는데, 그러면
   같은 당 의원 170명이 서로 전부 동맹이 되어 정파 구조를 보정하는 게 아니라
   증폭한다.
2. 감사 화면에서 대조 자료로 쓴다. 뉴스가 갈등이라고 말하는 두 사람이 법안
   14건을 함께 발의했다면, 그 사실이 판단에 필요하다.

아직 하지 않는 것: 관계 점수의 사전확률로 쓰는 것(문서 알고리즘 3의 역가중)
은 관측이 더 쌓여야 한다. 자세한 내용은 docs/MEDIA_BIAS_RESEARCH.md.
"""

import logging
import re
from collections import Counter
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from core.db_config import get_sync_pool

logger = logging.getLogger(__name__)


COSPONSORSHIP_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS public.assembly_bills (
        bill_id TEXT PRIMARY KEY,
        bill_no TEXT,
        bill_name TEXT,
        committee TEXT,
        propose_dt TEXT,
        proc_result TEXT,
        age TEXT,
        rst_proposer TEXT,
        publ_proposer TEXT,
        detail_link TEXT,
        collected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_assembly_bills_age
        ON public.assembly_bills (age);

    -- 쌍 단위 집계. 원본(assembly_bills)에서 언제든 다시 만들 수 있다.
    CREATE TABLE IF NOT EXISTS public.cosponsorship (
        pair_key TEXT PRIMARY KEY,
        entity_a TEXT NOT NULL,
        entity_b TEXT NOT NULL,
        bills INTEGER NOT NULL DEFAULT 0,
        first_date TEXT,
        last_date TEXT,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cosponsorship_a ON public.cosponsorship (entity_a);
    CREATE INDEX IF NOT EXISTS idx_cosponsorship_b ON public.cosponsorship (entity_b);
"""


def ensure_schema() -> None:
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(COSPONSORSHIP_SCHEMA_SQL)


# --- 발의자 이름 정리 -------------------------------------------------------

#: "강경숙의원", "강경숙 의원", "강경숙(더불어민주당)" 같은 표기를 벗긴다.
_SUFFIX = re.compile(r"\s*\(.*?\)\s*$")
_TITLES = ("의원", "위원장", "부의장", "의장")


def normalize_proposer(raw: str) -> str:
    name = _SUFFIX.sub("", str(raw or "")).strip()
    for title in _TITLES:
        if name.endswith(title):
            name = name[: -len(title)].strip()
    return name


def parse_proposers(rst_proposer: Optional[str],
                    publ_proposer: Optional[str],
                    members: Iterable[str]) -> List[str]:
    """한 법안의 발의자 중 현직 의원만 골라 돌려준다.

    PUBL_PROPOSER 는 쉼표로 이어진 이름 목록이다. 표기가 흔들리므로
    정규화한 뒤 의원 명부와 교집합을 취한다. 명부에 없는 이름(전직 의원,
    정부 제출 등)은 버린다. 억지로 맞추면 없는 관계가 생긴다.
    """
    known = set(members)
    found: List[str] = []
    seen: Set[str] = set()

    for chunk in [rst_proposer or ""] + re.split(r"[,;/]", publ_proposer or ""):
        name = normalize_proposer(chunk)
        if name and name in known and name not in seen:
            seen.add(name)
            found.append(name)
    return found


# --- 쌍 집계 ---------------------------------------------------------------

def pair_key(name_a: str, name_b: str) -> str:
    a, b = sorted([name_a.strip(), name_b.strip()])
    return f"{a}|{b}"


def count_pairs(bills: Iterable[Dict[str, Any]],
                members: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """법안 목록에서 공동발의 쌍을 센다. 순수 함수라 테스트가 쉽다.

    발의자가 많은 법안일수록 한 쌍의 의미는 옅어지지만, 여기서는 가중치를
    주지 않고 건수만 센다. 가중은 이 값을 쓰는 쪽에서 정한다.
    """
    known = list(members)
    counts: Counter = Counter()
    first: Dict[str, str] = {}
    last: Dict[str, str] = {}

    for bill in bills:
        proposers = parse_proposers(bill.get("rst_proposer"),
                                    bill.get("publ_proposer"), known)
        if len(proposers) < 2:
            continue
        date = str(bill.get("propose_dt") or "")
        for a, b in combinations(sorted(proposers), 2):
            key = pair_key(a, b)
            counts[key] += 1
            if date:
                if key not in first or date < first[key]:
                    first[key] = date
                if key not in last or date > last[key]:
                    last[key] = date

    result: Dict[str, Dict[str, Any]] = {}
    for key, bill_count in counts.items():
        entity_a, _, entity_b = key.partition("|")
        result[key] = {
            "pair_key": key,
            "entity_a": entity_a,
            "entity_b": entity_b,
            "bills": bill_count,
            "first_date": first.get(key),
            "last_date": last.get(key),
        }
    return result


# --- 적재 / 조회 -----------------------------------------------------------

def save_bills(bills: Sequence[Dict[str, Any]]) -> int:
    if not bills:
        return 0
    payload = [(
        b.get("bill_id"), b.get("bill_no"), b.get("bill_name"), b.get("committee"),
        b.get("propose_dt"), b.get("proc_result"), str(b.get("age") or ""),
        b.get("rst_proposer"), b.get("publ_proposer"), b.get("detail_link"),
    ) for b in bills if b.get("bill_id")]
    if not payload:
        return 0

    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO public.assembly_bills
                    (bill_id, bill_no, bill_name, committee, propose_dt,
                     proc_result, age, rst_proposer, publ_proposer, detail_link)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (bill_id) DO UPDATE SET
                    bill_no = EXCLUDED.bill_no,
                    bill_name = EXCLUDED.bill_name,
                    committee = EXCLUDED.committee,
                    propose_dt = EXCLUDED.propose_dt,
                    proc_result = EXCLUDED.proc_result,
                    rst_proposer = EXCLUDED.rst_proposer,
                    publ_proposer = EXCLUDED.publ_proposer,
                    detail_link = EXCLUDED.detail_link
                """,
                payload,
            )
    return len(payload)


def load_bills(age: Optional[str] = None) -> List[Dict[str, Any]]:
    query = ("SELECT bill_id, rst_proposer, publ_proposer, propose_dt, age "
             "FROM public.assembly_bills")
    params: Tuple = ()
    if age:
        query += " WHERE age = %s"
        params = (str(age),)
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return [{"bill_id": r[0], "rst_proposer": r[1], "publ_proposer": r[2],
                     "propose_dt": r[3], "age": r[4]} for r in cur.fetchall()]


def rebuild_pairs(members: Iterable[str], age: Optional[str] = None) -> int:
    """저장된 법안에서 쌍 집계를 다시 만든다."""
    pairs = count_pairs(load_bills(age), members)
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE public.cosponsorship")
            if pairs:
                cur.executemany(
                    """
                    INSERT INTO public.cosponsorship
                        (pair_key, entity_a, entity_b, bills, first_date, last_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [(p["pair_key"], p["entity_a"], p["entity_b"], p["bills"],
                      p["first_date"], p["last_date"]) for p in pairs.values()],
                )
    return len(pairs)


def bills_between(name_a: str, name_b: str) -> Optional[int]:
    """두 의원이 함께 발의한 법안 수.

    돌려주는 값이 세 가지다.

        None  자료를 아직 수집하지 않았다 (API 키가 없거나 수집 전)
        0     수집했고, 두 사람이 함께 발의한 적이 없다
        n     함께 발의한 법안 수

    None 과 0 을 구분하는 이유가 있다. 둘을 같이 0 으로 돌려주면 화면과
    감사 응답에서 "협력한 적 없음" 처럼 보인다. 실제로는 확인한 적이
    없는 것이고, 그것은 다른 진술이다.
    """
    if not is_populated():
        return None
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT bills FROM public.cosponsorship WHERE pair_key = %s",
                        (pair_key(name_a, name_b),))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def allies_of(name: str, min_bills: int = 5, limit: int = 50) -> List[Tuple[str, int]]:
    """공동발의가 잦은 상대. DCP 의 '동맹' 을 여기서 정의한다.

    min_bills 기본값 5는 우연한 한두 건을 걸러내기 위한 값이다. 관측이
    쌓이면 분포를 보고 조정한다(scripts/evidence_report.py).
    """
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT CASE WHEN entity_a = %s THEN entity_b ELSE entity_a END, bills
                FROM public.cosponsorship
                WHERE (entity_a = %s OR entity_b = %s) AND bills >= %s
                ORDER BY bills DESC
                LIMIT %s
                """,
                (name, name, name, min_bills, limit),
            )
            return [(r[0], int(r[1])) for r in cur.fetchall()]


def is_populated() -> bool:
    """공동발의 자료가 있는지. 없으면 호출부가 예전 방식으로 물러선다."""
    try:
        with get_sync_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM public.cosponsorship LIMIT 1")
                return cur.fetchone() is not None
    except Exception:                                     # noqa: BLE001
        logger.debug("공동발의 테이블 조회 실패", exc_info=True)
        return False

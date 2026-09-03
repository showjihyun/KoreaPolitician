"""국회 발의법률안 수집기.

열린국회정보 OpenAPI 의 "국회의원 발의법률안"(nzmimeepazxkubdpn)에서 22대
법안을 받아 공동발의 그래프를 만든다.

왜 필요한지는 core/cosponsorship.py 의 설명을 본다. 요약하면, 뉴스는 갈등만
싣기 때문에 협력의 증거를 뉴스 밖에서 가져와야 한다.

API 키
-----
open.assembly.go.kr 에서 발급받아 환경변수로 넣는다. 키가 없으면 이
스크립트는 아무것도 하지 않고 안내만 남긴다. 수집 파이프라인 전체를
멈추지는 않는다.

    ASSEMBLY_API_KEY=...

실행
----
    ASSEMBLY_API_KEY=... POSTGRES_HOST=... PYTHONPATH=backend \\
        python backend/crawlers/assembly_bills_pipeline.py
    ... --age 22        수집할 국회 대수 (기본 22)
    ... --rebuild-only  이미 받아 둔 법안으로 쌍 집계만 다시 만든다
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from core import cosponsorship
from core.db_config import close_sync_pool, env

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

API_URL = "https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn"
SERVICE = "nzmimeepazxkubdpn"
PAGE_SIZE = 1000          # API 상한
DEFAULT_AGE = "22"

#: 응답 필드 -> 우리 컬럼
FIELD_MAP = {
    "BILL_ID": "bill_id",
    "BILL_NO": "bill_no",
    "BILL_NAME": "bill_name",
    "COMMITTEE": "committee",
    "PROPOSE_DT": "propose_dt",
    "PROC_RESULT": "proc_result",
    "AGE": "age",
    "RST_PROPOSER": "rst_proposer",
    "PUBL_PROPOSER": "publ_proposer",
    "DETAIL_LINK": "detail_link",
}


def load_members() -> List[str]:
    for path in ("data/assembly_members_complete.json",
                 "backend/data/assembly_members_complete.json",
                 "assembly_members_complete.json"):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                return [m["name"] for m in json.load(handle) if m.get("name")]
    raise RuntimeError("의원 명부를 찾지 못했습니다: assembly_members_complete.json")


def _rows_from(payload: Any) -> List[Dict[str, Any]]:
    """열린국회정보 응답 봉투에서 row 목록을 꺼낸다.

    형태가 두 가지다. 정상 응답은
        {"nzmimeepazxkubdpn": [{"head": [...]}, {"row": [...]}]}
    이고, 결과가 없거나 오류면
        {"RESULT": {"CODE": "INFO-200", "MESSAGE": "..."}}
    로 온다. 두 번째를 그냥 넘기면 조용히 0건이 되므로 구분해서 알린다.
    """
    if not isinstance(payload, dict):
        return []
    if "RESULT" in payload:
        result = payload["RESULT"] or {}
        code = result.get("CODE", "")
        if not str(code).startswith("INFO-000"):
            logger.warning("API 응답: %s %s", code, result.get("MESSAGE"))
        return []

    blocks = payload.get(SERVICE)
    if not isinstance(blocks, list):
        return []
    for block in blocks:
        if isinstance(block, dict) and "row" in block:
            return block["row"] or []
        if isinstance(block, dict) and "head" in block:
            for item in block["head"]:
                result = (item or {}).get("RESULT")
                if result and not str(result.get("CODE", "")).startswith("INFO-000"):
                    logger.warning("API 응답: %s %s",
                                   result.get("CODE"), result.get("MESSAGE"))
    return []


def fetch_bills(api_key: str, age: str = DEFAULT_AGE,
                max_pages: int = 100) -> List[Dict[str, Any]]:
    """법안을 페이지 단위로 받는다."""
    collected: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "KEY": api_key, "Type": "json",
            "pIndex": page, "pSize": PAGE_SIZE, "AGE": age,
        }
        try:
            response = requests.get(API_URL, params=params, timeout=60)
            response.raise_for_status()
            rows = _rows_from(response.json())
        except Exception as e:                            # noqa: BLE001
            logger.error("법안 조회 실패 (page %s): %s", page, e)
            break

        if not rows:
            break

        for row in rows:
            collected.append({our: row.get(theirs) for theirs, our in FIELD_MAP.items()})
        logger.info("page %s: %s건 (누적 %s건)", page, len(rows), len(collected))

        if len(rows) < PAGE_SIZE:
            break
        # 공개 API 예의. 초당 여러 번 두드리지 않는다.
        time.sleep(0.3)

    return collected


def run(age: str = DEFAULT_AGE, rebuild_only: bool = False) -> int:
    members = load_members()
    cosponsorship.ensure_schema()

    if not rebuild_only:
        api_key = env("ASSEMBLY_API_KEY")
        if not api_key:
            logger.warning("ASSEMBLY_API_KEY 가 없어 수집을 건너뜁니다.")
            logger.warning("https://open.assembly.go.kr 에서 키를 발급받아 넣으세요.")
            logger.warning("이미 받아 둔 법안으로 집계만 하려면 --rebuild-only 를 씁니다.")
            return 0

        bills = fetch_bills(api_key, age)
        if not bills:
            logger.error("받아 온 법안이 없습니다. 키와 대수를 확인하세요.")
            return 0
        saved = cosponsorship.save_bills(bills)
        logger.info("법안 %s건 저장", saved)

    pairs = cosponsorship.rebuild_pairs(members, age=age)
    logger.info("공동발의 쌍 %s개 집계", pairs)

    if pairs:
        top = cosponsorship.allies_of(members[0], min_bills=1, limit=3)
        logger.info("예: %s 의 공동발의 상위 %s", members[0], top)
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--age", default=DEFAULT_AGE, help="국회 대수 (기본 22)")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="수집 없이 저장된 법안으로 쌍 집계만 다시 만든다")
    args = parser.parse_args()

    try:
        run(age=args.age, rebuild_only=args.rebuild_only)
    finally:
        close_sync_pool()


if __name__ == "__main__":
    main()

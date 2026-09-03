"""공동발의 그래프 회귀 테스트.

뉴스는 갈등을 싣고 협력은 싣지 않는다. 공동발의는 그 공백을 메우는
자료이므로, 이름 정리와 쌍 집계가 정확해야 한다. 이름을 억지로 맞추면
없는 협력 관계가 생긴다.

    PYTHONPATH=backend pytest backend/tests/test_cosponsorship.py -v
"""

from core.cosponsorship import (count_pairs, normalize_proposer, pair_key,
                                parse_proposers)

MEMBERS = ["강경숙", "김승원", "나경원", "이재명", "정청래", "김윤덕", "김윤"]


# --- 이름 정리 --------------------------------------------------------------

def test_strips_titles_and_party():
    assert normalize_proposer("강경숙의원") == "강경숙"
    assert normalize_proposer("강경숙 의원") == "강경숙"
    assert normalize_proposer("나경원(국민의힘)") == "나경원"
    assert normalize_proposer("  이재명  ") == "이재명"
    assert normalize_proposer("정청래위원장") == "정청래"


def test_unknown_names_are_dropped():
    """전직 의원이나 정부 제출은 명부에 없다. 억지로 맞추지 않는다."""
    found = parse_proposers("홍길동", "임꺽정,강경숙", MEMBERS)
    assert found == ["강경숙"]


def test_lead_and_co_proposers_are_combined():
    found = parse_proposers("강경숙", "김승원,나경원,이재명", MEMBERS)
    assert found == ["강경숙", "김승원", "나경원", "이재명"]


def test_duplicate_names_are_counted_once():
    """대표발의자가 공동발의자 목록에도 들어 있는 경우가 있다."""
    found = parse_proposers("강경숙", "강경숙,김승원", MEMBERS)
    assert found == ["강경숙", "김승원"]


def test_semicolon_and_slash_separators():
    assert parse_proposers("강경숙", "김승원;나경원/이재명", MEMBERS) == [
        "강경숙", "김승원", "나경원", "이재명"]


def test_empty_inputs_are_safe():
    assert parse_proposers(None, None, MEMBERS) == []
    assert parse_proposers("", "", MEMBERS) == []


def test_shorter_name_is_not_matched_inside_a_longer_one():
    """'김윤덕' 이 '김윤' 으로 잡히면 없는 협력 관계가 생긴다."""
    # 대표발의자가 먼저 온다.
    found = parse_proposers("김윤덕", "강경숙", MEMBERS)
    assert found == ["김윤덕", "강경숙"]
    assert "김윤" not in found


# --- 쌍 집계 ---------------------------------------------------------------

def _bill(bill_id, rst, publ, date="20260901"):
    return {"bill_id": bill_id, "rst_proposer": rst,
            "publ_proposer": publ, "propose_dt": date}


def test_counts_every_pair_in_a_bill():
    bills = [_bill("B1", "강경숙", "김승원,나경원")]
    pairs = count_pairs(bills, MEMBERS)
    assert len(pairs) == 3            # 3명 -> 3쌍
    assert pairs[pair_key("강경숙", "김승원")]["bills"] == 1


def test_repeated_collaboration_accumulates():
    bills = [
        _bill("B1", "강경숙", "김승원", "20260901"),
        _bill("B2", "김승원", "강경숙", "20260903"),
        _bill("B3", "강경숙", "나경원", "20260902"),
    ]
    pairs = count_pairs(bills, MEMBERS)
    together = pairs[pair_key("강경숙", "김승원")]
    assert together["bills"] == 2
    assert together["first_date"] == "20260901"
    assert together["last_date"] == "20260903"


def test_pair_key_is_order_independent():
    bills = [_bill("B1", "김승원", "강경숙")]
    pairs = count_pairs(bills, MEMBERS)
    assert pair_key("강경숙", "김승원") in pairs
    assert pairs[pair_key("김승원", "강경숙")]["entity_a"] == "강경숙"


def test_solo_bills_make_no_pair():
    """혼자 낸 법안은 협력의 증거가 아니다."""
    assert count_pairs([_bill("B1", "강경숙", "")], MEMBERS) == {}
    assert count_pairs([_bill("B2", "강경숙", "홍길동")], MEMBERS) == {}


def test_unknown_proposers_do_not_create_pairs():
    bills = [_bill("B1", "홍길동", "임꺽정,장길산")]
    assert count_pairs(bills, MEMBERS) == {}

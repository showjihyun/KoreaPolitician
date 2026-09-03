"""손코딩 채점 도구 회귀 테스트.

Krippendorff's alpha 를 잘못 구현하면 신뢰도를 실제보다 높게 보고하게
된다. 갈등 라벨이 압도적으로 많은 우리 데이터에서는 단순 일치율이
부풀기 때문에, 이 보정이 정확해야 한다.

    PYTHONPATH=backend pytest backend/tests/test_coding_sample.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from coding_sample import krippendorff_alpha  # noqa: E402


def test_perfect_agreement_is_one():
    units = [("conflict", "conflict"), ("ally", "ally"), ("none", "none")] * 4
    assert krippendorff_alpha(units) == 1.0


def test_total_disagreement_is_negative():
    """서로 반대로 찍으면 우연보다도 못하다."""
    units = [("conflict", "ally"), ("ally", "conflict")] * 6
    alpha = krippendorff_alpha(units)
    assert alpha is not None and alpha < 0


def test_chance_agreement_is_near_zero():
    """한쪽으로 치우친 라벨에서 우연히 맞은 것은 걷어내야 한다.

    두 코더가 서로 무관하게 찍었는데 conflict 가 흔해서 자주 겹치는
    상황이다. 단순 일치율은 높게 나오지만 alpha 는 0 근처여야 한다.
    """
    units = ([("conflict", "conflict")] * 72
             + [("conflict", "ally")] * 8
             + [("ally", "conflict")] * 8
             + [("ally", "ally")] * 2)
    agreement = sum(1 for a, b in units if a == b) / len(units)
    alpha = krippendorff_alpha(units)

    assert agreement > 0.8, "단순 일치율은 높게 나오는 상황이어야 한다"
    assert alpha is not None
    assert alpha < 0.3, f"우연 일치를 못 걷어냈다: alpha={alpha}"


def test_good_agreement_lands_in_the_reportable_band():
    units = ([("conflict", "conflict")] * 40
             + [("ally", "ally")] * 30
             + [("none", "none")] * 20
             + [("conflict", "none")] * 5
             + [("ally", "conflict")] * 5)
    alpha = krippendorff_alpha(units)
    assert alpha is not None and 0.67 < alpha < 1.0


def test_single_coder_units_are_ignored():
    """한 사람만 코딩한 단위로는 일치를 잴 수 없다."""
    assert krippendorff_alpha([("conflict", "")]) is None
    assert krippendorff_alpha([]) is None
    mixed = [("conflict", "conflict"), ("ally", ""), ("none", "none")]
    assert krippendorff_alpha(mixed) == 1.0


def test_handles_more_than_two_coders():
    units = [("conflict", "conflict", "conflict"), ("ally", "ally", "conflict")]
    alpha = krippendorff_alpha(units)
    assert alpha is not None and 0 < alpha < 1

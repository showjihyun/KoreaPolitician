"""태도 추출기의 순수 함수 회귀 테스트.

모델을 띄우지 않고 도는 부분만 본다. 문장 분리·근거 분류·조사 처리가
깨지면 NLI 전제와 가설이 망가져 판정 전체가 흔들린다.

    PYTHONPATH=backend pytest backend/tests/test_affective_analysis.py -v
"""

from crawlers.affective_analysis import (EVIDENCE_DIRECT, EVIDENCE_INDIRECT,
                                         EVIDENCE_NARRATION, EVIDENCE_WEIGHT,
                                         STANCE_OPPOSE, STANCE_SUPPORT,
                                         classify_evidence, hypothesis,
                                         is_hedged, split_sentences)


# --- 문장 나누기 ------------------------------------------------------------

def test_splits_on_sentence_endings():
    text = "나경원 의원이 발언했다. 이재명 대표가 반박했다! 회의는 계속됐나?"
    assert len(split_sentences(text)) == 3


def test_does_not_split_inside_numbers():
    """예전에는 text.split('.') 이라 소수점에서 문장이 쪼개졌다."""
    text = "예산은 3.5% 늘었다. 야당은 반대했다."
    parts = split_sentences(text)
    assert len(parts) == 2
    assert "3.5%" in parts[0]


def test_splits_on_newlines():
    """네이버 본문 파서는 문단을 줄바꿈으로 넘긴다."""
    text = "첫 문단입니다\n두 번째 문단입니다\n세 번째 문단입니다"
    assert len(split_sentences(text)) == 3


def test_drops_tiny_fragments():
    assert split_sentences("가. 나. 정상적인 길이의 문장입니다.") == ["정상적인 길이의 문장입니다."]


def test_empty_text_is_safe():
    assert split_sentences("") == []
    assert split_sentences(None) == []


# --- 근거 분류 --------------------------------------------------------------

def test_direct_quote_is_recognised():
    sentence = '나경원 의원은 "국정을 볼모로 삼는 행태"라고 비판했다.'
    assert classify_evidence(sentence) == EVIDENCE_DIRECT


def test_curly_quotes_count_as_direct():
    sentence = '이재명 대표는 “터무니없다”고 반박했다.'
    assert classify_evidence(sentence) == EVIDENCE_DIRECT


def test_indirect_quote_is_recognised():
    sentence = "나 의원은 예산안 처리 지연의 책임이 야당에 있다고 주장했다."
    assert classify_evidence(sentence) == EVIDENCE_INDIRECT


def test_reporter_narration_is_the_fallback():
    """기자가 붙인 대립 구도는 정치인의 발언과 다른 정보다."""
    sentence = "두 사람은 지난해부터 사사건건 부딪쳐 왔다."
    assert classify_evidence(sentence) == EVIDENCE_NARRATION


def test_evidence_weights_are_ordered():
    assert (EVIDENCE_WEIGHT[EVIDENCE_DIRECT]
            > EVIDENCE_WEIGHT[EVIDENCE_INDIRECT]
            > EVIDENCE_WEIGHT[EVIDENCE_NARRATION])


# --- 헤지 ------------------------------------------------------------------

def test_hedges_are_detected():
    """추측성 서술은 확인된 사실과 같은 무게를 가질 수 없다."""
    assert is_hedged("갈등이 깊어질 것으로 보인다.")
    assert is_hedged("두 사람이 갈라섰다는 관측이 나온다.")
    assert is_hedged("연대 가능성이 거론된다.")
    assert is_hedged("결별했다는 분석이 나온다.")


def test_plain_statements_are_not_hedged():
    assert not is_hedged("나경원 의원은 이재명 대표를 비판했다.")
    assert not is_hedged('그는 "동의할 수 없다"고 말했다.')


# --- 가설 문장 --------------------------------------------------------------

def test_hypothesis_uses_correct_particles():
    """조사가 어긋나면 문장이 어색해져 NLI 점수가 흔들린다."""
    # 받침 있음 -> 은/을, 받침 없음 -> 는/를
    assert hypothesis("나경원", "이재명", STANCE_OPPOSE).startswith("나경원은 이재명을")
    assert hypothesis("이재명", "나경원", STANCE_OPPOSE).startswith("이재명은 나경원을")
    assert hypothesis("한동훈", "조국", STANCE_SUPPORT).startswith("한동훈은 조국을")
    assert hypothesis("김기현", "추미애", STANCE_OPPOSE).startswith("김기현은 추미애를")


def test_hypothesis_is_directional():
    """대칭 가설은 한쪽이 일방적으로 비판한 문장을 놓친다.

    실측: "나경원 의원은 이재명 대표를 겨냥해 비판했다" 에 대해
    대칭 가설 0.607(임계값 0.65 미만이라 버려짐), 방향형 0.956.
    """
    forward = hypothesis("나경원", "이재명", STANCE_OPPOSE)
    backward = hypothesis("이재명", "나경원", STANCE_OPPOSE)
    assert forward != backward


def test_stances_have_distinct_wording():
    oppose = hypothesis("나경원", "이재명", STANCE_OPPOSE)
    support = hypothesis("나경원", "이재명", STANCE_SUPPORT)
    assert "비판" in oppose and "지지" in support

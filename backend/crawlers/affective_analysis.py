"""두 정치인 사이의 태도를 뉴스 본문에서 뽑아낸다.

무엇이 바뀌었나 (2026-09-03)
----------------------------
예전에는 창 하나에 대칭 가설 두 개를 물었다.

    "이 문맥에서 {A}와 {B}는 서로 적대적이거나 비판적인 관계이다."

이 방식에는 두 가지 문제가 있었다.

1. **관계를 놓친다.** 위 가설은 *상호* 상태를 주장한다. 한쪽이 다른 쪽을
   비판하는 문장은 그 상호 상태를 함의하지 않으므로 점수가 낮게 나온다.
   실측: "나경원 의원은 이재명 대표를 겨냥해 비판했다" 라는 교과서적인
   갈등 문장에서 대칭 가설은 0.607 로 임계값 0.65 를 넘지 못해 버려졌다.
   같은 문장에 방향형 가설 "나경원은 이재명을 비판했다" 를 물으면 0.956,
   역방향 "이재명은 나경원을 비판했다" 는 0.093 이 나온다.

2. **방향을 못 만든다.** 대칭 가설은 누가 누구를 공격했는지 말하지 않는다.
   그래서 엣지의 source/target 이 이름 가나다순의 부산물이었다.

지금은 창마다 방향형 가설 네 개(A→B 반대/지지, B→A 반대/지지)를 묻고,
그 진술이 누구 입에서 나왔는지(직접 인용 / 간접 인용 / 기자 서술)를 함께
기록한다. 유재광·오경수(2012)가 보였듯 신문은 같은 정치인 발언을 자사
프레임에 맞춰 골라 싣는다. 정치인이 실제로 한 말과 기자가 붙인 대립
구도는 다른 정보이므로 분리해서 무게를 달리 준다.

Entman(1993)의 프레이밍, Recasens 외(2013)의 프레이밍/인식론적 편향
구분, Hamborg & Donnay(2021)의 표적별 감성 분류가 근거다. 자세한 내용은
docs/MEDIA_BIAS_RESEARCH.md 의 알고리즘 4.

한 기사가 창 여러 개를 만들 때, 예전에는 **최댓값 하나**를 기사 점수로
썼다. 긴 기사 어딘가의 자극적인 문장 하나가 기사 전체를 대표했다.
지금은 상위 세 창의 가중 평균을 쓴다.
"""

import logging
import os
import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

from core.name_matcher import find_names

logger = logging.getLogger(__name__)


# --- 태도와 근거 종류 -------------------------------------------------------

STANCE_SUPPORT = "support"
STANCE_OPPOSE = "oppose"

POSITIVE_SENTIMENT = "POSITIVE_SENTIMENT"
NEGATIVE_SENTIMENT = "NEGATIVE_SENTIMENT"

EVIDENCE_DIRECT = "direct_quote"        # 따옴표 + 발화 동사
EVIDENCE_INDIRECT = "indirect_quote"    # 발화 동사만
EVIDENCE_NARRATION = "reporter_narration"

#: 근거 종류별 무게. 정치인이 실제로 한 말이 기자의 서술보다 무겁다.
#:
#: 기자 서술을 아예 버리는 방안도 있으나(문서의 원안), 지금 수집량에서는
#: 관계 대부분이 사라진다. 0.3 으로 눌러 두고 evidence_type 을 관측에
#: 남겨, 언론사 논조 보정(알고리즘 1)이 서술만 따로 쓸 수 있게 한다.
#: RELATION_DROP_NARRATION=1 로 완전히 버릴 수 있다.
EVIDENCE_WEIGHT = {
    EVIDENCE_DIRECT: 1.0,
    EVIDENCE_INDIRECT: 0.7,
    EVIDENCE_NARRATION: 0.3,
}

DROP_NARRATION = os.environ.get("RELATION_DROP_NARRATION", "").strip() in ("1", "true", "True")

#: 추측성 서술은 절반으로 깎는다. Recasens 외(2013)의 헤지(hedge)에 해당한다.
HEDGE_FACTOR = 0.5

#: 기사 하나에서 창 몇 개를 평균낼지. 최댓값 하나를 쓰면 자극적인 문장
#: 하나가 기사를 대표한다.
TOP_WINDOWS = 3

#: 창 크기(앞뒤 문장 수). 한국어 기사는 첫 언급 뒤 "나 의원", "이 대표"
#: 로 줄여 쓰기 때문에 두 이름이 한 창에 함께 나오는 경우가 많지 않다.
#: 창을 넓히면 회수가 늘지만 무관한 문장이 전제에 섞인다.
WINDOW_RADIUS = int(os.environ.get("RELATION_WINDOW_RADIUS", "1"))

#: 함의 확률 하한.
THRESHOLD = float(os.environ.get("RELATION_NLI_THRESHOLD", "0.65"))

#: 방향을 인정하는 데 필요한 정방향-역방향 점수 차.
#: 갈등 문맥에서는 모델이 역방향 가설에도 후하게 답하므로 절대 점수로는
#: 방향을 가를 수 없다. 같은 창에서 두 방향을 물어 차이를 본다.
DIRECTION_MARGIN = float(os.environ.get("RELATION_DIRECTION_MARGIN", "0.10"))


# --- 문장 나누기 ------------------------------------------------------------

# 예전에는 text.split('.') 이었다. "3.5%" 나 "오후 2.30" 같은 숫자에서
# 문장이 쪼개졌고, 물음표와 느낌표는 문장 끝으로 치지 않았다.
# 마침표 뒤에 공백이나 줄바꿈이 오는 자리에서만 나눈다.
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?…])\s+|\n+')

#: 발화 동사. 이 진술이 정치인 입에서 나왔는지 판별한다.
_SPEECH_VERBS = (
    "말했다", "밝혔다", "주장했다", "강조했다", "지적했다", "비판했다",
    "반박했다", "촉구했다", "요구했다", "덧붙였다", "설명했다", "언급했다",
    "전했다", "답했다", "되받았다", "일축했다", "질타했다", "따졌다",
    "호소했다", "제안했다", "경고했다", "반발했다", "라고", "며", "면서",
)

#: 추측·전언 표지.
_HEDGES = (
    "것으로 보인다", "것으로 알려졌다", "알려졌다", "전망이다", "전망이 나온다",
    "관측된다", "관측이", "관측도", "해석된다", "풀이된다", "가능성",
    "듯하다", "인 셈", "라는 설", "것으로 전해졌다", "분석된다", "분석이 나온다",
)

_QUOTE_PAIRS = (('"', '"'), ('“', '”'), ("'", "'"), ("‘", "’"), ("「", "」"))


def split_sentences(text: str) -> List[str]:
    """본문을 문장으로 나눈다. 너무 짧은 조각은 버린다."""
    if not text:
        return []
    parts = _SENTENCE_BOUNDARY.split(text)
    return [p.strip() for p in parts if p and len(p.strip()) >= 5]


def classify_evidence(sentence: str) -> str:
    """이 문장이 누구의 진술인지 가른다."""
    has_speech = any(verb in sentence for verb in _SPEECH_VERBS)
    has_quote = any(
        open_q in sentence and close_q in sentence[sentence.find(open_q) + 1:]
        for open_q, close_q in _QUOTE_PAIRS
    )
    if has_quote and has_speech:
        return EVIDENCE_DIRECT
    if has_speech:
        return EVIDENCE_INDIRECT
    return EVIDENCE_NARRATION


def is_hedged(sentence: str) -> bool:
    return any(hedge in sentence for hedge in _HEDGES)


# --- 조사 붙이기 ------------------------------------------------------------

def _has_final_consonant(word: str) -> bool:
    if not word:
        return False
    ch = word[-1]
    if not ("가" <= ch <= "힣"):
        return False
    return (ord(ch) - 0xAC00) % 28 != 0


def _topic(word: str) -> str:
    """은/는. 가설 문장이 어색하면 NLI 점수가 흔들린다."""
    return word + ("은" if _has_final_consonant(word) else "는")


def _object(word: str) -> str:
    """을/를."""
    return word + ("을" if _has_final_consonant(word) else "를")


def hypothesis(holder: str, target: str, stance: str) -> str:
    if stance == STANCE_OPPOSE:
        return f"{_topic(holder)} {_object(target)} 비판하거나 공격했다."
    return f"{_topic(holder)} {_object(target)} 지지하거나 옹호했다."


class AffectiveAnalyzer:
    """뉴스 본문에서 정치인 사이의 태도를 뽑는다.

    Zero-Shot NLI 를 쓴다. 전제는 3문장 창, 가설은 방향을 가진 진술이다.
    """

    def __init__(self, model_name="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli", device=None):
        self.model_name = model_name
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info(f"[AffectiveAnalyzer] Loading model {model_name} on {self.device}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
            self.model.eval()
            # 라벨 순서를 모델 설정에서 확인한다. 예전에는 0번이 entailment
            # 라고 주석으로만 적어 두어, 모델이 순서를 바꾸면 판정이 조용히
            # 뒤집힐 수 있었다.
            self._entailment_index = self._find_entailment_index()
            logger.info("[AffectiveAnalyzer] Model loaded successfully. "
                        f"entailment index = {self._entailment_index}")
        except Exception as e:
            logger.error(f"[AffectiveAnalyzer] Model loading failed: {e}")
            raise e

    def _find_entailment_index(self) -> int:
        id2label = getattr(self.model.config, "id2label", None) or {}
        for index, label in id2label.items():
            if str(label).lower().startswith("entail"):
                return int(index)
        logger.warning("[AffectiveAnalyzer] id2label 에 entailment 가 없어 0번을 쓴다: %s",
                       id2label)
        return 0

    @lru_cache(maxsize=4096)
    def predict_nli(self, premise, hypothesis):
        """전제가 가설을 함의할 확률."""
        try:
            inputs = self.tokenizer(
                premise,
                hypothesis,
                return_tensors="pt",
                truncation=True,
                max_length=512
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=1)

            return probs[0][self._entailment_index].item()
        except Exception as e:
            logger.warning(f"[AffectiveAnalyzer] NLI prediction failed: {e}")
            return 0.0

    # --- 태도 추출 ----------------------------------------------------------

    def extract_stances(self, text: str, entity_a: str, entity_b: str,
                        candidates: Optional[Iterable[str]] = None) -> List[Dict]:
        """창마다 방향형 가설 네 개를 물어 통과한 태도를 모두 돌려준다.

        candidates 는 그 기사에 등장하는 이름 전체다. 창 안에서 이름을 다시
        확인할 때 필요하다. 예전에는 여기서 `entity_a in window` 단순
        부분일치를 썼는데, extract_politicians 가 막아 둔 김건/김건희 류의
        오탐이 이 단계에서 다시 들어올 수 있었다.
        """
        sentences = split_sentences(text)
        if not sentences:
            return []

        names = list(candidates) if candidates else [entity_a, entity_b]
        stances: List[Dict] = []

        for idx, sentence in enumerate(sentences):
            if entity_a not in sentence and entity_b not in sentence:
                continue

            start = max(0, idx - WINDOW_RADIUS)
            end = min(len(sentences), idx + WINDOW_RADIUS + 1)
            window = " ".join(sentences[start:end])

            present = set(find_names(window, names))
            if entity_a not in present or entity_b not in present:
                continue

            # 창 안에 두 사람만 있으면 창 전체를 근거로 삼는다. 한국어
            # 기사는 첫 언급 뒤 "나 의원", "이 대표" 로 줄여 쓰므로, 두 사람
            # 짜리 기사에서는 이렇게 해야 관계를 놓치지 않는다.
            #
            # 셋 이상이 섞여 있으면 같은 문장에 함께 나올 때만 인정한다.
            # 그렇게 하지 않으면 단순 공동 언급이 관계로 둔갑한다. 실측:
            # 의원 5명이 나오는 기사에서 창 기준은 관계 10개를 만들었는데
            # 그중 7개가 서로 아무 말도 하지 않은 쌍이었다. 같은 문장을
            # 요구하니 실제 관계 4개만 남았다.
            anchored = set(find_names(sentence, names)) >= {entity_a, entity_b}
            dyad = present == {entity_a, entity_b}
            if not (anchored or dyad):
                continue

            evidence_type = classify_evidence(sentence)
            if DROP_NARRATION and evidence_type == EVIDENCE_NARRATION:
                continue
            hedged = is_hedged(window)
            weight = EVIDENCE_WEIGHT[evidence_type] * (HEDGE_FACTOR if hedged else 1.0)

            for stance in (STANCE_OPPOSE, STANCE_SUPPORT):
                # 두 방향을 같은 창에서 나란히 물어 서로 비교한다.
                #
                # 절대 점수만 보면 방향을 못 가른다. 갈등을 다룬 전제에서는
                # 모델이 역방향 가설에도 후하게 답하기 때문이다. 실측: 나경원이
                # 이재명을 비판한 문장에서 정방향 0.996, 역방향 0.672 로 둘 다
                # 임계값을 넘었다. 차이를 보면 방향이 분명하다.
                forward = self.predict_nli(window, hypothesis(entity_a, entity_b, stance))
                backward = self.predict_nli(window, hypothesis(entity_b, entity_a, stance))
                score = max(forward, backward)
                if score <= THRESHOLD:
                    continue

                if forward - backward >= DIRECTION_MARGIN:
                    direction, holder, target = "a_to_b", entity_a, entity_b
                elif backward - forward >= DIRECTION_MARGIN:
                    direction, holder, target = "b_to_a", entity_b, entity_a
                else:
                    # 서로 주고받은 문장이거나 방향을 가릴 근거가 약하다.
                    direction, holder, target = "mutual", None, None

                stances.append({
                    "direction": direction,
                    "holder": holder,
                    "target": target,
                    "stance": stance,
                    "score": score,
                    "forward": forward,
                    "backward": backward,
                    "weight": weight,
                    "evidence": sentence,
                    "evidence_type": evidence_type,
                    "hedged": hedged,
                    "window": idx,
                })

        return stances

    def analyze_pair(self, text: str, entity_a: str, entity_b: str,
                     candidates: Optional[Iterable[str]] = None) -> Optional[Dict]:
        """기사 하나가 이 쌍에 대해 말하는 바를 한 건으로 요약한다.

        같은 극성의 태도들 중 상위 TOP_WINDOWS 개를 가중 평균한다.
        방향은 그 극성 안에서 어느 쪽이 우세한지로 정한다. 양쪽이
        비슷하면 mutual 로 두고 화살표를 그리지 않는다.
        """
        stances = self.extract_stances(text, entity_a, entity_b, candidates)
        if not stances:
            return None

        # 극성별 무게 합으로 기사의 극성을 정한다.
        def total(stance_name):
            return sum(s["score"] * s["weight"] for s in stances if s["stance"] == stance_name)

        oppose_total, support_total = total(STANCE_OPPOSE), total(STANCE_SUPPORT)
        stance = STANCE_OPPOSE if oppose_total >= support_total else STANCE_SUPPORT
        chosen = [s for s in stances if s["stance"] == stance]

        top = sorted(chosen, key=lambda s: s["score"] * s["weight"], reverse=True)[:TOP_WINDOWS]
        weight_sum = sum(s["weight"] for s in top) or 1.0
        score = sum(s["score"] * s["weight"] for s in top) / weight_sum

        # 방향은 창별 판정을 무게로 모아 정한다. 방향을 못 가른 창은
        # 어느 쪽에도 표를 주지 않는다.
        forward = sum(s["score"] * s["weight"] for s in chosen if s["direction"] == "a_to_b")
        backward = sum(s["score"] * s["weight"] for s in chosen if s["direction"] == "b_to_a")
        if forward > 0 and (backward <= 0 or forward > 2 * backward):
            direction, holder, target = "a_to_b", entity_a, entity_b
        elif backward > 0 and (forward <= 0 or backward > 2 * forward):
            direction, holder, target = "b_to_a", entity_b, entity_a
        else:
            # 양쪽이 서로를 공격하는 기사이거나, 방향을 가릴 근거가 약하다.
            direction, holder, target = "mutual", None, None

        best = top[0]
        return {
            "type": NEGATIVE_SENTIMENT if stance == STANCE_OPPOSE else POSITIVE_SENTIMENT,
            "stance": stance,
            "score": score,
            "evidence": best["evidence"],
            "evidence_type": best["evidence_type"],
            "hedged": best["hedged"],
            "stance_weight": weight_sum / len(top),
            "direction": direction,
            "holder": holder,
            "target": target,
            "n_windows": len({s["window"] for s in chosen}),
        }

    def analyze_relationship(self, text, entity_a, entity_b, candidates=None):
        """예전 호출부와 맞추기 위한 얇은 껍데기. (라벨, 점수, 근거)."""
        result = self.analyze_pair(text, entity_a, entity_b, candidates)
        if not result:
            return None, 0.0, ""
        return result["type"], result["score"], result["evidence"]

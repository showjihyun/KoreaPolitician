import torch
from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
import numpy as np
import pprint

# 1. 인물 정보 예시 (실제는 CSV/DB에서 불러올 수 있음)
people = [
    {"name": "이재명", "school": "서울대", "birthplace": "경기도", "family": ["이해찬"]},
    {"name": "김기현", "school": "서울대", "birthplace": "울산", "family": ["김철수"]},
    {"name": "이준석", "school": "하버드", "birthplace": "서울", "family": []},
    {"name": "이해찬", "school": "서울대", "birthplace": "경기도", "family": ["이재명"]},
]

def extract_relations(people):
    relations = []
    for i, p1 in enumerate(people):
        for j, p2 in enumerate(people):
            if i == j:
                continue
            # 학연
            if p1["school"] and p1["school"] == p2["school"]:
                relations.append({
                    "source": p1["name"],
                    "target": p2["name"],
                    "type": "학연",
                    "desc": f"{p1['school']} 동문",
                    "score": 0
                })
            # 지연
            if p1["birthplace"] and p1["birthplace"] == p2["birthplace"]:
                relations.append({
                    "source": p1["name"],
                    "target": p2["name"],
                    "type": "지연",
                    "desc": f"{p1['birthplace']} 출신",
                    "score": 0
                })
            # 혈연
            if p2["name"] in p1.get("family", []):
                relations.append({
                    "source": p1["name"],
                    "target": p2["name"],
                    "type": "혈연",
                    "desc": "가족",
                    "score": 0
                })
    return relations

# 2. 테스트할 감정분석 모델 리스트 (공개 HuggingFace 모델)
SENTIMENT_MODELS = [
    ("monologg/kobert", "KOBERT (사전학습, 감정분석 파인튜닝 아님)"),
    ("snunlp/KR-FinBert-SC", "KR-FinBERT (금융 특화)"),
]

# 3. 예시 발언 데이터 (실제는 기사/발언록 등에서 추출)
statements = [
    {"source": "이재명", "target": "김기현", "text": "김기현 의원은 정말 최악이다. 너무 싫다."},
    {"source": "김기현", "target": "이재명", "text": "이재명 의원은 정말 훌륭하다. 존경스럽다."},
    {"source": "이준석", "target": "이재명", "text": "이재명 의원은 별로다. 실망스럽다."},
    {"source": "이해찬", "target": "김기현", "text": "김기현 의원은 최고다. 멋지다."},
]

def kobert_sentiment(text, tokenizer, model, device):
    if tokenizer is None or model is None:
        return {"label": "neutral", "confidence": 1.0}
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=1).cpu().numpy()[0]
        label_id = np.argmax(probs)
        labels = [model.config.id2label[i] for i in range(len(model.config.id2label))]
        return {
            "label": labels[label_id],
            "confidence": float(probs[label_id])
        }

def sentiment_to_score(label, confidence):
    if label == "positive":
        return int(50 + 50 * confidence)
    elif label == "negative":
        return int(-50 * confidence)
    else:
        return 0

# 2. KOBERT 임베딩 추출 예시 (감정분석 분류 아님)
def kobert_embedding_example():
    print("\n[KOBERT 임베딩 추출 예시]")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained("monologg/kobert", trust_remote_code=True)
    model = AutoModel.from_pretrained("monologg/kobert", trust_remote_code=True)
    model.to(device)
    text = "이재명 의원은 정말 훌륭하다. 존경스럽다."
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
        last_hidden = outputs.last_hidden_state
        pooled = last_hidden.mean(dim=1).squeeze().cpu().numpy()
    print("문장 임베딩 shape:", pooled.shape)
    print("임베딩 벡터(앞 10개):", pooled[:10])

if __name__ == "__main__":
    relations = extract_relations(people)
    kobert_embedding_example()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_results = []
    for model_name, model_desc in SENTIMENT_MODELS:
        print(f"\n=== 모델: {model_desc} ({model_name}) ===")
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
            model.to(device)
            print("라벨 매핑:", model.config.id2label)
        except Exception as e:
            print(f"모델 로딩 실패: {e}")
            continue
        label_counts = {"positive": 0, "negative": 0, "neutral": 0}
        model_relations = []
        for stmt in statements:
            result = kobert_sentiment(stmt["text"], tokenizer, model, device)
            score = sentiment_to_score(result["label"], result["confidence"])
            label_counts[result["label"]] = label_counts.get(result["label"], 0) + 1
            model_relations.append({
                "source": stmt["source"],
                "target": stmt["target"],
                "type": "감정",
                "desc": stmt["text"],
                "score": score,
                "sentiment_label": result["label"],
                "sentiment_confidence": result["confidence"]
            })
        print("분류 결과 요약:", label_counts)
        pprint.pprint(model_relations)
        model_results.append((model_desc, label_counts, model_relations))
    # 가장 긍정/부정 분류가 많은 모델 찾기
    best_model = max(model_results, key=lambda x: x[1]["positive"] + x[1]["negative"] if x[1]["positive"]+x[1]["negative"]>0 else -1)
    print("\n=== 가장 의미있는 분류를 보인 모델 ===")
    print(f"모델: {best_model[0]}")
    print(f"긍정: {best_model[1]['positive']} / 부정: {best_model[1]['negative']} / 중립: {best_model[1]['neutral']}")
    pprint.pprint(best_model[2])

    # 4. (선택) Cypher 쿼리 예시 출력
    def relation_to_cypher(rel):
        return (
            f"MATCH (a:Person {{name: '{rel['source']}'}}), (b:Person {{name: '{rel['target']}'}}) "
            f"MERGE (a)-[r:{rel['type']} {{desc: '{rel['desc']}', score: {rel['score']}}}]->(b);"
        )
    print("\n[Cypher 쿼리 예시]")
    for rel in relations:
        print(relation_to_cypher(rel)) 
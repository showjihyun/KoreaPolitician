import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import logging
import traceback
from functools import lru_cache

logger = logging.getLogger(__name__)

class AffectiveAnalyzer:
    """
    Web-Text Based Inter-Object Favorability & Negativity Algorithm (WIOFNA)
    Uses Zero-Shot NLI to determine the affective relationship between two entities.
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
            logger.info("[AffectiveAnalyzer] Model loaded successfully.")
        except Exception as e:
            logger.error(f"[AffectiveAnalyzer] Model loading failed: {e}")
            raise e

    @lru_cache(maxsize=2048)
    def predict_nli(self, premise, hypothesis):
        """
        Predicts entailment score for a premise-hypothesis pair.
        Returns the probability of 'entailment'.
        """
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
                logits = outputs.logits
                probs = torch.softmax(logits, dim=1)
                
            # MoritzLaurer/mDeBERTa-v3-base-mnli-xnli label mapping:
            # 0: entailment, 1: neutral, 2: contradiction
            # Verify via model config usually, but this is standard for this model.
            
            entailment_score = probs[0][0].item() # Probability of entailment
            return entailment_score
        except Exception as e:
            logger.warning(f"[AffectiveAnalyzer] NLI prediction failed: {e}")
            return 0.0

    def analyze_relationship(self, text, entity_a, entity_b):
        """
        Analyzes the relationship between entity_a and entity_b based on the text.
        Returns a tuple: (relationship_type, score, evidence_sentence)
        relationship_type: 'POSITIVE_SENTIMENT', 'NEGATIVE_SENTIMENT', or None
        """
        # 1. Preprocessing: Split into sentences (simple split for now)
        sentences = text.split('.') 
        target_sentences = []
        for sent in sentences:
            if entity_a in sent and entity_b in sent:
                target_sentences.append(sent.strip())
        
        if not target_sentences:
            return None, 0.0, ""

        # 2. Zero-Shot Classification per sentence
        best_score = 0.0
        best_label = None
        best_evidence = ""

        for sent in target_sentences:
            # Hypotheses
            # H1: Positive/Friendly
            h_positive = f"{entity_a}와 {entity_b}는 서로 우호적인 관계이다."
            # H2: Negative/Hostile
            h_negative = f"{entity_a}와 {entity_b}는 서로 적대적인 관계이다."
            
            score_pos = self.predict_nli(sent, h_positive)
            score_neg = self.predict_nli(sent, h_negative)
            
            # Thresholding
            threshold = 0.7 # Minimum confidence
            
            if score_pos > score_neg and score_pos > threshold:
                if score_pos > best_score:
                    best_score = score_pos
                    best_label = "POSITIVE_SENTIMENT"
                    best_evidence = sent
            elif score_neg > score_pos and score_neg > threshold:
                if score_neg > best_score:
                    best_score = score_neg
                    best_label = "NEGATIVE_SENTIMENT"
                    best_evidence = sent
                    
        return best_label, best_score, best_evidence

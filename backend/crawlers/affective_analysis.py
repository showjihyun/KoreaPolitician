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
        Uses a sliding window of 3 sentences to resolve zero-anaphora and context.
        """
        # 1. Preprocessing: Split into sentences
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        
        # 2. Identify target indices where at least one entity is mentioned
        target_indices = []
        for i, sent in enumerate(sentences):
            if entity_a in sent or entity_b in sent:
                target_indices.append(i)
        
        if not target_indices:
            return None, 0.0, ""

        best_score = 0.0
        best_label = None
        best_evidence = ""

        # 3. Process each target index with a context window
        # We look for relationships specifically where BOTH are contextually present
        # but one might be referred to by a pronoun or omitted in the current sentence.
        for idx in target_indices:
            # Context window: Previous, current, next
            start = max(0, idx - 1)
            end = min(len(sentences), idx + 2)
            context_window = ". ".join(sentences[start:end]) + "."
            
            # Check if both are present in the *window*
            if entity_a not in context_window or entity_b not in context_window:
                continue

            # Hypotheses (using the full window as premise)
            h_positive = f"이 문맥에서 {entity_a}와 {entity_b}는 서로 우호적이거나 협력적인 관계이다."
            h_negative = f"이 문맥에서 {entity_a}와 {entity_b}는 서로 적대적이거나 비판적인 관계이다."
            
            score_pos = self.predict_nli(context_window, h_positive)
            score_neg = self.predict_nli(context_window, h_negative)
            
            threshold = 0.65 # Minimum confidence
            
            if score_pos > score_neg and score_pos > threshold:
                if score_pos > best_score:
                    best_score = score_pos
                    best_label = "POSITIVE_SENTIMENT"
                    best_evidence = sentences[idx] # Current sentence is the main evidence
            elif score_neg > score_pos and score_neg > threshold:
                if score_neg > best_score:
                    best_score = score_neg
                    best_label = "NEGATIVE_SENTIMENT"
                    best_evidence = sentences[idx]
                    
        return best_label, best_score, best_evidence

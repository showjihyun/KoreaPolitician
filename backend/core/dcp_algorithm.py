import requests
import logging

logger = logging.getLogger(__name__)

class DCPCalculator:
    """
    Dynamic Contextual Propagation (DCP) Calculator.
    Calculates the 'Social Impact Score' by considering the resonance 
    with the subject's allies.
    """
    def __init__(self, api_base_url="http://localhost:5000", alpha=0.3):
        self.api_base_url = api_base_url
        self.alpha = alpha

    def calculate_impact_score(self, subject, target, current_sentiment, base_intensity):
        """
        Calculates the social impact score.
        Formula: final_score = (1 - alpha) * base_intensity + (alpha * resonance_score)
        """
        try:
            # 1. Fetch Context (Allies and their relationship to target)
            response = requests.get(
                f"{self.api_base_url}/api/dcp/context",
                params={"subject": subject, "target": target},
                timeout=5
            )
            
            if response.status_code != 200:
                logger.warning(f"[DCP] Failed to fetch context for {subject}->{target}")
                return base_intensity

            data = response.json()
            allies_context = data.get("allies_context", [])
            
            # 2. Calculate Resonance
            # We average the intensity of allies who share the same sentiment.
            # This prevents the score from exploding with too many allies.
            shared_sentiment_weights = []
            
            for item in allies_context:
                ally_relation = item.get("relation")
                weight = item.get("weight", 0.0)
                
                # Resonance occurs if Ally has the SAME sentiment towards the Target
                if ally_relation == current_sentiment:
                    shared_sentiment_weights.append(weight)
            
            resonance_score = 0.0
            if shared_sentiment_weights:
                # Average weight of resonating allies
                avg_weight = sum(shared_sentiment_weights) / len(shared_sentiment_weights)
                # Apply a slight boost for consensus volume (logarithmic)
                volume_bonus = 0.1 * (len(shared_sentiment_weights) ** 0.5)
                resonance_score = avg_weight + volume_bonus
                
            # 3. Apply Paper Formula
            final_score = (1 - self.alpha) * base_intensity + (self.alpha * resonance_score)
            
            # 4. Clamping and Normalization
            # Final score should be at least 0.1 but can go above 1.0 for visualization emphasis
            # However, for consistency with sentiment scores, we clamp to 1.5 max for "Heavy" links.
            return max(0.1, min(final_score, 1.5))

        except Exception as e:
            logger.error(f"[DCP] Error calculating score: {e}")
            return base_intensity

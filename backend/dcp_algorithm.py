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
        
        Args:
            subject (str): Name of the politician making the statement (or source).
            target (str): Name of the target politician.
            current_sentiment (str): 'POSITIVE_SENTIMENT' or 'NEGATIVE_SENTIMENT'.
            base_intensity (float): The sentiment score from the text (0.0 to 1.0).
            
        Returns:
            float: Adjusted Social Impact Score.
        """
        try:
            # 1. Fetch Context (Allies and their relationship to target)
            response = requests.get(
                f"{self.api_base_url}/api/dcp/context",
                params={"subject": subject, "target": target}
            )
            
            if response.status_code != 200:
                logger.warning(f"[DCP] Failed to fetch context for {subject}->{target}")
                return base_intensity

            data = response.json()
            allies_context = data.get("allies_context", [])
            
            # 2. Calculate Resonance
            resonance_score = 0.0
            total_weight = 0.0
            
            for item in allies_context:
                # item: { "ally": "name", "relation": "POSITIVE_SENTIMENT", "weight": 0.8 }
                ally_relation = item.get("relation")
                weight = item.get("weight", 0.0)
                
                # Resonance occurs if Ally has the SAME sentiment towards the Target
                if ally_relation == current_sentiment:
                    resonance_score += weight
                    total_weight += 1 # Simply count for now, or use complex weighting
            
            # Normalize resonance (if needed, or just let it amplify)
            # Paper Formula: final = (1-a)*base + a*resonance
            # But resonance can be > 1 if many allies agree? 
            # Let's assume resonance is average intensity of allies * support factor?
            # The simplified code in appendix: resonance_score += history['weight']
            # And final = (1-alpha)*base + alpha * resonance.
            # If resonance is sum, it could explode. Let's average it or clamp it.
            
            if total_weight > 0:
                 avg_resonance = resonance_score / total_weight
                 # Amplify by number of allies? 
                 # Let's follow the spirit: Resonance amplifies.
                 # Let's use the sum but clamp it to 1.0 logic from appendix might imply normalized weights.
                 # Let's use the appendix code logic:
                 # resonance_score += history['weight'] (assuming weight is 0-1)
                 # final = ...
                 # return min(final, 1.0)
                 pass
            else:
                avg_resonance = 0.0
                resonance_score = 0.0

            # Actually, let's use the accumulated resonance but cap at some reasonable boost
            # If 5 allies agree, it should be very strong.
            
            final_score = (1 - self.alpha) * base_intensity + (self.alpha * resonance_score)
            
            # Clamp to 1.0? Or allow > 1.0 for visualization thickness?
            # Paper says "social impact score" -> visualization width.
            # Let's allow it to go higher than 1.0 for "thick" edges, but maybe cap at 5.0
            
            return max(0.1, final_score) # Return at least small positive

        except Exception as e:
            logger.error(f"[DCP] Error calculating score: {e}")
            return base_intensity

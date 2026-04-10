"""
Market Movement Layer
=====================
Tracks odds changes, detects anomalies, and extracts market signals.
Supports: The Odds API (sports), Polymarket API (prediction markets).
"""
import re
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class MarketService:
    """
    Parses odds inputs and computes implied probabilities.
    Can be extended to fetch live odds from market APIs.
    """

    def parse_odds(self, odds_string: str) -> Optional[float]:
        """
        Convert various odds formats to implied probability.

        Supported formats:
        - Decimal: "1.80", "2.50"
        - American: "-150", "+200", "ML -110"
        - Fractional: "4/5", "7/2"
        - Percentage: "62%", "0.62"
        """
        if not odds_string:
            return None

        s = odds_string.strip()

        # Percentage / decimal 0-1
        if s.endswith("%"):
            try:
                return float(s[:-1]) / 100.0
            except ValueError:
                pass

        try:
            val = float(s)
            if 0.0 < val <= 1.0:
                return val  # Already a probability
            if val > 1.0:
                return self._decimal_to_prob(val)  # Decimal odds
        except ValueError:
            pass

        # American odds: -150, +200
        american_match = re.search(r"([+-]\d+)", s)
        if american_match:
            return self._american_to_prob(int(american_match.group(1)))

        # Fractional: 4/5, 7/2
        frac_match = re.match(r"(\d+)/(\d+)", s)
        if frac_match:
            num, den = int(frac_match.group(1)), int(frac_match.group(2))
            return den / (num + den)

        return None

    @staticmethod
    def _decimal_to_prob(decimal_odds: float) -> float:
        """Convert decimal odds to implied probability."""
        if decimal_odds <= 1.0:
            return 1.0
        return 1.0 / decimal_odds

    @staticmethod
    def _american_to_prob(american_odds: int) -> float:
        """Convert American moneyline odds to implied probability."""
        if american_odds > 0:
            return 100.0 / (american_odds + 100.0)
        else:
            return abs(american_odds) / (abs(american_odds) + 100.0)

    def assess_market_signal(
        self,
        initial_odds: Optional[str],
        current_odds: Optional[str],
    ) -> float:
        """
        Compute market signal from odds movement.
        Returns: -1.0 (strong bearish) to +1.0 (strong bullish)
        """
        if not initial_odds or not current_odds:
            return 0.0

        initial_prob = self.parse_odds(initial_odds)
        current_prob = self.parse_odds(current_odds)

        if initial_prob is None or current_prob is None:
            return 0.0

        # Positive movement = odds moving in favor of the bet
        movement = current_prob - initial_prob
        # Normalize to [-1, 1]
        return max(-1.0, min(1.0, movement * 10))

    def format_odds_display(self, probability: float) -> Dict[str, str]:
        """Format a probability as multiple odds representations."""
        if probability <= 0 or probability >= 1:
            return {"decimal": "N/A", "american": "N/A", "implied": f"{probability:.0%}"}

        decimal = 1.0 / probability
        american = (
            f"+{int((1/probability - 1) * 100)}"
            if probability < 0.5
            else f"-{int(probability / (1 - probability) * 100)}"
        )

        return {
            "decimal": f"{decimal:.2f}",
            "american": american,
            "implied": f"{probability:.1%}",
            "fractional": self._prob_to_fractional(probability),
        }

    @staticmethod
    def _prob_to_fractional(prob: float) -> str:
        """Approximate probability as a simple fraction string."""
        for num, den in [
            (1, 10), (1, 5), (1, 4), (1, 3), (2, 5), (1, 2),
            (3, 5), (2, 3), (3, 4), (4, 5), (9, 10)
        ]:
            if abs(num / (num + den) - prob) < 0.03:
                return f"{num}/{den}"
        return f"{prob:.0%}"


# Singleton
_market_service: Optional[MarketService] = None


def get_market_service() -> MarketService:
    global _market_service
    if _market_service is None:
        _market_service = MarketService()
    return _market_service

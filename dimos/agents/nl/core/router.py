"""Intent Router for the NL System.

Routes natural language input to the best matching parser based on
confidence scores and handles ambiguity resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from dimos.agents.nl.core.protocols import (
    IntentParser,
    ParseResult,
    RoutingDecision,
)
from dimos.agents.nl.core.registry import PluginRegistry

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class RouterConfig:
    """Configuration for IntentRouter.
    
    Attributes:
        min_confidence: Minimum confidence to consider a match valid
        ambiguity_threshold: Confidence difference threshold for ambiguity warning
        max_alternatives: Number of alternative parsers to include in decision
        enable_fallback: Whether to use fallback parser when no match
        fallback_parser_name: Name of parser to use as fallback
    """
    min_confidence: float = 0.5
    ambiguity_threshold: float = 0.15  # Top 2 within 0.15 = ambiguous
    max_alternatives: int = 2
    enable_fallback: bool = False
    fallback_parser_name: str | None = None


class AmbiguityError(Exception):
    """Raised when input is ambiguous between multiple parsers."""
    
    def __init__(
        self,
        message: str,
        alternatives: list[tuple[str, float, dict]],
    ):
        super().__init__(message)
        self.alternatives = alternatives


class IntentRouter:
    """Routes NL input to the best matching parser.
    
    The router:
    1. Queries all registered parsers
    2. Collects successful results with confidence > min_confidence
    3. Sorts by confidence (descending)
    4. Checks for ambiguity (top 2 too close)
    5. Returns RoutingDecision with best match + alternatives
    
    Example:
        router = IntentRouter(registry)
        decision = router.route("向后移动1米")
        
        if decision:
            print(f"Matched: {decision.intent_type}")
            print(f"Confidence: {decision.confidence}")
    """
    
    def __init__(
        self,
        registry: PluginRegistry[IntentParser],
        config: RouterConfig | None = None,
        disambiguator: Callable[[list[tuple[str, float, dict]], str], int] | None = None,
    ):
        """Initialize router.
        
        Args:
            registry: Parser registry to query
            config: Router configuration
            disambiguator: Optional callback for ambiguity resolution.
                Receives (alternatives, text) and returns index of chosen alternative.
        """
        self._registry = registry
        self._config = config or RouterConfig()
        self._disambiguator = disambiguator
    
    def route(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> RoutingDecision | None:
        """Route text to best matching parser.
        
        Args:
            text: User input text
            context: Optional context for disambiguation
        
        Returns:
            RoutingDecision with best match, or None if no match.
        
        Raises:
            AmbiguityError: If input is ambiguous and no disambiguator provided.
        """
        if not text or not text.strip():
            logger.debug("Empty text input")
            return None
        
        # Collect results from all parsers
        results = self._collect_results(text, context)
        
        if not results:
            logger.debug(f"No parser matched: {text[:50]}...")
            return None
        
        # Sort by confidence (descending)
        results.sort(key=lambda x: -x[2])  # (name, result, confidence)
        
        # Check for ambiguity
        if len(results) >= 2:
            best_name, best_result, best_conf = results[0]
            second_name, second_result, second_conf = results[1]
            
            conf_diff = best_conf - second_conf
            
            if conf_diff < self._config.ambiguity_threshold:
                # Ambiguous - attempt disambiguation
                logger.info(
                    f"Ambiguous input '{text[:50]}...': "
                    f"{best_name}({best_conf:.2f}) vs "
                    f"{second_name}({second_conf:.2f})"
                )
                
                if self._disambiguator:
                    chosen_idx = self._disambiguator(results[:2], text)
                    if chosen_idx == 1:
                        # Use second best
                        results[0], results[1] = results[1], results[0]
                        logger.debug(f"Disambiguator chose: {results[0][0]}")
                else:
                    # Could raise AmbiguityError, but we'll return best with warning
                    pass
        
        # Build decision
        best_name, best_result, best_conf = results[0]
        
        # Collect alternatives for debugging
        alternatives = [
            (name, conf)
            for name, _, conf in results[1 : 1 + self._config.max_alternatives]
        ]
        
        decision = RoutingDecision(
            parser_name=best_name,
            intent_type=best_result.intent_type,
            slots=dict(best_result.slots),  # Copy slots
            confidence=best_conf,
            alternatives=alternatives,
        )
        
        logger.debug(
            f"Routed to {decision.parser_name} "
            f"(intent={decision.intent_type}, conf={decision.confidence:.2f})"
        )
        
        return decision
    
    def route_all(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[tuple[str, ParseResult, float]]:
        """Route and return all matching results (for debugging/analysis).
        
        Returns:
            List of (parser_name, result, confidence) sorted by confidence.
        """
        return self._collect_results(text, context)
    
    def _collect_results(
        self,
        text: str,
        context: dict[str, Any] | None,
    ) -> list[tuple[str, ParseResult, float]]:
        """Collect results from all parsers above min_confidence."""
        results = []
        
        for entry in self._registry.list_all():
            try:
                result = entry.plugin.parse(text, context)
                
                if result.success and result.confidence >= self._config.min_confidence:
                    results.append((entry.name, result, result.confidence))
                
            except Exception as e:
                # Log but don't crash - other parsers may succeed
                logger.warning(
                    f"Parser {entry.name} failed for '{text[:50]}...': {e}",
                    exc_info=True,
                )
        
        return results
    
    def get_parser_for_intent(self, intent_type: str) -> IntentParser | None:
        """Get parser that handles specific intent type.
        
        Returns highest priority parser for the intent type.
        """
        entries = self._registry.list_by_intent_type(intent_type)
        return entries[0].plugin if entries else None

    def get_parser_for_intent_type(self, intent_type: str) -> IntentParser | None:
        """Return the highest-priority parser for an intent type.

        This method keeps the public name aligned with ``RoutingDecision`` and
        the NL tests while delegating to the shorter existing helper.
        """
        return self.get_parser_for_intent(intent_type)


# Simple disambiguators

@dataclass
class ContextDisambiguator:
    """Disambiguator that uses context to choose between alternatives.
    
    Example:
        disambiguator = ContextDisambiguator({
            "current_location": "workspace_A",
        })
        router = IntentRouter(registry, disambiguator=disambiguator.choose)
    """
    context_keys: dict[str, Any] = field(default_factory=dict)
    
    def choose(
        self,
        alternatives: list[tuple[str, ParseResult, float]],
        text: str,
    ) -> int:
        """Choose between alternatives based on context.
        
        Returns:
            Index (0 or 1) of chosen alternative.
        """
        # Default: choose first (highest confidence)
        if len(alternatives) < 2:
            return 0
        
        # Could implement sophisticated logic here:
        # - Prefer parsers matching current location
        # - Prefer parsers matching previous intent
        # - Prefer parsers with required slots present
        
        return 0


class ThresholdDisambiguator:
    """Always choose highest confidence unless difference is very small."""
    
    def __init__(self, force_second_threshold: float = 0.05):
        self.force_second_threshold = force_second_threshold
    
    def choose(
        self,
        alternatives: list[tuple[str, ParseResult, float]],
        text: str,
    ) -> int:
        if len(alternatives) < 2:
            return 0
        
        _, _, conf0 = alternatives[0]
        _, _, conf1 = alternatives[1]
        
        # If virtually tied, might need clarification
        if abs(conf0 - conf1) < self.force_second_threshold:
            logger.warning(f"Nearly tied confidences: {conf0:.3f} vs {conf1:.3f}")
        
        return 0

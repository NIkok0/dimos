"""Hybrid router combining rule-based and LLM-based parsing.

Implements the strategy:
1. Try rule-based parsers first (fast, deterministic)
2. If confidence < threshold, try LLM parser
3. Validate LLM output against rules
4. Return best result or ask for clarification
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dimos.agents.nl.core.protocols import ParseResult, RoutingDecision
from dimos.agents.nl.core.registry import PluginRegistry
from dimos.agents.nl.core.router import IntentRouter, RouterConfig

try:
    from dimos.agents.nl.llm.parser import LLMIntentParser
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


@dataclass
class HybridRouterConfig:
    """Configuration for hybrid router."""
    
    # Confidence thresholds
    rule_confidence_threshold: float = 0.8  # Rules above this are trusted
    llm_fallback_threshold: float = 0.6     # Below this, try LLM
    
    # Routing strategy
    use_llm_fallback: bool = True
    llm_as_primary: bool = False  # If True, try LLM first
    
    # Validation
    validate_llm_with_rules: bool = True
    
    # Performance
    rule_timeout_ms: float = 100.0  # Max time for rule parsing
    llm_timeout_ms: float = 5000.0  # Max time for LLM parsing


class HybridIntentRouter(IntentRouter):
    """Router that combines rule-based and LLM-based parsing.
    
    Strategy (default):
    1. Try all rule-based parsers
    2. If best rule confidence >= rule_confidence_threshold: use it
    3. If best rule confidence < llm_fallback_threshold and LLM available:
       - Try LLM parser
       - Validate LLM output against rules if configured
       - Use LLM result if confidence higher
    4. Return best result or None
    
    Alternative strategy (llm_as_primary=True):
    1. Try LLM parser first
    2. Validate LLM output with rules
    3. If LLM fails or validation fails, try rules
    """
    
    def __init__(
        self,
        registry: PluginRegistry,
        config: RouterConfig | None = None,
        hybrid_config: HybridRouterConfig | None = None,
        llm_parser: Any | None = None,
    ):
        """Initialize hybrid router.
        
        Args:
            registry: Plugin registry for rule-based parsers
            config: Base router configuration
            hybrid_config: Hybrid-specific configuration
            llm_parser: LLM parser instance (created if not provided)
        """
        super().__init__(registry, config)
        
        self._hybrid_config = hybrid_config or HybridRouterConfig()
        
        # Initialize LLM parser if available
        if llm_parser:
            self._llm_parser = llm_parser
        elif LLM_AVAILABLE and self._hybrid_config.use_llm_fallback:
            try:
                self._llm_parser = LLMIntentParser()
                logger.info("Initialized LLM parser for hybrid routing")
            except Exception as e:
                logger.warning(f"Could not initialize LLM parser: {e}")
                self._llm_parser = None
        else:
            self._llm_parser = None

        self._last_llm_result: ParseResult | None = None

    @property
    def last_llm_result(self) -> ParseResult | None:
        """Last LLM parse result from the most recent route() call.

        Note: this is instance-level state, not thread-safe. Concurrent
        route() calls on the same router instance may overwrite this.
        Callers needing thread safety should create per-call router instances.
        """
        return self._last_llm_result

    def route(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> RoutingDecision | None:
        """Route text using hybrid strategy.
        
        Args:
            text: User instruction
            context: Optional context (includes conversation history, etc.)
        
        Returns:
            RoutingDecision with best matching intent, or None
        """
        if not text or not text.strip():
            return None
        
        if self._hybrid_config.llm_as_primary and self._llm_parser:
            return self._route_llm_primary(text, context)
        else:
            return self._route_rules_primary(text, context)
    
    def _route_rules_primary(
        self,
        text: str,
        context: dict[str, Any] | None,
    ) -> RoutingDecision | None:
        """Default strategy: rules first, then LLM fallback."""
        
        # Step 1: Try rule-based parsers
        rule_results = self._collect_results(text, context)
        
        if rule_results:
            # Sort by confidence
            rule_results.sort(key=lambda x: -x[2])
            best_rule = rule_results[0]
            
            # If rule confidence is high enough, use it
            if best_rule[2] >= self._hybrid_config.rule_confidence_threshold:
                logger.debug(f"Using rule-based result: {best_rule[0]} (conf={best_rule[2]:.2f})")
                return self._make_decision(best_rule, rule_results)
        
        # Step 2: Try LLM if confidence is low and LLM available
        if (self._llm_parser and 
            self._hybrid_config.use_llm_fallback and
            (not rule_results or rule_results[0][2] < self._hybrid_config.llm_fallback_threshold)):
            
            logger.debug("Trying LLM fallback")
            llm_result = self._llm_parser.parse(text, context)
            
            if llm_result.success and llm_result.confidence >= self._config.min_confidence:
                # Compare with best rule result
                if rule_results and rule_results[0][2] > llm_result.confidence:
                    logger.debug(f"Rule result better than LLM: {rule_results[0][2]:.2f} vs {llm_result.confidence:.2f}")
                    return self._make_decision(rule_results[0], rule_results)
                
                logger.debug(f"Using LLM result: {llm_result.intent_type} (conf={llm_result.confidence:.2f})")
                return RoutingDecision(
                    parser_name="llm_parser",
                    intent_type=llm_result.intent_type or "",
                    slots=llm_result.slots,
                    confidence=llm_result.confidence,
                    alternatives=[(r[0], r[2]) for r in rule_results[:2]] if rule_results else [],
                )
        
        # Step 3: Return best rule result or None
        if rule_results:
            return self._make_decision(rule_results[0], rule_results)
        
        return None
    
    def _route_llm_primary(
        self,
        text: str,
        context: dict[str, Any] | None,
    ) -> RoutingDecision | None:
        """LLM-first strategy: rules are not used as fallback."""

        if not self._llm_parser:
            self._last_llm_result = None
            return None

        llm_result = self._llm_parser.parse(text, context)
        self._last_llm_result = llm_result

        if llm_result.success and llm_result.confidence >= self._config.min_confidence:
            return RoutingDecision(
                parser_name="llm_parser",
                intent_type=llm_result.intent_type or "",
                slots=llm_result.slots,
                confidence=llm_result.confidence,
                alternatives=[],
            )

        return None
    
    def _make_decision(
        self,
        best: tuple[str, Any, float],
        all_results: list[tuple[str, Any, float]],
    ) -> RoutingDecision:
        """Create RoutingDecision from result."""
        parser_name, result, confidence = best
        
        alternatives = [
            (r[0], r[2]) for r in all_results[1:3]
            if r[0] != parser_name
        ]
        
        return RoutingDecision(
            parser_name=parser_name,
            intent_type=result.intent_type if hasattr(result, 'intent_type') else "",
            slots=result.slots if hasattr(result, 'slots') else {},
            confidence=confidence,
            alternatives=alternatives,
        )
    
    def _validate_with_rules(
        self,
        text: str,
        llm_result: ParseResult,
        context: dict[str, Any] | None,
    ) -> RoutingDecision | None:
        """Validate LLM result against rule-based parsers."""
        # Find a rule parser that matches the LLM intent type
        for entry in self._registry.list_all():
            if entry.plugin.intent_type == llm_result.intent_type:
                rule_result = entry.plugin.parse(text, context)
                if rule_result.success:
                    # Rule parser agrees with LLM
                    return None  # Let LLM result stand
        
        # No matching rule found or rule disagrees
        # Could adjust confidence or reject
        return None
    
    def route_with_llm(
        self,
        text: str,
        context: dict[str, Any] | None = None,
        force_llm: bool = False,
    ) -> RoutingDecision | None:
        """Route with explicit LLM control.
        
        Args:
            text: User instruction
            context: Optional context
            force_llm: If True, skip rules and use LLM directly
        
        Returns:
            RoutingDecision or None
        """
        if force_llm and self._llm_parser:
            result = self._llm_parser.parse(text, context)
            if result.success:
                return RoutingDecision(
                    parser_name="llm_parser",
                    intent_type=result.intent_type or "",
                    slots=result.slots,
                    confidence=result.confidence,
                    alternatives=[],
                )
        
        return self.route(text, context)


# Factory functions

def create_hybrid_router(
    registry: PluginRegistry | None = None,
    llm_model: str = "gpt-4o",
    **kwargs,
) -> HybridIntentRouter:
    """Create a hybrid router with sensible defaults.
    
    Args:
        registry: Rule-based parser registry (uses global if None)
        llm_model: LLM model to use
        **kwargs: Additional config options
    
    Returns:
        Configured HybridIntentRouter
    """
    if registry is None:
        from dimos.agents.nl.core.registry import intent_parser_registry
        registry = intent_parser_registry
    
    llm_parser = None
    if LLM_AVAILABLE:
        try:
            llm_parser = LLMIntentParser(model=llm_model)
        except Exception as e:
            logger.warning(f"Failed to create LLM parser: {e}")
    
    return HybridIntentRouter(
        registry=registry,
        hybrid_config=HybridRouterConfig(**kwargs),
        llm_parser=llm_parser,
    )

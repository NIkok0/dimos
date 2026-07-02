"""Core protocols for the NL System.

Defines the contracts that all NL components must implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ParseResult:
    """Result of natural language parsing.
    
    Attributes:
        success: Whether parsing succeeded
        intent_type: The type of intent identified (e.g., "move_relative")
        slots: Extracted slot values for the intent
        confidence: Confidence score (0.0-1.0), used for routing decisions
        error_code: Error code if parsing failed (e.g., "NO_MATCH", "LOW_CONFIDENCE")
    """
    success: bool
    intent_type: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    error_code: str | None = None
    
    def __post_init__(self) -> None:
        if self.success and (self.intent_type is None or self.confidence <= 0):
            raise ValueError("Successful parse must have intent_type and positive confidence")


@dataclass(frozen=True)
class RoutingDecision:
    """Final routing decision from IntentRouter.
    
    Attributes:
        parser_name: Name of the selected parser
        intent_type: The resolved intent type
        slots: Final slot values after any post-processing
        confidence: Final confidence score
        alternatives: Top alternative (parser_name, confidence) pairs for debugging
    """
    parser_name: str
    intent_type: str
    slots: dict[str, Any]
    confidence: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)


@runtime_checkable
class IntentParser(Protocol):
    """Protocol for natural language intent parsers.
    
    All intent parsers must implement this protocol to be registered
    in the ParserRegistry and used by the IntentRouter.
    
    Example:
        class RelativeMoveParser:
            @property
            def intent_type(self) -> str:
                return "move_relative"
            
            def parse(self, text: str, context: dict | None = None) -> ParseResult:
                # Implementation here
                ...
    """
    
    @property
    def intent_type(self) -> str:
        """Return the intent type this parser handles.
        
        Must be unique across all registered parsers.
        """
        ...
    
    def parse(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> ParseResult:
        """Attempt to parse text into an intent.
        
        Args:
            text: Raw user input (may contain Chinese, English, etc.)
            context: Optional context for disambiguation:
                - request_id: Unique request identifier
                - current_location: Current robot pose
                - previous_intent: Previous intent for multi-turn
                - session_history: Recent conversation history
        
        Returns:
            ParseResult with success/failure status and extracted slots.
            If parsing fails, return ParseResult(success=False, error_code=...)
        """
        ...
    
    def get_supported_slots(self) -> list[str]:
        """Return list of slot names this parser can extract.
        
        Used for validation and documentation generation.
        Example: ["direction", "distance_units"]
        """
        ...


@runtime_checkable
class SlotExtractor(Protocol):
    """Protocol for slot value extractors.
    
    Extractors are reusable components that extract specific slot types
    (e.g., distance, direction, colors) from text.
    """
    
    @property
    def slot_name(self) -> str:
        """Name of the slot this extractor produces."""
        ...
    
    @property
    def slot_type(self) -> type:
        """Python type of the extracted value."""
        ...
    
    def extract(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        """Attempt to extract slot value from text.
        
        Returns:
            (success, value) tuple. If success is False, value is None.
        """
        ...


@runtime_checkable  
class ActionComposer(Protocol):
    """Protocol for composing ActionPlans from parsed intents.
    
    ActionComposers transform intent slots into executable ActionPlans
    that the ActionPlanOrchestrator can execute.
    """
    
    @property
    def intent_type(self) -> str:
        """Intent type this composer handles."""
        ...
    
    @property
    def template_name(self) -> str:
        """Template name for logging/debugging."""
        ...
    
    def compose(
        self,
        slots: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any:  # Returns ActionPlan
        """Compose an ActionPlan from intent slots.
        
        Args:
            slots: Extracted slot values from parser
            context: Optional composition context
        
        Returns:
            ActionPlan ready for execution
        """
        ...

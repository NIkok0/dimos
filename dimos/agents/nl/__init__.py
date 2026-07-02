"""Natural Language System for DimOS.

A plugin-based, configuration-driven natural language understanding system.

Key components:
- Core: Protocols, registries, and routing
- Extractors: Reusable slot value extractors
- LLM: LLM-based intent parser + catalog validator
- Task: NL intent bridge + TaskRouter

Example:
    from dimos.agents.nl import (
        IntentRouter,
        intent_parser_registry,
        ParseResult,
    )

    # Route NL input
    router = IntentRouter(intent_parser_registry)
    decision = router.route("向后移动1米")

    if decision:
        print(f"Intent: {decision.intent_type}")
        print(f"Slots: {decision.slots}")
"""

from dimos.agents.nl.core import (
    # Protocols
    IntentParser,
    ActionComposer,
    SlotExtractor,
    ParseResult,
    RoutingDecision,
    # Registry
    PluginRegistry,
    PluginEntry,
    PluginMetadata,
    intent_parser_registry,
    action_composer_registry,
    get_intent_parser_registry,
    get_action_composer_registry,
    register_intent_parser,
    register_action_composer,
    # Router
    IntentRouter,
    RouterConfig,
    AmbiguityError,
    ContextDisambiguator,
    ThresholdDisambiguator,
)

__all__ = [
    # Core exports
    "IntentParser",
    "ActionComposer",
    "SlotExtractor",
    "ParseResult",
    "RoutingDecision",
    "PluginRegistry",
    "PluginEntry",
    "PluginMetadata",
    "intent_parser_registry",
    "action_composer_registry",
    "get_intent_parser_registry",
    "get_action_composer_registry",
    "register_intent_parser",
    "register_action_composer",
    "IntentRouter",
    "RouterConfig",
    "AmbiguityError",
    "ContextDisambiguator",
    "ThresholdDisambiguator",
]

"""Core components of the NL System.

This module provides the foundational abstractions for natural language
understanding in DimOS, including:

- Protocols: Contracts for parsers, extractors, and composers
- Registry: Plugin registration and discovery
- Router: Confidence-based intent routing
- Config: Hot-reload configuration loading

Example usage:
    from dimos.agents.nl.core import (
        IntentParser,
        ParseResult,
        intent_parser_registry,
        IntentRouter,
        ConfigLoader,
    )
    
    # Register a parser
    intent_parser_registry.register("my_parser", MyParser(), priority=100)
    
    # Route input
    router = IntentRouter(intent_parser_registry)
    decision = router.route("向后移动1米")
"""

from dimos.agents.nl.core.protocols import (
    IntentParser,
    ActionComposer,
    SlotExtractor,
    ParseResult,
    RoutingDecision,
)

from dimos.agents.nl.core.registry import (
    PluginRegistry,
    PluginEntry,
    PluginMetadata,
    intent_parser_registry,
    action_composer_registry,
    get_intent_parser_registry,
    get_action_composer_registry,
    register_intent_parser,
    register_action_composer,
)

from dimos.agents.nl.core.router import (
    IntentRouter,
    RouterConfig,
    AmbiguityError,
    ContextDisambiguator,
    ThresholdDisambiguator,
)

from dimos.agents.nl.core.config_loader import (
    ConfigLoader,
    ConfigReloadCallback,
    get_config_loader,
)

__all__ = [
    # Protocols
    "IntentParser",
    "ActionComposer",
    "SlotExtractor",
    "ParseResult",
    "RoutingDecision",
    # Registry
    "PluginRegistry",
    "PluginEntry",
    "PluginMetadata",
    "intent_parser_registry",
    "action_composer_registry",
    "get_intent_parser_registry",
    "get_action_composer_registry",
    "register_intent_parser",
    "register_action_composer",
    # Router
    "IntentRouter",
    "RouterConfig",
    "AmbiguityError",
    "ContextDisambiguator",
    "ThresholdDisambiguator",
    # Config
    "ConfigLoader",
    "ConfigReloadCallback",
    "get_config_loader",
]

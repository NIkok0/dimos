"""Plugin registries for the NL System.

Provides generic plugin registration with priority-based resolution.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable, Generic, TypeVar

from dimos.agents.nl.core.protocols import IntentParser, ActionComposer

from dimos.utils.logging_config import setup_logger

logger = setup_logger()

T = TypeVar("T")


class PluginMetadata:
    """Metadata for a registered plugin."""
    
    def __init__(
        self,
        priority: int = 0,
        version: str = "1.0.0",
        description: str = "",
        author: str = "",
        tags: list[str] | None = None,
    ):
        self.priority = priority
        self.version = version
        self.description = description
        self.author = author
        self.tags = tags or []


class PluginEntry(Generic[T]):
    """A registered plugin entry with metadata."""
    
    def __init__(
        self,
        name: str,
        plugin: T,
        metadata: PluginMetadata,
    ):
        self.name = name
        self.plugin = plugin
        self.metadata = metadata


class PluginRegistry(Generic[T]):
    """Generic plugin registry with priority-based resolution.
    
    Supports:
    - Priority-based ordering (higher = tried first)
    - Auto-discovery from packages
    - Version tracking
    - Metadata tagging
    
    Example:
        registry = PluginRegistry[IntentParser]()
        registry.register("relative_move", RelativeMoveParser(), priority=100)
        
        # Iterate in priority order
        for entry in registry.list_all():
            result = entry.plugin.parse(text)
            ...
    """
    
    def __init__(self, name: str = "PluginRegistry"):
        self._name = name
        self._plugins: dict[str, PluginEntry[T]] = {}
        self._cache: list[PluginEntry[T]] | None = None  # Sorted cache
    
    def register(
        self,
        name: str,
        plugin: T,
        priority: int = 0,
        version: str = "1.0.0",
        description: str = "",
        author: str = "",
        tags: list[str] | None = None,
        force: bool = False,
    ) -> None:
        """Register a plugin.
        
        Args:
            name: Unique plugin identifier
            plugin: The plugin instance
            priority: Priority for ordering (higher = first)
            version: Plugin version string
            description: Human-readable description
            author: Plugin author/team
            tags: Optional tags for filtering
            force: Overwrite existing registration
        
        Raises:
            ValueError: If name already registered and force=False
        """
        if name in self._plugins and not force:
            raise ValueError(
                f"Plugin '{name}' already registered. "
                f"Use force=True to overwrite."
            )
        
        metadata = PluginMetadata(
            priority=priority,
            version=version,
            description=description,
            author=author,
            tags=tags or [],
        )
        
        self._plugins[name] = PluginEntry(name, plugin, metadata)
        self._cache = None  # Invalidate cache
        
        logger.debug(
            f"Registered {self._name} plugin: {name} "
            f"(priority={priority}, version={version})"
        )
    
    def unregister(self, name: str) -> bool:
        """Unregister a plugin.
        
        Returns:
            True if plugin was removed, False if not found.
        """
        if name in self._plugins:
            del self._plugins[name]
            self._cache = None
            logger.debug(f"Unregistered {self._name} plugin: {name}")
            return True
        return False
    
    def get(self, name: str) -> T | None:
        """Get plugin by name.
        
        Returns:
            The plugin instance, or None if not found.
        """
        entry = self._plugins.get(name)
        return entry.plugin if entry else None
    
    def get_entry(self, name: str) -> PluginEntry[T] | None:
        """Get full plugin entry including metadata."""
        return self._plugins.get(name)
    
    def list_all(self) -> list[PluginEntry[T]]:
        """List all plugins sorted by priority (descending).
        
        Returns:
            List of PluginEntry, sorted by priority (highest first).
            Plugins with same priority are sorted by registration order.
        """
        if self._cache is None:
            entries = list(self._plugins.values())
            # Sort by priority (desc), then by name for stability
            entries.sort(key=lambda e: (-e.metadata.priority, e.name))
            self._cache = entries
        return self._cache
    
    def list_by_tag(self, tag: str) -> list[PluginEntry[T]]:
        """List plugins with specific tag."""
        return [
            entry for entry in self.list_all()
            if tag in entry.metadata.tags
        ]
    
    def list_by_intent_type(self, intent_type: str) -> list[PluginEntry[T]]:
        """List plugins that handle a specific intent type.
        
        Only works for IntentParser and ActionComposer registries.
        """
        results = []
        for entry in self.list_all():
            plugin = entry.plugin
            if hasattr(plugin, 'intent_type') and plugin.intent_type == intent_type:
                results.append(entry)
        return results
    
    def update_priority(self, name: str, new_priority: int) -> bool:
        """Update priority of a registered plugin.
        
        Returns:
            True if updated, False if plugin not found.
        """
        entry = self._plugins.get(name)
        if entry is None:
            return False
        
        # Create new entry with updated priority
        new_metadata = PluginMetadata(
            priority=new_priority,
            version=entry.metadata.version,
            description=entry.metadata.description,
            author=entry.metadata.author,
            tags=entry.metadata.tags,
        )
        self._plugins[name] = PluginEntry(name, entry.plugin, new_metadata)
        self._cache = None  # Invalidate cache
        return True
    
    def clear(self) -> None:
        """Remove all registered plugins."""
        self._plugins.clear()
        self._cache = None
        logger.debug(f"Cleared all {self._name} plugins")
    
    def auto_discover(
        self,
        package_path: str,
        register_func_name: str = "register_parser",
    ) -> int:
        """Auto-discover plugins from a package.
        
        Scans subpackages and calls their register function.
        
        Args:
            package_path: Python package path (e.g., "dimos.agents.nl.parsers")
            register_func_name: Name of the register function to call
        
        Returns:
            Number of plugins successfully registered.
        
        Example package structure:
            parsers/
                relative_move/
                    __init__.py  # contains register_parser()
        """
        count = 0
        try:
            package = importlib.import_module(package_path)
        except ImportError as e:
            logger.warning(f"Could not import package {package_path}: {e}")
            return 0
        
        for _, name, is_pkg in pkgutil.iter_modules(package.__path__):
            if not is_pkg:
                continue  # Only look at subpackages
            
            full_name = f"{package_path}.{name}"
            try:
                module = importlib.import_module(full_name)
                register_func = getattr(module, register_func_name, None)
                
                if register_func is not None:
                    register_func(self)
                    count += 1
                    logger.debug(f"Auto-discovered plugin from {full_name}")
                else:
                    logger.warning(
                        f"Module {full_name} has no {register_func_name}()"
                    )
            except Exception as e:
                logger.warning(f"Failed to load plugin from {full_name}: {e}")
        
        logger.info(f"Auto-discovered {count} plugins from {package_path}")
        return count
    
    def __len__(self) -> int:
        return len(self._plugins)
    
    def __contains__(self, name: str) -> bool:
        return name in self._plugins
    
    def __iter__(self):
        """Iterate over plugin entries in priority order."""
        return iter(self.list_all())


# Global registries for the NL System

#: Global registry for IntentParser plugins
intent_parser_registry: PluginRegistry[IntentParser] = PluginRegistry(
    name="IntentParser"
)

#: Global registry for ActionComposer plugins  
action_composer_registry: PluginRegistry[ActionComposer] = PluginRegistry(
    name="ActionComposer"
)


def get_intent_parser_registry() -> PluginRegistry[IntentParser]:
    """Get the global intent parser registry."""
    return intent_parser_registry


def get_action_composer_registry() -> PluginRegistry[ActionComposer]:
    """Get the global action composer registry."""
    return action_composer_registry


def register_intent_parser(
    name: str,
    parser: IntentParser,
    priority: int = 0,
    **metadata,
) -> None:
    """Convenience function to register an intent parser."""
    intent_parser_registry.register(name, parser, priority=priority, **metadata)


def register_action_composer(
    name: str,
    composer: ActionComposer,
    priority: int = 0,
    **metadata,
) -> None:
    """Convenience function to register an action composer."""
    action_composer_registry.register(name, composer, priority=priority, **metadata)

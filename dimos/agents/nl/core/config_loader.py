"""Configuration loader with hot-reload support.

Provides YAML/JSON configuration loading with file watching for hot updates.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

# Try to import yaml, provide fallback if not available
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class ConfigReloadCallback(Protocol):
    """Protocol for configuration reload callbacks."""
    
    def __call__(self, config: dict[str, Any], source: str) -> None:
        ...


@dataclass
class ConfigWatchEntry:
    """Entry for a watched configuration file."""
    path: Path
    last_modified: float
    last_hash: str
    callbacks: list[ConfigReloadCallback] = field(default_factory=list)
    config_type: str = "yaml"  # yaml, json, or python


class ConfigLoader:
    """Configuration loader with hot-reload support.
    
    Usage:
        loader = ConfigLoader()
        
        # Load once
        config = loader.load("config/nl/relative_move.yaml")
        
        # Watch for changes
        loader.watch("config/nl/relative_move.yaml", on_reload)
        
        # Start watching (in background thread)
        loader.start_watching(interval=5.0)
    """
    
    def __init__(
        self,
        base_path: str | Path | None = None,
        default_format: str = "yaml",
    ):
        """Initialize config loader.
        
        Args:
            base_path: Base directory for relative paths
            default_format: Default format for config files (yaml/json)
        """
        self._base_path = Path(base_path) if base_path else Path.cwd()
        self._default_format = default_format
        self._watched: dict[str, ConfigWatchEntry] = {}
        self._watch_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
    
    def load(
        self,
        path: str | Path,
        config_type: str | None = None,
    ) -> dict[str, Any]:
        """Load configuration from file.
        
        Args:
            path: Path to config file (relative to base_path or absolute)
            config_type: Config type override (yaml/json/python)
        
        Returns:
            Configuration as dictionary
        
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If format is unsupported
        """
        full_path = self._resolve_path(path)
        
        if not full_path.exists():
            raise FileNotFoundError(f"Config file not found: {full_path}")
        
        # Determine type from extension if not specified
        if config_type is None:
            ext = full_path.suffix.lower()
            if ext in (".yaml", ".yml"):
                config_type = "yaml"
            elif ext == ".json":
                config_type = "json"
            elif ext == ".py":
                config_type = "python"
            else:
                config_type = self._default_format
        
        # Load based on type
        if config_type in ("yaml", "yml"):
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML required for YAML config loading")
            with open(full_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        
        elif config_type == "json":
            with open(full_path, "r", encoding="utf-8") as f:
                return json.load(f)
        
        elif config_type == "python":
            # Import Python module and extract config dict
            import importlib.util
            spec = importlib.util.spec_from_file_location("config", full_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load Python config: {full_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # Look for common config variable names
            for name in ["CONFIG", "config", "PATTERNS", "patterns"]:
                if hasattr(module, name):
                    value = getattr(module, name)
                    if isinstance(value, dict):
                        return value
            return {}
        
        else:
            raise ValueError(f"Unsupported config type: {config_type}")
    
    def watch(
        self,
        path: str | Path,
        callback: ConfigReloadCallback,
        config_type: str | None = None,
    ) -> None:
        """Watch a configuration file for changes.
        
        Args:
            path: Path to config file
            callback: Function to call when config changes
            config_type: Optional config type override
        """
        full_path = self._resolve_path(path)
        path_key = str(full_path)
        
        with self._lock:
            if path_key in self._watched:
                # Add callback to existing watch
                self._watched[path_key].callbacks.append(callback)
            else:
                # Create new watch entry
                stat = full_path.stat()
                entry = ConfigWatchEntry(
                    path=full_path,
                    last_modified=stat.st_mtime,
                    last_hash=self._compute_hash(full_path),
                    callbacks=[callback],
                    config_type=config_type or self._detect_type(full_path),
                )
                self._watched[path_key] = entry
        
        logger.info(f"Watching config file: {full_path}")
    
    def unwatch(self, path: str | Path, callback: ConfigReloadCallback | None = None) -> bool:
        """Stop watching a configuration file.
        
        Args:
            path: Path to config file
            callback: Specific callback to remove, or None for all
        
        Returns:
            True if anything was removed
        """
        full_path = self._resolve_path(path)
        path_key = str(full_path)
        
        with self._lock:
            if path_key not in self._watched:
                return False
            
            entry = self._watched[path_key]
            
            if callback is None:
                # Remove all watches for this file
                del self._watched[path_key]
                return True
            
            # Remove specific callback
            if callback in entry.callbacks:
                entry.callbacks.remove(callback)
                if not entry.callbacks:
                    del self._watched[path_key]
                return True
            
            return False
    
    def start_watching(self, interval: float = 5.0) -> None:
        """Start background thread to watch for config changes.
        
        Args:
            interval: Check interval in seconds
        """
        if self._watch_thread is not None and self._watch_thread.is_alive():
            logger.warning("Config watcher already running")
            return
        
        self._stop_event.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            args=(interval,),
            daemon=True,
            name="ConfigWatcher",
        )
        self._watch_thread.start()
        logger.info(f"Started config watcher (interval={interval}s)")
    
    def stop_watching(self, wait: bool = True, timeout: float = 5.0) -> None:
        """Stop background watching thread.
        
        Args:
            wait: Whether to wait for thread to finish
            timeout: Max time to wait
        """
        if self._watch_thread is None or not self._watch_thread.is_alive():
            return
        
        self._stop_event.set()
        
        if wait:
            self._watch_thread.join(timeout=timeout)
        
        self._watch_thread = None
        logger.info("Stopped config watcher")
    
    def check_all(self) -> list[tuple[str, dict[str, Any]]]:
        """Check all watched files for changes.
        
        Returns:
            List of (path, new_config) for files that changed
        """
        changed = []
        
        with self._lock:
            for path_key, entry in self._watched.items():
                if not entry.path.exists():
                    continue
                
                stat = entry.path.stat()
                current_hash = self._compute_hash(entry.path)
                
                # Check mtime first (fast), then hash (accurate)
                if stat.st_mtime != entry.last_modified or current_hash != entry.last_hash:
                    try:
                        new_config = self.load(entry.path, entry.config_type)
                        changed.append((path_key, new_config))
                        
                        # Update entry
                        entry.last_modified = stat.st_mtime
                        entry.last_hash = current_hash
                        
                        # Notify callbacks
                        for callback in entry.callbacks:
                            try:
                                callback(new_config, path_key)
                            except Exception as e:
                                logger.error(f"Config reload callback failed: {e}")
                    
                    except Exception as e:
                        logger.error(f"Failed to reload config {entry.path}: {e}")
        
        return changed
    
    def _watch_loop(self, interval: float) -> None:
        """Background thread loop for watching."""
        while not self._stop_event.is_set():
            try:
                self.check_all()
            except Exception as e:
                logger.error(f"Error in config watch loop: {e}")
            
            # Wait for interval or stop signal
            self._stop_event.wait(interval)
    
    def _resolve_path(self, path: str | Path) -> Path:
        """Resolve path relative to base_path if not absolute."""
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        return self._base_path / path_obj
    
    def _detect_type(self, path: Path) -> str:
        """Detect config type from file extension."""
        ext = path.suffix.lower()
        if ext in (".yaml", ".yml"):
            return "yaml"
        elif ext == ".json":
            return "json"
        elif ext == ".py":
            return "python"
        return self._default_format
    
    def _compute_hash(self, path: Path) -> str:
        """Compute simple hash of file contents."""
        import hashlib
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:16]


# Global config loader instance
_global_loader: ConfigLoader | None = None


def get_config_loader(base_path: str | Path | None = None) -> ConfigLoader:
    """Get or create global config loader instance."""
    global _global_loader
    if _global_loader is None:
        _global_loader = ConfigLoader(base_path=base_path)
    return _global_loader

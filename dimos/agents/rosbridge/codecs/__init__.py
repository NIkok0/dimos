"""DimOS-specific ROS interface codecs used through py_rosbridge.

This package mirrors ``py_rosbridge.codecs`` for robot-local interface packages:
generated dataclasses live in per-interface modules, while this package-level
registry gives callers one place to merge codec metadata for custom messages.
"""

from dimos.agents.rosbridge.codecs import dax_dimos_interfaces
from dimos.agents.rosbridge.codecs import robot_interfaces

TYPE_REGISTRY = {
    **dax_dimos_interfaces.TYPE_REGISTRY,
    **robot_interfaces.TYPE_REGISTRY,
}

for _codec in TYPE_REGISTRY.values():
    _codec.type_registry = TYPE_REGISTRY

__all__ = [
    "TYPE_REGISTRY",
    "dax_dimos_interfaces",
    "robot_interfaces",
]

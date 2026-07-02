# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared py_rosbridge QoS profiles for Dax navigation topics."""

from py_rosbridge.client import Qos, QosDurability, QosHistory, QosReliability

MAP_TOPIC_QOS = Qos(
    history=QosHistory.KEEP_LAST,
    depth=1,
    reliability=QosReliability.RELIABLE,
    durability=QosDurability.TRANSIENT_LOCAL,
)

SLAM_STATUS_TOPIC_QOS = Qos(
    history=QosHistory.KEEP_LAST,
    depth=1,
    reliability=QosReliability.BEST_EFFORT,
    durability=QosDurability.VOLATILE,
)

NAV_STATUS_TOPIC_QOS = Qos(
    history=QosHistory.KEEP_LAST,
    depth=1,
    reliability=QosReliability.BEST_EFFORT,
    durability=QosDurability.VOLATILE,
)

__all__ = [
    "MAP_TOPIC_QOS",
    "NAV_STATUS_TOPIC_QOS",
    "SLAM_STATUS_TOPIC_QOS",
]

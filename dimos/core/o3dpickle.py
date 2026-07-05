# Copyright 2025-2026 Dimensional Inc.
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

from __future__ import annotations

import copyreg
from typing import Any


def reduce_external(obj: Any) -> tuple[Any, tuple[Any, ...]]:  # type: ignore[no-untyped-def]
    import numpy as np

    points_array = np.asarray(obj.points)
    return (reconstruct_pointcloud, (points_array,))


def reconstruct_pointcloud(points_array: Any) -> Any:  # type: ignore[no-untyped-def]
    import open3d as o3d

    pc = o3d.geometry.PointCloud()
    pc.points = o3d.utility.Vector3dVector(points_array)
    return pc


def register_picklers() -> None:
    """Register open3d PointCloud picklers when open3d is installed.

    dax-agent minimal deploy omits open3d; skip registration in that case.
    """
    try:
        import open3d as o3d
    except ImportError:
        return

    _dummy_pc = o3d.geometry.PointCloud()
    copyreg.pickle(_dummy_pc.__class__, reduce_external)

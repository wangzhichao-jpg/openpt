# SPDX-License-Identifier: Apache-2.0
"""核心计算的具名结果结构及兼容映射接口。"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, fields
from typing import Any


@dataclass
class ResultMapping(Mapping[str, Any]):
    """提供字段映射和用于序列化的显式转换。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可用于 JSON 输出的字段字典。"""
        return {f.metadata.get("key", f.name): getattr(self, f.name) for f in fields(self)}

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(fields(self))


@dataclass
class HomogeneityResult(ResultMapping):
    """GL003 4.2、4.3 的平衡设计结果。"""

    status: str
    design_status: str
    design_warnings: list[str]
    warnings: list[str]
    g: int
    m: int
    means: list[float]
    mean: float
    SS_between: float
    SS_within: float
    df_between: int
    df_within: int
    MS_between: float
    MS_within: float
    F: float | None
    F_critical: float
    p: float | None
    variance_raw: float
    Ss: float
    sigma: float | None
    threshold: float | None
    F_pass: bool | None
    Ss_pass: bool | None
    Ss_status: str
    strict: bool
    conclusion: bool | None


@dataclass
class AlgorithmAResult(ResultMapping):
    """GL002 附录 A.2 的稳健统计结果。"""

    x: float
    s: float
    u_x: float
    n: int
    iterations: int
    converged: bool
    status: str
    warning: str | None
    simplified: bool
    rule: str
    tolerance: float
    history: list[dict[str, Any]]


@dataclass
class MedianIqrResult(ResultMapping):
    """GL002 附录 A.4 的中位数及标准化四分位距。"""

    median: float
    q1: float
    q3: float
    iqr: float
    niqr: float
    status: str


@dataclass
class ZScoreResult(ResultMapping):
    """GL002 4.4 和 4.5 的比分数结果。"""

    z: float
    status: str
    classification: str


@dataclass
class StabilityResult(ResultMapping):
    """GL003 5.2 和 5.3 的稳定性计算结果。"""

    t: float | None = None
    df: float | None = None
    p: float | None = None
    critical: float | None = None
    passed: bool | None = field(default=None, metadata={"key": "pass"})
    difference: float = 0.0
    se: float = 0.0
    s1: float = 0.0
    s2: float | None = None
    mean1: float = 0.0
    mean2: float | None = None
    n1: int = 0
    n2: int | None = None
    status: str = "NOT_EVALUATED"
    reference: float | None = None
    model: str | None = None
    method: str | None = None
    threshold: float | None = None
    mean_difference_pass: bool | None = None
    mean_difference_status: str = "NOT_EVALUATED"
    design_status: str = "OK"
    design_warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "StabilityResult":
        """将内部中间值映射转换成具名结构。"""
        values = values.copy()
        values["passed"] = values.pop("pass", None)
        return cls(**values)

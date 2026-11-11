# SPDX-License-Identifier: Apache-2.0
"""GL002 附录 A.2 与可选交叉核对。"""

import pytest

from openpt.core.robust import algorithm_a


def test_gl002_against_optional_library() -> None:
    """GL002 A.2：第三有效位及对应数位；合成对称样本均值为 2。"""
    values = [1.0, 2.0, 3.0, 4.0, 0.0]
    local = algorithm_a(values)
    assert local["rule"] == "gl002"
    assert local["x"] == pytest.approx(2.0)
    library = pytest.importorskip("pt13528.robust")
    reference = library.algorithm_a(values, tol="equivalent-figure")
    assert local["iterations"] == reference.iterations
    assert local["x"] == pytest.approx(reference.location, abs=1e-12)
    assert local["s"] == pytest.approx(reference.scale, abs=1e-12)


def test_absolute_and_simplified() -> None:
    """GL002 附录 A.2 给出简化法；绝对容差为软件附加选项。"""
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert algorithm_a(values, rule="simplified")["iterations"] == 0
    assert algorithm_a(values, rule="absolute", tolerance=1e-9)["converged"]

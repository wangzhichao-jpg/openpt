# SPDX-License-Identifier: Apache-2.0
"""导入与只读检查共用的数据形态规则。"""


def insufficient_units(count: int) -> bool:
    """单因子方差分析和当前稳定性计算至少需要两个单元。"""
    return count < 2


def insufficient_homogeneity_replicates(count: int) -> bool:
    """常规方差分析要求每个均匀性单元至少两次重复。"""
    return count < 2

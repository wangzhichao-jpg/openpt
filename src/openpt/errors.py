# SPDX-License-Identifier: Apache-2.0
"""输入错误及可定位的提示。"""


class InputError(ValueError):
    """输入无法用于选定计算；可包含工作表和单元格位置。"""

# SPDX-License-Identifier: Apache-2.0
"""输入数据校验错误。"""


class InputError(ValueError):
    """带位置的输入错误；用于在命令行提示用户修正数据。"""

# SPDX-License-Identifier: Apache-2.0
"""允许使用 python -m openpt 启动命令行。"""

from .cli import main

raise SystemExit(main())

# SPDX-License-Identifier: Apache-2.0
"""打包入口。"""

import os
import traceback
from pathlib import Path

if __name__ == "__main__":
    try:
        from openpt.windows_app import main

        main()
    except Exception:
        smoke_dir = os.environ.get("OPENPT_GUI_SMOKE_DIR")
        if not smoke_dir:
            raise
        Path(smoke_dir, "gui-smoke-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise SystemExit(1) from None

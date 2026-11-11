# SPDX-License-Identifier: Apache-2.0
"""清除 sdist tar 条目中的本机用户和组元数据。"""

import gzip
import io
import os
import sys
import tarfile
from pathlib import Path


def main(path):
    path = Path(path)
    buffer = io.BytesIO()
    timestamp = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    with (
        tarfile.open(path, "r:gz") as source,
        gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as output,
    ):
        for member in source.getmembers():
            data = source.extractfile(member) if member.isfile() else None
            member.uid = member.gid = 0
            member.uname = member.gname = "root"
            member.mtime = timestamp
            for key in ("mtime", "atime", "ctime", "uid", "gid", "uname", "gname"):
                member.pax_headers.pop(key, None)
            output.addfile(member, data)
    path.write_bytes(buffer.getvalue())


if __name__ == "__main__":
    main(sys.argv[1])

# SPDX-License-Identifier: Apache-2.0
"""清除 sdist tar 条目中的本机用户和组元数据。"""
import io
from pathlib import Path
import sys
import tarfile

def main(path):
    path=Path(path); buffer=io.BytesIO()
    with tarfile.open(path,'r:gz') as source, tarfile.open(fileobj=buffer,mode='w:gz') as output:
        for member in source.getmembers():
            data=source.extractfile(member) if member.isfile() else None
            member.uid=member.gid=0; member.uname=member.gname='root'
            output.addfile(member,data)
    path.write_bytes(buffer.getvalue())

if __name__=='__main__': main(sys.argv[1])

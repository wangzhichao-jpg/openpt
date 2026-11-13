# 第三方许可证与分发注意事项

下表列出 Python 运行时直接与传递依赖的项目级许可证；安装器可能按平台选择不同 wheel，实际分发必须核查该 wheel 中的完整许可证和附带组件。许可证信息依据本机安装包元数据和随包文件，不代表其他版本均相同。

| 项目 | 项目级许可证 | 关系 |
|---|---|---|
| NumPy | BSD-3-Clause，部分文件 0BSD、MIT、Zlib、CC0-1.0 | 直接 |
| SciPy | BSD-3-Clause，含其他许可组件 | 直接 |
| openpyxl | MIT | 直接 |
| python-docx | MIT | 直接 |
| et_xmlfile | MIT | openpyxl 传递依赖 |
| lxml | BSD-3-Clause | python-docx 传递依赖，随包可能带 libxml2、libxslt、zlib 等，按其许可文件核查 |
| typing_extensions | PSF-2.0 | python-docx 传递依赖 |

**依赖包许可口径。** 按验收端澄清，宽松许可要求针对上表所列 Python 依赖包自身的项目级许可；这些项目级许可属于宽松许可。Windows 包会捆绑上游二进制依赖，构建脚本收集实际构建环境的许可证文件。上游 NumPy/SciPy wheel 可能包含 libgfortran（GPL-3.0-or-later WITH GCC-exception-3.1）和 libquadmath（LGPL-2.1-or-later，动态链接）；lxml 某些平台构建可能包含 iconv。分发前应核查实际 wheel 的随附许可并履行相应义务。本说明不声称整个二进制依赖链的每个组件都是宽松许可证。

可选交叉核对依赖 pt13528 为 LGPL-3.0-or-later，仅在显式安装 crosscheck extra 时使用，不纳入运行时。PyInstaller 采用 GPL-2.0-or-later，bootloader 附有分发例外；Windows 包随附其许可。Python、Tcl/Tk 及依赖许可证也随 Windows 包附带。此清单不是法律意见。

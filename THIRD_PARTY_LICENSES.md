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

**未满足全链路均为宽松许可证的硬要求。** 本机 NumPy 二进制包的许可证文件明确列出 libgfortran：GPL-3.0-or-later WITH GCC-exception-3.1，libquadmath：LGPL-2.1-or-later；SciPy 的二进制包也可能包含同类运行库。lxml 的许可证说明还提及某些平台可能包含 LGPL 的 iconv。项目本身并不将这些库打包进 wheel，但通过依赖安装时仍可能获得它们。须逐平台检查具体分发件、履行许可义务，或改用经审核的构建；在此之前不能声称运行时依赖全链路仅含宽松许可证。

可选交叉核对依赖 pt13528 为 LGPL-3.0-or-later，仅在显式安装 crosscheck extra 时使用，不纳入运行时。测试、构建工具不是运行时依赖。此清单不是法律意见。

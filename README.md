# OpenPT 能力验证计算工作台

OpenPT 提供均匀性、稳定性和指定值计算。本项目采用 Apache-2.0 许可证。

## Windows 快速开始

1. 解压 `OpenPT-Windows-x64.zip`，双击文件夹内的 `OpenPT.exe`。
2. 点击“载入甲醛示例”，或选择已填写的 Excel 数据文件。也可以新建模板，填写并保存。
3. 点击“开始计算”，在窗口查看均匀性、各稳定时间组和指定值。
4. 点击“打开计算书”或“打开结果目录”。结果保存在个人文档的 `OpenPT结果` 文件夹。

无需安装 Python 或其他运行环境，也无需管理员权限。工作簿中设置计算方法；程序不会修改输入文件。详细填写方式见 [使用手册](docs/使用手册.md)。

## 开发与验证

源码及内部计算管线保留，工程测试包含 Windows、Linux 及 R 独立对照。开发者参考见 [命令行与工程参考](docs/开发者命令行参考.md)，第三方许可见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。Windows 便携包由 `.github/workflows/windows-build.yml` 在原生 Windows 上构建和冒烟测试。

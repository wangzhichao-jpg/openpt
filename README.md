# 能力验证样品评价与定值工具

简体中文 | [English](README.en.md)

## Windows 免安装版下载

- **国内入口：**[Gitee 下载 Windows 免安装版 0.2.6](https://gitee.com/bigtaurus/openpt/releases/tag/v0.2.6)（Gitee 本地附件）。
- **备用入口：**[GitHub 下载 Windows 免安装版 0.2.6](https://github.com/wangzhichao-jpg/openpt/releases/tag/v0.2.6)。

两个入口均提供 0.2.6，包含甲醛、材料抗拉强度、颗粒振实密度、数字多用表和 GB/T 28043 合成检测五个示例；σ_pt 可由参加者结果计算（NIQR、算法A、MADe、算法S），计算书增加参加者结果统计量表和算法A迭代过程，模板提供常见场景填写说明和冲突提示；窗口显示 σ_pt 及每位参加者的统计量与评价，稳定性可按时间组分别选择评价准则。

下载 Windows ZIP 后全部解压并双击程序。

Windows 11 的智能应用控制可能阻止未签名程序；本程序目前未进行代码签名，项目已选定 SignPath Foundation 提供的开源项目免费代码签名方案，尚未申请。处理方式见[使用手册](docs/使用手册.md#smart-app-control)。

本工具提供均匀性、稳定性和指定值计算。本项目采用 Apache-2.0 许可证。

## 视频讲解

能力验证统计学避坑指南（竖屏短视频，约 3 分钟一集）：

- 01 F检验过了，均匀性就够了吗？（F 检验与 Ss ≤ 0.3σ 准则、异常单元复核）：[B站](https://www.bilibili.com/video/BV1vPyizHE3K/) ｜ [YouTube](https://youtube.com/shorts/oF8_y89ukRg)
- 02 10 瓶各测 2 次，算 20 个数还是 10 瓶？（稳定性检验的伪重复与自由度）：[B站](https://www.bilibili.com/video/BV1oryLzvEZh/) ｜ [YouTube](https://youtube.com/shorts/XXDXruBJP8I)

## Windows 快速开始

1. 解压 `能力验证样品评价与定值工具_Windows.zip`，双击文件夹内的 `能力验证样品评价与定值工具.exe`。
2. 点击“载入甲醛示例”，或点击“选择数据文件”选择程序旁“示例案例”文件夹中的工作簿。也可以新建模板，填写并保存。
3. 点击“开始计算”，在窗口查看均匀性、各稳定时间组和指定值。
4. 点击“打开计算书”或“打开结果目录”。结果保存在个人文档的 `OpenPT结果` 文件夹。

无需安装 Python 或其他运行环境，也无需管理员权限。工作簿中设置计算方法；程序不会修改输入文件。详细填写方式见 [使用手册](docs/使用手册.md)。

## 开发与验证

源码及内部计算管线保留，工程测试包含 Windows、Linux 及 R 独立对照。开发者参考见 [命令行与工程参考](docs/开发者命令行参考.md)，第三方许可见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。Windows 便携包由 `.github/workflows/windows-build.yml` 在原生 Windows 上构建和冒烟测试。

# Windows 兼容性测试

`tools/test_windows_wine.sh` 是供维护者在 Linux 上选用的 Wine 辅助测试，不替代 Windows 实机或 CI。脚本以 `git archive HEAD` 提取已提交的公开源码，不读取仓库外的内部数据；未提交的修改不会参与测试。

请先确认 Docker 可用，并预先取得、核验 `tobix/pywine:3.12` 镜像的可信来源与摘要。脚本不会自动拉取镜像；本轮本地镜像摘要为 `sha256:e1c1d41a8b64616ac838aed8908a75b8f6838337533fe2484a7bb6871a8403cc`。建议先检查可靠国内镜像是否有相同摘要，不关闭 TLS 或完整性校验。

```sh
bash tools/test_windows_wine.sh
```

脚本设置 `LANG=C.UTF-8`、`LC_ALL=C.UTF-8`，通过清华 PyPI 镜像安装依赖，固定 NumPy 1.26.4 和 SciPy 1.13.1，然后运行公开测试及中文路径的 `python -m openpt demo`。可用 `OPENPT_WINE_IMAGE` 选择已验证的镜像标签，用 `OPENPT_WINE_LOCK` 指定锁文件。正式运行应使用用户级 systemd 任务和锁，保留日志，并检查容器确实退出后再重试。

已知限制：此 Wine 版本缺少 `ucrtbase.crealf`，NumPy 2.x 会崩溃，所以此辅助测试固定 1.26.4；这不是对原生 Windows 上 NumPy 2.x 的结论。容器语言环境影响中文文件名的转换；`C.UTF-8` 下通过不代表所有 Windows 区域设置都通过。测试依赖 Docker、Linux、Wine 和网络，不能替代 Windows 10/11 实机、GitHub Actions Windows runner 或其他 Python／依赖版本的验证。

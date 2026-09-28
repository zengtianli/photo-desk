# Photo Engine 修复同步 · 2026-09-28

本轮仅修改 PhotoDesk 仓库；沿用用户长期授权装机、发行、推送及单产品官网部署。开工时仅有 Chapter 原有未跟踪的 perf/acceptance、build-receipt 和 delivery-evidence，不纳入提交。两个子 agent 分别负责 vendor/lib 与 manifest、回归测试与发行校验；主 agent 集成、提交及实际交付。

## 同步内容

- 原版为 apple-data/engine/photo/photocli/photocli/lib.py，已提交修复为 75d955bdab0f2b35325db4efef54030158c10ba7；副本 SHA-256 为 6f5e4a8bce7c4154cc5276c216c0e9af8b9da95d2c19f71249bfb3b1103f2729，其余十个模块与上游一致。
- 配置缺失、非法 YAML、顶层类型错误，以及照片库缺失、权限不足、SQLite 与解析异常，转为可读错误；失败不污染已有成功缓存，修复输入后可恢复。
- App 桥接层沿异常上下文保留 PhotoDesk 自身的完全磁盘访问提示，避免引入上游 CLI 对“终端”的提示。
- 发行验证使用临时存在但无数据库的 .photoslibrary，越过 App 路径预检，真正调用冻结包的 lib.load_db；旧装机 31 已按预期失败，不能再把仅通过路径预检当成修复进入发行包的证据。
- 固定 recovery 验收加入同样的真实冻结引擎错误路径，并核对原合成图库缓存未变；不读写个人图库，不抢焦点或模拟输入。

## 交付及复现

已交付构建 1.0.1（33），沿用 ad-hoc、未公证 ZIP 分发。提交后按以下既有入口生成 receipt、装机并核验真正内置引擎；版本和成功状态以实际生成的 dist/release.json、perf/build-receipt.json、perf/acceptance 和 build/engine-sync-readback.json 为准。

```sh
uv run python scripts/accept/build.py
python3 scripts/install_app.py build/DerivedData/Build/Products/Release/PhotoDesk.app --name-en PhotoDesk --display-name 'PhotoDesk · 照片台' --bundle-id cyou.tianli.PhotoDesk
uv run python scripts/check_distribution.py /Applications/PhotoDesk.app --report build/installed-engine-check.json
uv run python scripts/release.py --reuse-build
uv run python scripts/build_site.py
~/Dev/.venv/bin/python ../chapter/engine/app_sop.py run --app photo-desk --test-only --now --json
~/Dev/.venv/bin/python ../chapter/engine/app_sop.py accept --app photo-desk --check functionality --check recovery --check privacy --check native_ui --json
```

推送前已读 GitHub 最新发行31与远端 main，Actions/Webhooks 均为零，仓内无 ci_scripts、工作流或 Xcode Cloud 配置；推送只更新公开源码与说明，未改变公开范围。官网仅走 apps-portal/site/deploy.sh --products-only photo-desk，按计划白名单、远端备份和失败回滚发布，不改变其他产品或 DNS/authgate。

资源测量仍标注旧构建21，不伪填当前性能；长时间空闲采样沿既有门槛另补。装机图标由本人在 Chapter 确认，不能以签名或文件哈希代替视觉确认。

## 最终回读（16:30）

- 业务提交 ad309d50fdd710bf2b068c044b2319f9af201662 已推送；本地副本与上游 lib.py 字节一致，manifest 的 11 个文件全部通过核验。
- 本机安装、GitHub Release v1.0.1-33、官网 release.json 均为 1.0.1（33）；装机签名及 receipt 与当前构建输入一致；已安装包和独立发行包各自通过真实内置引擎故障回归，未访问个人图库。
- ZIP 为 37,354,083 字节，SHA-256 e916c41555e0dfb120bff0ba7d536cbe542c91799e753a307162e516fc399ede；GitHub 上传资产 digest、官网公开 checksum 及部署服务器实际文件哈希一致；本轮未完整回下载 ZIP，不将 HEAD 视为整包下载验收。
- 主 agent 统一验证 37 项 Python 测试及 Swift 控件测试通过，Chapter 已登记当前代码测试；functionality、recovery、privacy、native_ui、homepage_desktop、homepage_mobile、media_playback 七项固定验收通过，证据由 app_sop 生成。
- 官网部署计划为 apps-portal/site/build/product-publish/20260928T082742Z-c317f55d/plan.json，只涉及 PhotoDesk 的 16 个文件，远端备份及 rollback.sh 已保留，线上图标与两段视频哈希匹配。
- Chapter check-only 已回读：装机、发布、receipt、README、测试、素材和页面通过；coverage 仅剩 installed_icon；perf 与 input-binding 仍为旧构建21的性能证据，需要空闲采样，不能据此声称全部维度通过。
- 接手性能采样：接电、闲置十分钟且低负载后，在本仓执行 `~/Dev/.venv/bin/python ../.claude/skills/app-lightweight/scripts/batch_measure.py photo-desk`；随后运行 `~/Dev/.venv/bin/python ../chapter/engine/app_sop.py run --app photo-desk --check-only --json`。
- 此最终交接只改文档，不改变已发布构建输入，按已匹配则跳过的要求不重复打包、装机或发版；完整机器回读在 build/engine-sync-readback.json，Chapter 重检在 build/engine-sync-sop.json。

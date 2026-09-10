# PhotoDesk 产品主页与真实媒体 · 2026-09-10

本轮用户选择 PhotoDesk 做产品线。主页采用亮色青绿色品牌、真实截图、两段字幕演示、直接下载、安装教程与 FAQ；私有源码不公开。

当前冻结发行：`/Users/tianli/Apps/mac/photo-desk/dist/PhotoDesk-1.0.1-10-arm64.zip`，v1.0.1 build 10，arm64、macOS 15+，ad-hoc 签名、未公证。SHA-256：`ca83de1b407771b86a92f3b72f60c620280077f4e2aea75c2520a4efef5e086b`。发行对应源提交 `ef19e9001c2faf7a335be80fdc55f79d2aee61a0`；本次只提交媒体、主页与剪辑工具，没有重新编译 App 或提升 build。

真实录制由主线程通过 CUA AX 完成，使用独立合成输入、缓存与偏好。普通发行 App 不含测试 `LSEnvironment`；非激活面板只用于严格隔离的录制环境。演示输入为 9 张原创合成图及 1 张字节相同副本，归集、文字识别和重复核对调用生产实现。

媒体在 `/Users/tianli/Apps/mac/photo-desk/docs/demo/`：`timeline.mp4` 14.6 秒、`review.mp4` 17.9 秒，后者明确标注重复核对补拍。两张截图、两张成片海报及两段视频由 `evidence.json` 固定哈希；`recording.json` 保留三段原片与精确剪点映射，`result-check.json` 记录独立结果核验，`VERIFICATION.md` 说明验证范围。原片只在 gitignored `build/tutorial/raw/`。

已验证：11 段首中尾共 33 帧和关键放大/海报/截图；完整解码、H.264/yuv420p、30 fps、faststart、无持续黑段；三段原片及主线程截图哈希不变。生产结果 10 项完成、0 失败、3 个片段（3/3/4），计划成员与输入集合一致；重复 2 项、1 项预选，文件字节哈希相同。无效下一张及等待已剪去；未录到关闭预览，未覆盖个人图库授权、Apple 相册写回或照片删除。

正式站点：`/Users/tianli/Apps/mac/photo-desk/build/site/`，15 个公开白名单文件，含 `site-manifest.json` 共 16 个文件，`preview: false`。每项实际哈希与清单一致；安装包哈希与冻结发行一致。CSS 地址含内容哈希，移动端标题字号已按主线程审核调整。

主线程已通过桌面与 390px 页面标题、图片验收；视频容器随后匹配真实成片的 160:137 比例，避免旧 1.5 比例产生额外留边，仅修改视频规则，截图布局保留。

首次线上全量 HTTPS GET 已写 `build/online-verification.json`：16 文件全部返回 200，完整 ZIP 和全部非 HTML 文件哈希一致；3 个 HTML 仅多出 Cloudflare Web Analytics 自动注入脚本，原始响应 SHA-256 如实记为不一致。后续公开隐私说明已按真实统计行为修正并链接官方说明；没有修改 Cloudflare 或服务器配置。

主页媒体说明现只展示录制版本、合成输入数量和剪辑方式，两段视频描述按实际录到的操作收窄。内部返工细节与覆盖局限完整保留在 `recording.json`、`evidence.json`、`VERIFICATION.md`，不再整段进入产品用户页面。此后新的正式站点清单需要主线程重新生成发布计划并上线；初次线上验收 JSON 仍绑定此前清单，不能冒充新文案已经上线。

复建主页：

```bash
cd /Users/tianli/Apps/mac/photo-desk
/opt/homebrew/bin/python3 scripts/build_site.py
```

媒体复建接口为 `scripts/render_demo.py`，需保留真实原片；详 `docs/demo/EDITING.md`。不能从当前 HEAD 的提交数量推断录制 build。

主线程后续负责浏览器验收与共享站群按产品发布，域名 `app-mac-photodesk.tianli.cyou`。本站没有单独 provision nginx，也未由本子任务远端部署。并行迁移对 `scripts/vendor_engine.py` 的路径改动不属于本提交，保留原样未暂存。

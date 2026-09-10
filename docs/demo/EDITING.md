# 真实录屏剪辑接口

入口：`/opt/homebrew/bin/python3 scripts/render_demo.py`。Pillow 只绘制画面外的青绿色字幕条；产品区域始终来自原片。原片保留在 `build/tutorial/raw/`，脚本不会覆盖主线程保存的 `timeline.png`、`preview.png`。

1. 主线程确认原片、录制版本/build、冻结发行 SHA-256、系统与芯片。将 `edit-plan.example.json` 的结构填写为 `edit-plan.json`；未知事实保持空值，不能从当前源码推测录像版本。
2. 检查每个关键操作前后画面，填写每段原片 SHA-256、实际宽高、整窗裁剪范围与剪点。每个 `segments` 条目形如 `{"start": 1.2, "end": 4.8, "crop": [0, 0, 1200, 840], "title": "按实际操作填写", "subtitle": "按实际结果填写"}`；`crop` 可省略以沿用 `window_crop`，单位为原片像素。剪点为原片秒数，`poster_time` 为成片秒数。只保留原速，剪去等待与局部放大会明确标注。
   同一 build 和同一图库的补拍可登记在章节的 `supplements` 对象，每个具名条目同样提供 `raw_file`、`raw_sha256`、`raw_geometry`、`window_crop`；其 `chapter` 必须含“补拍”。对应剪点设置 `source` 为该条目名。脚本分别验证各原片的顺序、范围与哈希，成片字幕持续标注补拍，记录保留来源；不能把补拍伪装为连续操作。
3. `--check-only` 校验真实源文件哈希、版本/build/发行哈希、剪点范围与顺序、裁剪几何、字幕安全边距。缺少观测事实时拒绝运行。`--layout-preview` 只在 build 生成两个字幕色带，不生成产品画面。
4. 运行无参数剪辑，生成两段 MP4、对应 JPG 海报、VTT 与 `recording.json`。海报从成片抽帧；成片为 H.264/yuv420p/faststart。逐片完整解码，并检查产品画面区域持续黑屏；这些机器检查不替代内容验收。
5. 录制负责人或受委派的媒体验收者核验首中尾、每次操作和结果、局部放大边界、其他 App/个人内容泄露。确认后才将计划中的 `review.privacy_reviewed` 和 `review.final_visual_review` 设为 true，填写 `reviewer_role`（`recording-owner` 或 `media-reviewer`）以及真实覆盖与剪辑说明。运行 `--finalize` 生成现有主页构建器需要的 `evidence.json`；六项公开媒体的 SHA-256 在此时固定。

两段是独立章节，不把不同 build 或不同图库拼成同一次连续操作。此合成图库演示不能证明个人图库权限授予、Apple 相册写回或系统删除成功。脚本不启动 App，不生成截图，不构建或部署网站。

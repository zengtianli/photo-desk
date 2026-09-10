# PhotoDesk 真实媒体接口

主线程通过 CUA 操作独立演示 App，录制真实原生窗口。不得从个人图库取截图，不得把预绘图片冒充产品界面。

1. `uv run python scripts/prepare_demo.py` 生成 `build/demo-input/`：9 张明确标记的原创合成图片及 1 张字节相同副本。图片是输入，manifest 只给拍摄时间、已有相册等元数据；时间线、OCR、Vision 和重复核对走生产函数。
2. `python3 scripts/prepare_demo_app.py` 把四个环境值写入临时副本 `build/demo-app/PhotoDesk Demo.app` 的 `LSEnvironment`，并用独立 bundle ID 避免碰到用户正在运行的应用；脚本只准备，不启动。然后由 CUA 以 background 方式启动。不装机、不停止用户进程。
3. `PHOTODESK_BACKGROUND=1` 禁应用主动激活/重新打开抢前台。`PHOTODESK_DEMO_ROOT` 使后台只读合成输入，数据缓存强制位于该目录内；Apple Photos 定位、授权、写入及删除均拒绝执行。
4. 界面常驻合成演示标识。此片只能证明界面与样例算法，不能证明图库读取权限、Apple 相册写回或系统删除成功。

## 拍摄清单

| 成片 | 起点与操作 | 要看到的结果 | 独立核验 |
|---|---|---|---|
| `timeline.mp4` | 我的时间线开始；分别点击猫时间线、会议与工作、回全部 | 合成 10 项实际归集；猫与会议来自已有相册/真实 OCR 线索 | `build/demo-input/state/journey/*/latest.json` 中总数与事件成员守恒；10 项各出现一次 |
| `review.mp4` | 全部照片或首页片段；先单击，再“放大查看”/“查看片段”，随后重复核对 | 单击只选择；预览显示真实输入图像；1 对等字节照片、1 项建议 | 两输入文件 SHA-256 相同；生产重复计划行数2，recommended 计数1 |

只用 CUA 提供的 AX 按钮/字段操作；不发送共享剪贴板或系统级键盘事件。若 AX 无法触发 Space，用界面真实的放大查看入口，并如实写字幕。首次采集保留实时等待，不用剪辑证明速度。

截图：`timeline.png`（首屏）、`preview.png`（实际预览）。海报：`timeline-poster.jpg`、`review-poster.jpg`（从对应字幕成片抽帧）。MP4 采用 H.264、yuv420p、faststart，原生 controls/playsinline。原片只放 `build/tutorial/raw/`。

完成后在此目录保存 `evidence.json`：

```json
{
  "recorded_version": "1.0.1",
  "recorded_build": "填实际Info.plist构建号",
  "synthetic_inputs": true,
  "privacy_reviewed": true,
  "caption": "PhotoDesk v1.0.1，Apple Silicon / 实际macOS版本，合成图像输入、原生窗口实录。按实际情况说明剪掉等待/补拍。",
  "files": [{"path": "timeline.png", "sha256": "填写实际值"}]
}
```

`files` 需要包含上面 6 个实际文件。`python3 scripts/build_site.py` 会核对版本、每项哈希与 MP4 流；缺任何真实媒体就拒绝正式构建。`--preview` 允许有显式待采集区域的本地版式预览，但公开 manifest 标记 `preview: true`。

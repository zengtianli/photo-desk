# PhotoDesk

原生 SwiftUI 相册整理应用。产品范围、运行数据和构建入口见 README.md；命名及图标由 catalog.yaml 定义。

- 用户 2026-09-08 明确：照片有意义，要联系、分类、梳理成个人时间线、猫时间线、会议等。启动即自动全库归集、增量内容识别及重复预选，不能退回逐个点击“生成建议”的工具面板。时间线是主流程，旧写回工具置于菜单高级整理。
- backend/journey.py 是本地事件索引原版：读取全部可访问照片（共享只读），Vision + OCR，按 UUID/原片与修改时间缓存；不调用外部模型或传图。自动归类保存在 PhotoDesk；Apple 相册/标题写回仍经高级整理显式确认。
- 重复预选必须同时满足字节一致及保留副本覆盖独有元数据；保护、隐藏、编辑、视频和 Live Photo 不预选。后台刷新不能重置用户正在核对的勾选。删除仍只执行用户最终确认的精确资产。

- SwiftUI + 内置冻结 Python 引擎。运行禁止 import 其他 App 或依赖开发目录；osxphotos 的图库解析能力和现有 photocli 算法是保留 Python 的依据。
- vendor/photocli 是 apple/photo 的源码快照，先改源再显式同步；正常构建检查 manifest 的完整性。
- 只读生成计划；使用 Cloud GUID 映射，用户勾选并确认后写入同一份计划。执行前重新核对库路径、照片存在性、共享状态和标题冲突。
- 不提供自动删除；共享内容仅只读。未下载原片不 OCR，不把空 OCR 当垃圾，不推断票据报销状态。
- 手动删除走 NativePhotos：计划重新解析 → 精确匹配 PhotoKit 资产 → 用户逐项确认 → 系统确认 → 删除后回读。macOS 27 可能缺失旧 SystemLibraryPath 配置，不能据此误判图库；NativePhotos 必须匹配全部所选 UUID，否则整批拒绝。无 Cloud GUID 的本地照片只在原图库中用 UUID 解析。
- “整理 → 导入验收测试图…”生成明确标记的合成照片，真实写入与删除只用这类新建测试资产验收，不拿用户原有照片做实验。
- 数据只保存在用户 Application Support/PhotoDesk，qa/、原片、OCR 和含人物信息的测试输出不入 git。
- 修改 JSON 契约须通过真实 Swift decoder 验证。GUI 需实际窗口与操作检查；不在用户图库无人值守执行写入测试。
- build.sh 使用总部 Xcode 选择器和图标工厂，产物为自包含 App。提交后最后构建安装，以 git 提交数派生构建号。

import SwiftUI
import AppKit
import ImageIO
import AVKit

private let accent = Color(red: 0.06, green: 0.49, blue: 0.46)

struct ContentView: View {
    @ObservedObject var model: PhotoDeskModel
    @Environment(\.openSettings) private var openSettings
    @FocusState private var searchFocused: Bool
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(spacing: 12) {
                    Image(systemName: "photo.stack.fill").font(.system(size: 26)).foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("PhotoDesk").font(.title2.bold())
                        Text("给回忆一个好位置").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.horizontal, 20).padding(.top, 25)
                VStack(spacing: 5) {
                    ForEach([Page.journey, .library, .duplicates, .overview, .history]) { page in
                        Button { model.navigate(page); if page == .journey { model.track = "全部" } } label: {
                            HStack(spacing: 12) {
                                Image(systemName: page.symbol).font(.system(size: 16)).frame(width: 22)
                                Text(page.name).font(.system(size: 14, weight: model.page == page ? .semibold : .regular))
                                Spacer()
                            }.padding(.horizontal, 14).padding(.vertical, 11)
                                .foregroundStyle(model.page == page && (page != .journey || model.track == "全部") ? accent : .primary)
                                .background(model.page == page && (page != .journey || model.track == "全部") ? accent.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 9))
                        }.buttonStyle(.plain).disabled(model.busy)
                        if page == .journey {
                            ForEach(["猫时间线", "会议与工作", "资料与截图"], id: \.self) { track in
                                Button {
                                    model.navigate(.journey); model.track = track
                                } label: {
                                    HStack(spacing: 12) {
                                        Image(systemName: track == "猫时间线" ? "cat" : track == "会议与工作" ? "person.3" : "doc.text").frame(width: 22)
                                        Text(track).font(.system(size: 14)); Spacer()
                                    }.padding(.horizontal, 14).padding(.vertical, 11)
                                        .foregroundStyle(model.page == .journey && model.track == track ? accent : .primary)
                                        .background(model.page == .journey && model.track == track ? accent.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 9))
                                }.buttonStyle(.plain).disabled(model.busy)
                            }
                        }
                    }
                }.padding(.horizontal, 12)
                Spacer()
                VStack(alignment: .leading, spacing: 10) {
                    SettingsLink { Label("设置…", systemImage: "gearshape") }.buttonStyle(.link)
                    Label("在你的 Mac 上整理", systemImage: "desktopcomputer").font(.caption.weight(.medium))
                    Text("照片和识别结果保存在本机。\n整理先预览，删除由你决定。")
                        .font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                    Button("在“照片”中查看") { model.openPhotos() }.buttonStyle(.link)
                }.padding(20)
            }.navigationSplitViewColumnWidth(min: 210, ideal: 225, max: 255)
        } detail: {
            VStack(spacing: 0) {
                header
                if let error = model.error { errorBanner(error) }
                Group {
                    switch model.page {
                    case .journey: journeyArea
                    case .overview: overview
                    case .history: history
                    default: planArea
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                footer
            }.frame(minWidth: 670, minHeight: 560)
                .background(Color(nsColor: .windowBackgroundColor))
        }
        .tint(accent)
        .preferredColorScheme(model.preferences.colorScheme)
        .onAppear { model.openSettingsAction = { openSettings() }; model.startProductControls() }
        .toolbar {
            ToolbarItemGroup {
                Button { model.chooseLibrary() } label: { Label("选择图库", systemImage: "externaldrive") }.disabled(model.busy)
                Button { model.refresh() } label: { Label("刷新图库", systemImage: "arrow.clockwise") }.disabled(model.busy)
            }
        }
        .sheet(isPresented: $model.confirm) { confirmation }
        .sheet(isPresented: $model.confirmDelete) { deletionConfirmation }
        .sheet(isPresented: Binding(get: { model.enlargedPhoto != nil }, set: { if !$0 { model.enlargedPhoto = nil } })) {
            if let row = model.enlargedPhoto { LargePhotoPreview(row: row, previous: { model.movePhoto(-1) }, next: { model.movePhoto(1) }) }
        }
        .alert("导入一张验收测试图？", isPresented: $model.confirmFixture) {
            Button("取消", role: .cancel) { }
            Button("创建测试图") { model.createFixture() }
        } message: {
            Text("将在系统照片图库中新建一张带 PhotoDesk-QA 标记的图片，用于检查整理和删除功能。不会改动已有照片。")
        }
        .onChange(of: model.group) { _, _ in model.pageNumber = 0 }
        .onChange(of: model.search) { _, _ in model.pageNumber = 0 }
        .onChange(of: model.searchFocusToken) { _, _ in searchFocused = true }
        .onChange(of: searchFocused) { _, value in if value { model.gridFocused = false } }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 7) {
                Text(model.page == .journey && model.track != "全部" ? model.track : model.page.name).font(.system(size: 28, weight: .bold))
                Text(model.page.detail).font(.callout).foregroundStyle(.secondary)
            }
            Spacer(minLength: 15)
            if ![Page.journey, .overview, .history].contains(model.page) {
                Button(model.page == .library ? "刷新照片" : (model.plan == nil ? "生成建议" : "重新分析"), systemImage: model.page == .library ? "arrow.clockwise" : "sparkles") { model.generate() }
                    .buttonStyle(.borderedProminent).controlSize(.large).disabled(model.busy)
            }
        }.padding(28)
    }
    private func errorBanner(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(text, systemImage: "exclamationmark.circle").textSelection(.enabled)
            HStack {
                Button("打开权限设置") { model.openPrivacy() }
                Button("照片访问权限") { model.openPhotosPrivacy() }
                Button("在 Finder 显示 App") { NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL]) }
                Button("收起") { model.error = nil }
            }.buttonStyle(.link).font(.caption)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(15)
            .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 10)).padding(.horizontal, 28).padding(.bottom, 12)
    }
    private var footer: some View {
        HStack(spacing: 10) {
            if model.busy { ProgressView().controlSize(.small) }
            else { Image(systemName: "checkmark.circle").foregroundStyle(accent) }
            Text(model.progress?.message ?? model.status).font(.caption).lineLimit(2)
            if let p = model.progress, p.total > 0 { ProgressView(value: Double(p.done), total: Double(p.total)).frame(width: 100) }
            Spacer()
            if model.busy && !model.applying { Button("取消") { model.cancel() }.controlSize(.small) }
        }.padding(.horizontal, 24).padding(.vertical, 13).background(.bar)
    }

    private var overview: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                if let s = model.summary {
                    HStack(spacing: 14) {
                        metric("个人图库", value: s.total, symbol: "photo.on.rectangle.angled")
                        metric("视频", value: s.movies, symbol: "video")
                        metric("收藏", value: s.favorites, symbol: "heart")
                        metric("本地原片", value: s.local, symbol: "internaldrive")
                    }
                    HStack(alignment: .top, spacing: 18) {
                        VStack(alignment: .leading, spacing: 16) {
                            Text("时间里的照片").font(.headline)
                            ForEach(s.byYear.keys.sorted().reversed(), id: \.self) { year in
                                HStack(spacing: 10) {
                                    Text(year).font(.caption.monospacedDigit()).frame(width: 36, alignment: .leading)
                                    GeometryReader { proxy in
                                        Capsule().fill(accent.opacity(0.08))
                                        Capsule().fill(accent.opacity(0.75)).frame(width: max(3, proxy.size.width * Double(s.byYear[year] ?? 0) / Double(max(1, s.byYear.values.max() ?? 1))))
                                    }.frame(height: 7)
                                    Text((s.byYear[year] ?? 0).formatted()).font(.caption.monospacedDigit()).frame(width: 42, alignment: .trailing)
                                }
                            }
                        }.card()
                        VStack(alignment: .leading, spacing: 14) {
                            Text("现有相册").font(.headline)
                            ForEach(s.albums.sorted { $0.value > $1.value }.prefix(9), id: \.key) { album in
                                HStack {
                                    Image(systemName: "folder").foregroundStyle(accent)
                                    Text(album.key).font(.callout).lineLimit(1)
                                    Spacer(); Text(album.value.formatted()).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                }
                            }
                            if s.albums.isEmpty { Text("还没有相册，试试分类整理。 ").foregroundStyle(.secondary) }
                        }.card()
                    }
                    Text("\(s.photos.formatted()) 张照片 · \(s.live.formatted()) 张 Live Photo · 另有 \(s.shared.formatted()) 项共享或不可编辑内容（只读）")
                        .font(.caption).foregroundStyle(.secondary)
                    Text(s.message).font(.caption).foregroundStyle(.secondary)
                    Text("开始一次整理").font(.headline)
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
                        ForEach([Page.classify, .triage, .sensitive, .duplicates]) { page in
                            Button { model.navigate(page) } label: {
                                HStack(alignment: .top, spacing: 15) {
                                    Image(systemName: page.symbol).font(.title2).foregroundStyle(accent).frame(width: 30)
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text(page.name).font(.headline).foregroundStyle(.primary)
                                        Text(page.detail).font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                                    }
                                    Spacer(minLength: 0)
                                    Image(systemName: "arrow.up.right").foregroundStyle(.tertiary)
                                }.card()
                            }.buttonStyle(.plain).disabled(model.busy)
                        }
                    }
                    Text(s.library).font(.caption2).foregroundStyle(.tertiary).textSelection(.enabled)
                } else {
                    ContentUnavailableView {
                        Label("连接你的照片图库", systemImage: "photo.stack")
                    } description: {
                        Text("读取 Mac 上的照片、相册和拍摄信息，然后生成可预览的整理建议。")
                    } actions: {
                        Button("读取默认图库") { model.refresh() }.buttonStyle(.borderedProminent).disabled(model.busy)
                        Button("选择其他图库") { model.chooseLibrary() }.disabled(model.busy)
                    }.padding(.top, 60)
                }
            }.padding(.horizontal, 28).padding(.bottom, 28)
        }
    }

    private var journeyArea: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                if model.organizing { ProgressView().controlSize(.small) }
                VStack(alignment: .leading, spacing: 5) {
                    Text(model.organizationStatus).font(.callout)
                    if let error = model.organizationError { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                    if let j = model.journey {
                        Text("覆盖 \(j.albums) 个已有相册 · \(j.events.count.formatted()) 个生活片段 · 包含共享内容（只读）")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Button(model.automaticEnabled ? "暂停自动整理" : "继续自动整理") {
                    if model.automaticEnabled { model.pauseAutomation() }
                    else if !model.preferences.automatic { model.preferences.automatic = true }
                    else { model.startAutomation(restart: true) }
                }.disabled(model.busy)
            }.padding(.horizontal, 28).padding(.bottom, 15)
            if let event = model.activeEvent, let plan = model.plan {
                HStack {
                    Button("返回时间线", systemImage: "arrow.left") { model.activeEvent = nil; model.clearEventSelection(); model.group = "全部" }
                    Text(event.title).font(.headline)
                    Text("\(event.count) 张 · \(event.date)").font(.caption).foregroundStyle(.secondary)
                }.padding(.horizontal, 28).padding(.bottom, 8)
                planBrowser(plan, showGroups: false)
            } else {
                HStack(spacing: 12) {
                    Picker("时间线", selection: $model.track) {
                        ForEach(["全部", "个人时间线", "猫时间线", "会议与工作", "资料与截图"], id: \.self) { Text($0).tag($0) }
                        ForEach((model.journey?.tracks ?? []).filter { $0.hasPrefix("猫 · ") || $0.hasPrefix("人物 · ") }, id: \.self) { Text($0).tag($0) }
                    }.frame(maxWidth: 240)
                    TextField("查找人物、地点、日期或事件", text: $model.eventSearch).textFieldStyle(.roundedBorder).focused($searchFocused)
                    Button {
                        model.navigate(.duplicates)
                    } label: {
                        let rows = model.journey?.duplicates.rows ?? []
                        Text("重复核对 \(rows.filter { $0.recommended == true }.count) 项建议删除")
                    }.buttonStyle(.borderedProminent).disabled(model.journey == nil || model.busy)
                }.padding(.horizontal, 28).padding(.bottom, 12)
                if model.journey == nil {
                    ContentUnavailableView("正在联系你的照片", systemImage: "sparkles", description: Text("先按时间、人物与已有相册归集，随后在后台补充内容识别。无需逐项启动。"))
                } else {
                    ScrollViewReader { reader in
                    ScrollView {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 16)], alignment: .leading, spacing: 16) {
                            ForEach(Array(model.events.prefix(model.eventLimit))) { event in
                                JourneyCard(event: event, selected: model.selectedEventIDs.contains(event.id), select: {
                                    searchFocused = false
                                    model.selectEvent(event, modifiers: NSApp.currentEvent?.modifierFlags ?? [])
                                }, open: { model.openEvent(event) }).id(event.id)
                            }
                        }.frame(maxWidth: .infinity, alignment: .topLeading)
                        if model.events.isEmpty {
                            ContentUnavailableView("暂未找到匹配片段", systemImage: "magnifyingglass", description: Text("可调整筛选；后台识别完成后会自动补充。"))
                        }
                        if model.events.count > model.eventLimit {
                            Button("继续查看更早的片段") { model.eventLimit += 60 }.padding()
                        }
                    }.padding(.horizontal, 28)
                        .background(GeometryReader { proxy in
                            Color.clear.onAppear { model.gridColumns = max(1, Int((proxy.size.width - 40) / 276)) }
                                .onChange(of: proxy.size.width) { _, width in model.gridColumns = max(1, Int((width - 40) / 276)) }
                        })
                        .onChange(of: model.navigationScrollToken) { _, _ in
                            if let id = model.focusedEventID { reader.scrollTo(id, anchor: .center) }
                        }
                    }
                    Divider()
                    HStack {
                        Button("全选片段") { model.selectAllPhotos() }
                        Button("取消选择") { model.clearEventSelection() }.disabled(model.selectedEventIDs.isEmpty)
                        Text("已选 \(model.selectedEventIDs.count) 个片段 · \(model.selectedPhotoCount) 张可操作照片").font(.caption)
                        Spacer()
                        Button("快速预览", systemImage: "eye") { model.togglePreview() }.disabled(!model.canPreview)
                        Button("删除所选 \(model.selectedPhotoCount) 张照片…", role: .destructive) { model.checkBeforeDelete() }.disabled(model.selected.isEmpty)
                    }.controlSize(.small).padding(15).disabled(model.busy)
                    Text("单击选择整个片段，⌘增减、⇧连续选择；空格预览封面。逐张选择请点“查看片段”。共享照片只读。")
                        .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 15).padding(.bottom, 10)
                }
            }
        }
        .onChange(of: model.track) { _, _ in model.eventLimit = 60; model.clearEventSelection() }
        .onChange(of: model.eventSearch) { _, _ in model.eventLimit = 60; model.clearEventSelection() }
    }

    private func metric(_ label: String, value: Int, symbol: String) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(label, systemImage: symbol).font(.caption).foregroundStyle(.secondary)
            Text(value.formatted()).font(.system(size: 29, weight: .semibold, design: .rounded))
        }.frame(maxWidth: .infinity, alignment: .leading).card()
    }

    private var planArea: some View {
        VStack(spacing: 0) {
            if model.page.usesOCR {
                HStack {
                    Text("识别范围").foregroundStyle(.secondary)
                    Picker("识别范围", selection: $model.ocrLimit) {
                        Text("最近 50 项").tag(50); Text("最近 100 项").tag(100); Text("全部候选").tag(0)
                    }.labelsHidden().frame(width: 160).disabled(model.busy)
                    Text("只识别已下载原片，可复用上次识别结果").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                }.padding(.horizontal, 28).padding(.bottom, 15)
            }
            if let plan = model.plan {
                ForEach(plan.warnings, id: \.self) { warning in
                    Text(warning).font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 28).padding(.bottom, 6)
                }
                if plan.rows.isEmpty {
                    ContentUnavailableView("本次没有新增建议", systemImage: "checkmark.seal", description: Text("已检查 \(plan.examined) 项。已有分类会跳过；识别范围和缺失原片数量见上方说明。"))
                } else {
                    planBrowser(plan)
                }
            } else {
                ContentUnavailableView {
                    Label("先看看整理建议", systemImage: model.page.symbol)
                } description: {
                    Text(model.page == .duplicates ? "分析相同原片指纹，放大核对后可手动勾选删除。" : "点击“生成建议”开始分析。查看照片后，勾选想要执行的项目。")
                }
            }
        }
    }

    private func planBrowser(_ plan: PhotoPlan, showGroups: Bool = true) -> some View {
        let counts = Dictionary(grouping: plan.rows, by: \.group).mapValues(\.count)
        return VStack(spacing: 0) {
            HStack(spacing: 14) {
                TextField("搜索文件名、日期或建议", text: $model.search).textFieldStyle(.roundedBorder).focused($searchFocused)
                Text("\(model.filteredRows.count) 项").font(.caption).foregroundStyle(.secondary)
                Button("导出清单") { model.exportCSV() }.disabled(model.busy)
            }.padding(.horizontal, 28).padding(.vertical, 12)
            HStack(spacing: 0) {
                if showGroups {
                ScrollView {
                    VStack(spacing: 3) {
                        groupButton("全部", count: plan.rows.count)
                        ForEach(plan.groups, id: \.self) { group in
                            groupButton(group, count: counts[group] ?? 0)
                        }
                    }.padding(10)
                }.frame(width: 185)
                Divider()
                }
                ScrollViewReader { reader in
                ScrollView {
                    if model.filteredRows.isEmpty {
                        ContentUnavailableView("没有匹配照片", systemImage: "magnifyingglass", description: Text("清空搜索或选择其他月份后再查看。"))
                    }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: model.preferences.thumbnailWidth), spacing: 14)], spacing: 14) {
                        ForEach(model.visibleRows) { row in
                            PhotoTile(row: row, selected: model.selected.contains(row.id), readOnly: row.readOnly == true, enlarge: {
                                model.focusedPhotoID = row.id; model.gridFocused = true; model.enlargedPhoto = row
                            }) {
                                searchFocused = false
                                model.selectPhoto(row, modifiers: NSApp.currentEvent?.modifierFlags ?? [])
                            }.disabled(model.busy).id(row.id)
                        }
                    }.frame(maxWidth: .infinity, alignment: .topLeading).padding(16)
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(GeometryReader { proxy in
                        Color.clear.onAppear { model.updateGridWidth(Double(proxy.size.width)) }
                            .onChange(of: proxy.size.width) { _, width in model.updateGridWidth(Double(width)) }
                            .onChange(of: model.preferences.thumbnailWidth) { _, _ in model.updateGridWidth(Double(proxy.size.width)) }
                    })
                    .onChange(of: model.navigationScrollToken) { _, _ in
                        if let id = model.focusedPhotoID { reader.scrollTo(id, anchor: .center) }
                    }
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider()
            HStack(spacing: 12) {
                Button("全选筛选结果") { model.selectAllPhotos() }.disabled(model.busy)
                Button("清空勾选") { model.selected = [] }.disabled(model.busy)
                Spacer()
                Button("快速预览", systemImage: "eye") { model.togglePreview() }.disabled(!model.canPreview).help("空格键预览所选照片")
                Button { model.pageNumber -= 1 } label: { Image(systemName: "chevron.left") }.disabled(model.pageNumber == 0)
                Text("\(model.pageNumber + 1) / \(max(1, (model.filteredRows.count + 59) / 60))").font(.caption.monospacedDigit())
                Button { model.pageNumber += 1 } label: { Image(systemName: "chevron.right") }.disabled((model.pageNumber + 1) * 60 >= model.filteredRows.count)
                if !plan.isReadOnly {
                    Button("检查并写入 \(model.selected.count) 项") { model.checkBeforeApply() }
                        .buttonStyle(.borderedProminent).disabled(model.selected.isEmpty || model.busy)
                }
            }.controlSize(.small).padding(15)
            HStack {
                Label("删除后可在“照片”的“最近删除”中恢复", systemImage: "clock.arrow.circlepath").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(role: .destructive) { model.checkBeforeDelete() } label: {
                    Label("删除所选 \(model.selectedPhotoCount) 张照片…", systemImage: "trash")
                }.buttonStyle(.bordered).tint(.red).disabled(model.selected.isEmpty || model.busy)
            }.padding(.horizontal, 15).padding(.bottom, 12)
        }
    }
    private func groupButton(_ title: String, count: Int) -> some View {
        Button { model.group = title; model.gridFocused = false; model.focusedPhotoID = nil; model.selected = [] } label: {
            HStack {
                Text(title).font(.caption).lineLimit(2).multilineTextAlignment(.leading)
                Spacer(minLength: 4); Text(count.formatted()).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            }.padding(9).background(model.group == title ? accent.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 7))
        }.buttonStyle(.plain)
    }
    private var confirmation: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("确认本次整理", systemImage: "checklist").font(.title2.bold())
            Text("将在“照片”中执行你勾选的 \(model.selected.count) 项操作。")
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Dictionary(grouping: model.selectedRows, by: { "\($0.actionName) · \($0.group)" }).sorted { $0.key < $1.key }, id: \.key) { pair in
                        HStack { Text(pair.key); Spacer(); Text("\(pair.value.count) 项").foregroundStyle(.secondary) }
                    }
                }
            }.frame(maxHeight: 220)
            Text("相册和标题的改动会随 iCloud 同步。此操作不会删除照片。")
                .font(.callout).foregroundStyle(.secondary)
            HStack { Spacer(); Button("返回查看") { model.confirm = false }; Button("确认写入") { model.apply() }.buttonStyle(.borderedProminent) }
        }.padding(28).frame(width: 520).interactiveDismissDisabled()
    }
    private var deletionConfirmation: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("删除 \(model.pendingDeletion?.items.count ?? 0) 张照片？", systemImage: "trash").font(.title2.bold()).foregroundStyle(.red)
            Text("这会从照片图库中删除原照片，而不只是移出当前相册。启用 iCloud 照片时，删除会同步到其他设备。")
            Text("照片进入“最近删除”，通常可在 30 天内恢复。点击“确认删除”即提交删除；系统可能另外弹出确认。")
                .foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(model.pendingDeletion?.items ?? []) { item in
                        HStack {
                            Text(item.filename).textSelection(.enabled)
                            Spacer()
                            if !item.protected.isEmpty { Label(item.protected, systemImage: "heart.circle").foregroundStyle(.orange) }
                        }
                    }
                }
            }.frame(maxHeight: 250)
            HStack {
                Spacer()
                Button("取消", role: .cancel) { model.confirmDelete = false; model.pendingDeletion = nil; model.status = "已取消删除，照片未改动"; model.startAutomation(restart: true) }
                Button("确认删除", role: .destructive) { model.deleteSelected() }.buttonStyle(.borderedProminent).tint(.red)
            }
        }.padding(28).frame(width: 580).interactiveDismissDisabled()
    }
    private var history: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Button("刷新记录") { model.loadHistory() }.disabled(model.busy); Button("在 Finder 查看记录") { model.openRecords() }; Spacer() }
            if model.history.isEmpty {
                ContentUnavailableView("还没有整理记录", systemImage: "clock", description: Text("生成建议后，计划会自动保存在这里。"))
            } else {
                List(model.history) { entry in
                    HStack(spacing: 14) {
                        Image(systemName: Page(rawValue: entry.kind)?.symbol ?? "doc").foregroundStyle(accent)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(Page(rawValue: entry.kind)?.name ?? entry.kind).font(.headline)
                            Text(entry.created).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer(); Text("\(entry.count) 项").foregroundStyle(.secondary)
                        Button("打开计划") { model.restore(entry) }.disabled(model.busy)
                    }.padding(.vertical, 8)
                }.listStyle(.inset)
            }
        }.padding(.horizontal, 28).padding(.bottom, 20)
    }
}

private struct JourneyCard: View {
    let event: JourneyEvent
    let selected: Bool
    let select: () -> Void
    let open: () -> Void
    @State private var image: NSImage?
    var body: some View {
        VStack(spacing: 0) {
        Button(action: select) {
            VStack(alignment: .leading, spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9).fill(Color.secondary.opacity(0.08))
                    if let image { Image(nsImage: image).resizable().scaledToFill() }
                    else { Image(systemName: "photo.stack").font(.largeTitle).foregroundStyle(.secondary) }
                }.frame(height: 155).clipped().clipShape(RoundedRectangle(cornerRadius: 9))
                .overlay(alignment: .topTrailing) {
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                        .font(.title2).foregroundStyle(selected ? accent : .gray)
                        .background(.regularMaterial, in: Circle()).padding(7)
                }
                HStack { Text(event.date).font(.caption).foregroundStyle(.secondary); Spacer(); Text("\(event.count) 张").font(.caption.bold()).foregroundStyle(accent) }
                Text(event.title).font(.headline).lineLimit(2)
                Text(event.evidence.isEmpty ? "按同日拍摄顺序联系，内容识别继续补充" : event.evidence.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(3).frame(height: 43, alignment: .topLeading)
            }.padding(13).frame(maxWidth: .infinity, alignment: .leading)
                .background(selected ? accent.opacity(0.06) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 13))
                .overlay(RoundedRectangle(cornerRadius: 13).stroke(selected ? accent : Color.primary.opacity(0.07), lineWidth: selected ? 2 : 1))
                .contentShape(Rectangle())
        }.buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .simultaneousGesture(TapGesture(count: 2).onEnded { open() })
        Button("查看片段", systemImage: "arrow.right", action: open).buttonStyle(.link).font(.caption).padding(9)
        }
        .task(id: event.cover.previewPath) {
            let path = event.cover.previewPath
            let cg = await Task.detached(priority: .utility) { () -> CGImage? in
                guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil) else { return nil }
                return CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 640, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary)
            }.value
            if let cg, !Task.isCancelled { image = NSImage(cgImage: cg, size: .zero) }
        }
    }
}

private struct PhotoTile: View {
    let row: PlanRow
    let selected: Bool
    let readOnly: Bool
    let enlarge: () -> Void
    let toggle: () -> Void
    @State private var image: NSImage?
    var body: some View {
        VStack(spacing: 0) {
        Button { toggle() } label: {
            VStack(alignment: .leading, spacing: 9) {
                ZStack(alignment: .topTrailing) {
                    ZStack {
                        Rectangle().fill(Color(nsColor: .controlBackgroundColor))
                        if let image { Image(nsImage: image).resizable().scaledToFit() }
                        else { VStack(spacing: 8) { Image(systemName: "photo").font(.title); Text("暂无本地预览").font(.caption2) }.foregroundStyle(.tertiary) }
                    }.frame(height: 138).clipShape(RoundedRectangle(cornerRadius: 7))
                    if !readOnly {
                        Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                            .font(.title2).foregroundStyle(selected ? accent : .gray).background(.regularMaterial, in: Circle()).padding(7)
                    }
                }
                Text(row.filename).font(.caption.weight(.semibold)).lineLimit(1)
                Text(String(row.date.prefix(10))).font(.caption2).foregroundStyle(.secondary)
                Text(row.target).font(.caption).foregroundStyle(accent).lineLimit(2)
                if row.readOnly == true { Label("共享内容 · 只读", systemImage: "icloud").font(.caption2).foregroundStyle(.secondary) }
                if !row.protected.isEmpty { Label(row.protected, systemImage: "lock.fill").font(.caption2).foregroundStyle(.secondary).lineLimit(1) }
                if !row.note.isEmpty { Text(row.note).font(.caption2).foregroundStyle(.secondary).lineLimit(3) }
                Spacer(minLength: 0)
            }.padding(10).frame(maxWidth: .infinity, minHeight: 240, alignment: .topLeading)
                .background(selected ? accent.opacity(0.06) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(selected ? accent : Color.primary.opacity(0.07), lineWidth: selected ? 2 : 1))
                .contentShape(Rectangle())
        }.buttonStyle(.plain)
            .simultaneousGesture(TapGesture(count: 2).onEnded { enlarge() })
            .contextMenu { Button("放大查看", systemImage: "arrow.up.left.and.arrow.down.right") { enlarge() } }
            .help("\(row.filename)\n\(row.actionName)：\(row.target)\n\(row.note)")
            .task(id: row.previewPath) {
                let path = row.previewPath
                guard !path.isEmpty else { return }
                let cg = await Task.detached(priority: .utility) { () -> CGImage? in
                    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil) else { return nil }
                    return CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 480, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary)
                }.value
                if let cg, !Task.isCancelled { image = NSImage(cgImage: cg, size: .zero) }
            }
            Button("放大查看", systemImage: "arrow.up.left.and.arrow.down.right") { enlarge() }
                .buttonStyle(.link).font(.caption).padding(.vertical, 7)
        }
    }
}

// Use AppKit's player directly: the macOS 27 beta SwiftUI AVKit overlay
// aborts while initializing VideoPlayer's generic superclass metadata.
private struct NativeMoviePreview: NSViewRepresentable {
    let player: AVPlayer
    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .inline
        view.player = player
        return view
    }
    func updateNSView(_ view: AVPlayerView, context: Context) { view.player = player }
    static func dismantleNSView(_ view: AVPlayerView, coordinator: ()) {
        view.player?.pause(); view.player = nil
    }
}

private struct LargePhotoPreview: View {
    let row: PlanRow
    let previous: () -> Void
    let next: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var image: NSImage?
    @State private var player: AVPlayer?
    var body: some View {
        VStack(spacing: 14) {
            HStack { Text(row.filename).font(.headline); Spacer(); Button("上一张", systemImage: "chevron.left", action: previous); Button("下一张", systemImage: "chevron.right", action: next); Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction) }
            if let player { NativeMoviePreview(player: player).frame(maxWidth: .infinity, maxHeight: .infinity) }
            else if let image {
                Image(nsImage: image).resizable().scaledToFit().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else { ContentUnavailableView("暂无本地预览", systemImage: "photo", description: Text("原片可能未下载，或该视频尚无缩略图。")) }
            Text("\(row.date) · \(row.target)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            if !row.note.isEmpty { Text(row.note).font(.caption).textSelection(.enabled) }
            Text("空格 / Esc 关闭 · ← → 查看前后照片").font(.caption).foregroundStyle(.secondary)
        }.padding(20).frame(minWidth: 600, idealWidth: 850, maxWidth: 1100, minHeight: 500, idealHeight: 700, maxHeight: 900)
            .task(id: row.id) {
                player?.pause(); player = nil; image = nil
                if row.isMovie == true, let path = row.originalPath, !path.isEmpty, FileManager.default.fileExists(atPath: path) {
                    player = AVPlayer(url: URL(fileURLWithPath: path)); return
                }
                let path = row.isMovie != true && !(row.originalPath ?? "").isEmpty ? row.originalPath! : row.previewPath
                let cg = await Task.detached(priority: .utility) { () -> CGImage? in
                    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil) else { return nil }
                    return CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 1800, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary)
                }.value
                if let cg, !Task.isCancelled { image = NSImage(cgImage: cg, size: .zero) }
            }
            .onDisappear { player?.pause() }
    }
}

private extension View {
    func card() -> some View {
        padding(19).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).stroke(Color.primary.opacity(0.055)))
    }
}

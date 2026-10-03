# PhotoDesk

The Mac app menu includes **Configuration and updates…** and **Check for updates…**. Export/import organization rules, display preferences and shortcuts, or enable optional iCloud settings sync, off by default. With iCloud Drive and sync enabled on two Macs using the same Apple account, a new Mac restores existing preferences. Restores create backups and reject damaged files. Photos, library paths, recognition caches, login items and permissions stay on each device. Update checks read published releases from the existing public repository.

[中文](README.md) | **English**

A native macOS photo timeline. On launch it automatically scans the entire library, connects everyday life, cats, people, meetings, and documents, and prepares duplicate-photo cleanup suggestions.

Product website and installation guide: [PhotoDesk](https://app-mac-photodesk.tianli.cyou/). Verify the website’s publication status by visiting it.

Read the local [getting-started guide and captioned demos (Chinese)](docs/demo/tutorial.md), or see the [fixed acceptance commands](scripts/accept/README.md) for development verification.

<!-- lightweight:start -->
## Resource use

| Download | Idle memory | Idle CPU | Cold launch to window |
|---|---|---|---|
| **37.4 MB** (installed 92.0 MB) | **122 MB** | **0%** | **402 ms** |

Native SwiftUI window with no HTTP server. Photo analysis runs in a bundled Python engine packaged with PyInstaller, which accounts for most of the app's size; it runs as a subprocess and exits when done. While the app is open it checks every 60 seconds, read-only, only the photo data the engine actually uses, so system analysis and search-index writes do not count as changes. If nothing relevant changed, the engine does not start; if it did, the timeline is rebuilt, and when the result matches what is already on screen nothing is rewritten or redrawn. Back-to-back batches of 12 photos run only during the first content recognition pass.

<sub>v1.0.1 (50) · Mac16,12 / Apple M4 / macOS 27.2 · Real photo library with 6,393 items (2,722 timeline segments) · measured 2026-10-01. Measured on the listed device; re-measured for each version. Memory uses phys_footprint; CPU is CPU time ÷ wall time over a 60-second sampling window; sizes in decimal MB. Raw data: [perf/lightweight.json](perf/lightweight.json).</sub>
<!-- lightweight:end -->

## Usage

Open `/Applications/PhotoDesk.app`. It reads the most recently opened Photos library by default; you can also choose a `.photoslibrary` from the top right.

The homepage opens directly to “My Timeline.” It first groups the full library by time, location, people, and existing albums, then supplements the content in the background with Apple Vision classification and local OCR. You can browse while organization continues. Initial recognition takes time; the interface shows actual completed counts, resumes after quitting, and checks for new photos every minute by default.

Press **⌘,** or choose “Settings…” at the bottom left to open the native settings window. Automatic organization, launch at login, library and sharing scope, appearance, photo size, check frequency, recognition intensity, event time/distance limits, meeting-document association scope, cat names, and duplicate preselection are configurable and saved automatically.

Photo lists follow Mac conventions: click to select, ⌘-click to add/remove, and ⇧-click for a range. Arrow keys move; ⇧-arrow extends selection. **Space opens Quick Look**; Space or Esc closes it, and Left/Right moves between photos. Double-click or “Enlarge” opens the same preview. Original videos use the native player. ⌘A selects all current filtered results, ⌘F searches, and ⌘⌫ opens deletion preflight and confirmation. System text-editing behavior is preserved in text inputs. The grid adapts to window width and photo size; keyboard navigation scrolls and crosses pages.

Homepage timeline cards also select first: a single click selects the whole segment, with a border and checkmark for feedback. The bottom bar shows selected segment counts and actionable photos. ⌘/⇧ multi-selection and Space preview of the cover are supported; closing the preview keeps the selection. Double-click or the separate “View segment” button opens details, where individual photos can be selected. Shared photos do not count toward deletable totals, and background classification does not change the members of a segment being reviewed.

The photo context menu, enlarged preview footer, and “Photo” menu provide “Open in Photos,” locating the exact same image in Apple Photos by its local asset identifier. The timeline context menu can open the segment cover. First use may require system Automation permission.

Settings → Shortcuts supports recording, clearing, conflict notices, and scope. All custom bindings are empty by default. Show window, Settings, and Pause organization may be global; all others work only inside PhotoDesk. Standard native in-app keys are not registered as global shortcuts.

- **Personal and cat timelines**: Group segments chronologically, with search and filtering by named people or pets, date, and place. Photos recognized as cats but lacking names are not assigned invented names.
- **Meetings and work**: Combine meeting scenes, photo titles, existing albums, and meeting/project clues from OCR. Documents and screenshots can connect to meeting clues on the same day within 90 minutes and, when locations are known, no farther than 1 kilometer. This time-based inference is clearly labeled and must not be treated as a confirmed event.
- **Automatic association rules**: Photos on the same day and topic form a segment when shot no more than 3 hours apart and, for known locations, within 8 kilometers. Shared albums can be grouped and browsed, while deletion remains read-only.
- **Automatic duplicate cleanup suggestions**: First group by original-file fingerprints, then calculate SHA-256 for readable static originals. Deletion is preselected only when files are identical, the retained copy covers existing albums/titles/descriptions/keywords/people, and time/location agree. Favorites, hidden photos, independently edited photos, Live Photos, and videos are not automatically preselected. “Review duplicates” opens the selected suggestions for checking; final deletion still requires confirmation.

Automatic timeline classifications are stored in PhotoDesk’s local index and do not create albums in bulk in Apple Photos. To write classifications, keywords, or titles back to Apple Photos, use Organize → Advanced organization.

- **Library overview**: Personal photos, videos, favorites, local originals, year distribution, and existing albums.
- **All photos**: Browse by month in reverse order, search, and enlarge. Select photos and click the red “Delete N selected photos…” button at the bottom right. Photos not yet synced locally can also be selected.
- **Classification**: Year/month, people, pet albums, and readable scene labels. Existing assignments are skipped; favorites and photos of people are excluded from cleanup candidates.
- **Screenshots and receipts**: Local OCR through Apple Vision, with the latest 50, 100, or all candidates selectable. An existing “Cleanup candidates” album is analyzed first; otherwise PNG and document candidates are used. Missing originals or recognition failures remain pending review. Old receipts are not assumed reimbursed.
- **Sensitive photos**: Locally identifies identity documents, bank cards, and phone numbers. Plans show only the type, not the complete number.
- **Photo titles**: Fill empty titles and preserve existing ones. Recheck before applying to avoid overwriting recent edits.
- **Duplicate review**: Automatically generates groups, retention reasons, and preselected suggestions. Similar-looking scenes are not treated as identical duplicates; Live Photo motion content is not compared.
- **Organization history**: Restore the latest 30 plans and export full CSV. Local records retain plans and execution results.

Organization writes require selection, preflight, and then “Confirm write.” Every photo list has a separate deletion button. Review photos individually, then click “Confirm deletion” to submit to system Photos, which may show an additional confirmation. Original photos are deleted and the change syncs through iCloud; they can usually be recovered within 30 days in Photos → Recently Deleted. Shared albums, shared libraries, and unsaved shared-message photos are excluded from writes and deletion. PhotoKit checks exact asset identifiers before and after deletion, and execution records stay in the local history directory.

If access is denied, enable PhotoDesk in System Settings → Privacy & Security → Full Disk Access, then restart. Deletion also requires Photos access. The first organization write may additionally prompt for permission to control Photos.

**Recognition scope**: The system search scene index is unreadable on this machine’s macOS 27, so the automatic timeline runs local Vision classification directly on available previews. OCR covers PNG files and document/meeting candidates identified from images; it does not run without originals. Videos are classified only through metadata and existing previews, without understanding their full motion content. Originals are not downloaded automatically, and inferences are not presented as confirmed facts.

## Data and runtime

- Runtime data: `~/Library/Application Support/PhotoDesk/`, including plans, ocr, history, and progress. Full OCR text is cached only locally; directory permissions protect it for the current user.
- Native SwiftUI window with no HTTP service. Bundled Python, osxphotos, photoscript, and ocrmac are called through stdin/stdout JSON. Runtime operation does not depend on uv, Homebrew, the development directory, or other app projects.
- Python is retained because the app actually uses `PhotosDB` and `PhotoInfo` for people/tags/Cloud GUID/fingerprint parsing, `PhotosAlbum` for hierarchical albums, and photoscript write-back interfaces. Public PhotoKit alone cannot equivalently replace the existing organization capabilities.
- The photo engine lives in `backend/`: `bridge.py` is the dispatcher the App and the command line share (`handle()`), `journey.py` is the timeline index, `photocli/` holds the classification, OCR and title algorithms (originating from apple repository commit `75d955b`), `desk_cli.py` turns the App's functions into `photodesk` commands, and `preferences.py` reads and writes settings the way the App does. The GUI and `photodesk` share one bundled engine, maintained, tested and built here; the legacy `photocli` command only forwards to the installed PhotoDesk.

## Command line

The App includes `photodesk`; no separate Python installation is needed. This repository's installer links it into `~/.local/bin`. After dragging a downloaded App into Applications, run:

```sh
mkdir -p "$HOME/.local/bin"
ln -s /Applications/PhotoDesk.app/Contents/Resources/bin/photodesk "$HOME/.local/bin/photodesk"
export PATH="$HOME/.local/bin:$PATH"
photodesk --help
```

If the command path already exists, verify its origin before replacing it. When access is denied, grant Full Disk Access to the terminal running the CLI; the first `apply --confirm` may also ask whether the terminal may control Photos.

The window is for people, the commands are for agents: `photodesk` calls the same engine functions as the window and reads and writes the same timeline cache, plans, records and settings. Plans made from the command line appear in the App's Organize History, and the timeline the App built is readable from the command line. The library defaults to the App's (the library chosen in the App, otherwise the one Photos opened last); `--library PATH` picks another. Every read command takes `--json` and prints one object `{"ok": true, "command": …, …}`; a failure prints `{"ok": false, "error": …}` and exits 1, including failures before a command runs (usage errors, an unwritable data folder). Without `--json`, errors go to stderr. When following the system library, `timeline`, `duplicates` and `delete-check --event/--recommended` read only the timeline cache of the library Photos opened last; a cache from another library is an error, so run `photodesk refresh` first.

```sh
photodesk timeline --json --limit 20            # My Timeline: segments and recognition progress (cache, no rebuild)
photodesk timeline --event <segment-id> --json  # photos in one segment
photodesk refresh --json                        # like ⌘R: rebuild the timeline; writes only PhotoDesk's own index
photodesk refresh --enrich --max-batches 5      # continue on-device content recognition; batch size follows App settings
photodesk audit --json                          # Library Overview, same numbers as the App
photodesk photos --month 2026-09 --json         # All Photos (read-only, saves no plan)
photodesk duplicates --json                     # Duplicate Review: kept copy and suggested deletions
photodesk plan classify --json                  # Generate Suggestions (library/classify/triage/sensitive/title)
photodesk plans --json                          # Organize History (latest 30)
photodesk plan-show <plan-id> --group <group> --csv-out list.csv
photodesk apply <plan-id> --select-all          # Check and Write: pre-check only by default, library untouched
photodesk apply <plan-id> --select 3,7 --confirm  # write to Photos, read back, receipt in history/
photodesk delete-check --event <segment-id> --json  # delete pre-check, counts only; --verbose lists photos
photodesk records --json                        # write receipts and delete records
photodesk settings --json                       # App settings (13 fields and the library)
photodesk settings set eventHours 4             # change one; refused while PhotoDesk runs
photodesk doctor --json                         # engine, data folder, library access, cache (notes have ok: null); --ocr also writes one synthetic probe image to check OCR
```

| In the App | Command |
|---|---|
| My Timeline, switching timelines, searching segments, showing earlier segments | `timeline [--track] [--search] [--limit/--offset]` |
| View Segment | `timeline --event ID` |
| Refresh Library (⌘R), background recognition, retry failed recognition | `refresh [--enrich] [--batch] [--max-batches] [--retry-failed]` |
| Library Overview | `audit [--details]` |
| All Photos (by month, search) | `photos [--month] [--search]` |
| Generate Suggestions for Classify, Screenshots & Receipts, Sensitive Photos, Photo Titles, All Photos | `plan KIND [--limit]` (OCR kinds take `--request-id`; poll with `progress ID`) |
| Duplicate Review | `duplicates [--recommended-only]` |
| Organize History, Open Plan, Export List | `plans`, `plan-show ID [--group] [--search] [--csv-out]` |
| Selection (click/⌘/⇧, ⌘A, selected segments, duplicate preselection) | `--select ID,…`, `--select-group`, `--select-all`, `--event`, `--recommended` |
| Check and Write → Confirm Write | `apply ID …` (writes only with `--confirm`; excludes concurrent App writes) |
| Delete pre-check (⌘⌫) | `delete-check …` |
| Local records | `records [--kind apply]`, `records --kind delete` |
| Settings window | `settings`, `settings set KEY VALUE` |

What stays in the App: **deleting photos** (PhotoKit and the system confirmation live in the App; the command line stops at `delete-check`); pausing/resuming automatic organizing (state of the running App; the persistent Automatic switch is `settings set automatic`); launch at login; Open in Photos, opening Photos, revealing records in Finder and privacy-pane links; importing the acceptance test photo; and interface gestures such as Space preview, zoom, video playback, grid size, live appearance changes, shortcut recording and cancelling a task. `settings set` accepts only values the Settings window can produce and refuses while PhotoDesk runs (the running App would overwrite the change). `photos` saves no plan; use `plan library` before a delete pre-check.

Old command names remain as aliases of the same flow: `classify-plan`/`title-plan` = `plan classify|title`, `triage`/`ocr-scan` = `plan triage|sensitive` (with `--apply`, the new plan is then written in full), `classify-apply`/`title-apply` = `apply <latest plan of that kind> --select-all` (writes only with `--apply`). Old CSV plans are retired; titles are only suggested for untitled photos, and screenshot triage no longer creates a delete album. Command-line-only tools: `backup`, `ocr-extract`, `shared-list`, `dedup-export` and `reconcile`, with output in `~/Library/Application Support/PhotoDesk/cli/`. `reconcile` (read-only), `shared-list` (writes the shared-album checklist) and `dedup-export` take `--json`; `backup` and `ocr-extract` are long tasks and print text progress only. They read a private YAML file (`--config` or `PHOTOCLI_CONFIG`, by default `cli-config.yaml` in the data directory, else neutral bundled defaults). When `--config` is passed explicitly, its `library` also applies to the other commands. Personal configuration is never included in the App or public repository.

The JSON pipe between the App and its engine (no arguments, request on stdin) is the App's internal contract: it exits 0 even on failure and the App reads the error from the JSON. Agents should use the commands above.

## Build and verification

```bash
# Run from the repository root
uv sync --locked --group build
uv run python -m unittest discover -s tests -v
bash build.sh                 # 构建内置引擎、SwiftUI、签名、安装
bash build.sh --no-install    # 仅生成应用
```

Xcode selection and icon generation reuse existing shared engines. Build output is `build/DerivedData/Build/Products/Release/PhotoDesk.app`. The local edition is for Apple Silicon and locally signed; it has not been released through the App Store or notarized for distribution.

Engine diagnostics: `photodesk doctor --ocr --json`. For the App's internal contract, `build/engine/photo-engine/photo-engine` accepts JSON on stdin, for example `{"command":"audit"}` and `{"command":"ocr-probe"}`. Read-only analysis results can be verified through actual Swift models and decoders using `tests/contract_check.swift`. Writes to the original library must not be used as unattended test data.

Third-party sources: [osxphotos](https://github.com/RhetTbull/osxphotos), [PyInstaller packaging guide](https://pyinstaller.org/en/stable/usage.html). osxphotos 0.76.1 includes preliminary macOS 27 compatibility fixes; validation against the actual system is still required.

## Direct distribution and website

`python3 scripts/release.py` builds without installing, generating a ZIP, SHA-256, and `release.json` in `dist/`. It checks the bundled runtime, synthetic OCR, missing-library behavior, and error contract from a relocated app package. Read-only checks do not access system photos and do not replace first-time permissions, GUI verification, or deletion/recovery verification on a new computer. Third-party licenses are bundled; source is available in the [existing public repository](https://github.com/zengtianli/photo-desk).

`python3 scripts/build_site.py --preview` generates a light-theme preview in `build/site/`. See [docs/demo/README.md](docs/demo/README.md) for real screenshots, videos, and evidence requirements. Production `python3 scripts/build_site.py` requires a complete release package and verified real media. Public files are passed to the existing site deployment entry point through the `site-manifest.json` allowlist; source directories and raw recordings must not be synced.

The distributed version defaults to empty pet names while retaining existing saved settings. `PHOTODESK_PREFERENCES_SUITE`, `PHOTODESK_DATA_ROOT`, and `PHOTODESK_DEMO_ROOT` support isolated synthetic verification. Demo isolation strictly rejects connecting to or modifying the system Photos library; it is not a general folder-import feature.

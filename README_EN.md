# PhotoDesk

[中文](README.md) | **English**

A native macOS photo timeline. On launch it automatically scans the entire library, connects everyday life, cats, people, meetings, and documents, and prepares duplicate-photo cleanup suggestions.

Product website and installation guide: [PhotoDesk](https://app-mac-photodesk.tianli.cyou/). Verify the website’s publication status by visiting it.

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
- `vendor/photocli/` is a verifiable source snapshot of the original apple/photo engine. Normal builds use only this repository’s snapshot rather than importing another app. `scripts/vendor_engine.py --sync` is the explicit update entry point, with source-file hashes recorded in the manifest. Business algorithm fixes are made in the apple/photo original and then synced into the snapshot.

## Build and verification

```bash
cd /Users/tianli/Apps/photo-desk
uv sync --locked --group build
uv run python -m unittest discover -s tests -v
bash build.sh                 # 构建内置引擎、SwiftUI、签名、安装
bash build.sh --no-install    # 仅生成应用
```

Xcode selection and icon generation reuse existing shared engines. Build output is `build/DerivedData/Build/Products/Release/PhotoDesk.app`. The local edition is for Apple Silicon and locally signed; it has not been released through the App Store or notarized for distribution.

Engine diagnostics: `build/engine/photo-engine/photo-engine` accepts JSON on stdin, for example `{"command":"audit"}` and `{"command":"ocr-probe"}`. Read-only analysis results can be verified through actual Swift models and decoders using `tests/contract_check.swift`. Writes to the original library must not be used as unattended test data.

Third-party sources: [osxphotos](https://github.com/RhetTbull/osxphotos), [PyInstaller packaging guide](https://pyinstaller.org/en/stable/usage.html). osxphotos 0.76.1 includes preliminary macOS 27 compatibility fixes; validation against the actual system is still required.

## Direct distribution and website

`python3 scripts/release.py` builds without installing, generating a ZIP, SHA-256, and `release.json` in `dist/`. It checks the bundled runtime, synthetic OCR, missing-library behavior, and error contract from a relocated app package. Read-only checks do not access system photos and do not replace first-time permissions, GUI verification, or deletion/recovery verification on a new computer. Third-party licenses are bundled; product source remains private.

`python3 scripts/build_site.py --preview` generates a light-theme preview in `build/site/`. See [docs/demo/README.md](docs/demo/README.md) for real screenshots, videos, and evidence requirements. Production `python3 scripts/build_site.py` requires a complete release package and verified real media. Public files are passed to the existing site deployment entry point through the `site-manifest.json` allowlist; source directories and raw recordings must not be synced.

The distributed version defaults to empty pet names while retaining existing saved settings. `PHOTODESK_PREFERENCES_SUITE`, `PHOTODESK_DATA_ROOT`, and `PHOTODESK_DEMO_ROOT` support isolated synthetic verification. Demo isolation strictly rejects connecting to or modifying the system Photos library; it is not a general folder-import feature.

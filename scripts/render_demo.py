#!/usr/bin/env python3
"""Caption reviewed real PhotoDesk recordings. Never draw or replace product pixels.

Use /opt/homebrew/bin/python3 (Pillow), ffmpeg and ffprobe. The edit plan records
observed capture facts and exact raw-file cuts; missing facts fail closed.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "build/tutorial/raw"
OUT = ROOT / "docs/demo"
WORK = ROOT / "build/tutorial/edit"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
WIDTH, VIEW_HEIGHT, HEADER_HEIGHT, FOOTER_HEIGHT = 1280, 864, 64, 168
SCENES = ("timeline", "review")
SCREENSHOTS = ("timeline.png", "preview.png")


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    subprocess.run(args, check=True)


def probe(path):
    return json.loads(subprocess.check_output([FFPROBE, "-v", "error", "-show_streams",
        "-show_format", "-of", "json", str(path)], text=True))


def stamp(seconds):
    n = round(seconds * 1000)
    return f"{n // 3600000:02}:{n // 60000 % 60:02}:{n // 1000 % 60:02}.{n % 1000:03}"


def band(height, lines):
    canvas = Image.new("RGB", (WIDTH, height), "#edf6f2")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, 3), fill="#76a99a")
    for text, position, size, color, right in lines:
        font = ImageFont.truetype(FONT, size)
        bounds = draw.multiline_textbbox(position, text, font=font, spacing=8)
        require(bounds[2] <= right and bounds[3] <= height - 12, "Caption exceeds its safe area: " + text)
        draw.multiline_text(position, text, font=font, fill=color, spacing=8)
    return canvas


def captions(chapter, title, subtitle, mode, trimmed):
    label = mode + " · 原速" + (" · 已剪去等待" if trimmed else "")
    header = band(HEADER_HEIGHT, [
        ("PhotoDesk  " + chapter, (30, 18), 25, "#205e56", 770),
        (label, (800, 23), 19, "#56756c", WIDTH - 26),
    ])
    footer = band(FOOTER_HEIGHT, [
        (title, (32, 24), 35, "#205e56", WIDTH - 28),
        (subtitle, (32, 91), 23, "#56756c", WIDTH - 28),
    ])
    return header, footer


def plan_digest(plan):
    # Review may be completed after rendering; cuts/capture facts remain fixed.
    content = {k: v for k, v in plan.items() if k != "review"}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scene_sources(scene):
    supplements = scene.get("supplements", {})
    require(isinstance(supplements, dict) and "main" not in supplements, "Supplement sources need distinct names.")
    return {"main": scene, **supplements}


def load_plan(path):
    plan = json.loads(path.read_text())
    recording = plan.get("recording", {})
    require(recording.get("source") == "real-app-window", "Capture must be a real application window.")
    require(recording.get("synthetic_inputs") is True, "Only isolated synthetic inputs may be published.")
    for key in ("recorded_version", "recorded_build", "release_sha256", "macos", "chip", "recorded_at"):
        require(isinstance(recording.get(key), str) and recording[key].strip(), "Missing observed recording fact: " + key)
    release = json.loads((ROOT / "dist/release.json").read_text())
    require((recording["recorded_version"], recording["recorded_build"], recording["release_sha256"]) ==
            (release["version"], str(release["build"]), release["sha256"]),
            "The observed recording does not match the frozen distribution.")
    require(set(plan.get("scenes", {})) == set(SCENES), "Supply exactly timeline and review scenes.")
    for name, scene in plan["scenes"].items():
        sources, facts = scene_sources(scene), {}
        for source_id, source in sources.items():
            filename = source.get("raw_file", "")
            require(filename and Path(filename).name == filename, "Raw recordings must be basenames under build/tutorial/raw.")
            raw = RAW / filename
            require(raw.is_file() and not raw.is_symlink(), "Missing original recording: " + filename)
            info = probe(raw)
            streams = [s for s in info["streams"] if s["codec_type"] == "video"]
            require(len(streams) == 1, "Expected one real video stream: " + filename)
            audio = any(s["codec_type"] == "audio" for s in info["streams"])
            require(recording.get("audio_policy") in ("no-audio", "mute"), "Record the actual audio policy.")
            require(not audio or recording["audio_policy"] == "mute", "Source contains audio; its removal must be explicit.")
            video = streams[0]
            require(source.get("raw_geometry") == [video["width"], video["height"]], "Source geometry was not reviewed: " + filename)
            require(source.get("raw_sha256") == sha(raw), "Original recording hash was not reviewed: " + filename)
            if source_id != "main":
                require("补拍" in source.get("chapter", ""), "Supplementary capture must be visibly labelled.")
            facts[source_id] = (video, float(info["format"]["duration"]))
        cuts = scene.get("segments", [])
        require(cuts and scene.get("independent_result"), "Supply reviewed cuts and observed results: " + name)
        previous = {source_id: 0.0 for source_id in sources}
        for cut in cuts:
            source_id = cut.get("source", "main")
            require(source_id in sources, "Unknown source in cut: " + source_id)
            source = sources[source_id]
            video, duration = facts[source_id]
            start, end = cut["start"], cut["end"]
            require(0 <= previous[source_id] <= start < end <= duration, "Cuts must be ordered, nonoverlapping and inside each source.")
            previous[source_id] = end
            rect = cut.get("crop") or source["window_crop"]
            require(len(rect) == 4 and all(type(n) is int for n in rect), "Crop must be four integer pixels.")
            x, y, width, height = rect
            require(x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= video["width"] and y + height <= video["height"], "Crop escapes the recording.")
            require(cut.get("title") and cut.get("subtitle"), "Every cut needs factual captions.")
            captions(source["chapter"], cut["title"], cut["subtitle"], "真实窗口" if rect == source["window_crop"] else "局部放大", True)
        retained = sum(c["end"] - c["start"] for c in cuts)
        require(0 <= scene["poster_time"] < retained, "Poster time must be inside the edited video.")
    return plan


def decode_check(path, log):
    result = subprocess.run([FFMPEG, "-hide_banner", "-v", "info", "-i", str(path),
        "-vf", f"crop={WIDTH}:{VIEW_HEIGHT}:0:{HEADER_HEIGHT},blackdetect=d=0.2:pic_th=0.98:pix_th=0.10",
        "-an", "-f", "null", "-"], capture_output=True, text=True)
    log.write_text(result.stderr)
    require(result.returncode == 0 and "black_start:" not in result.stderr, "Decode/black-frame check failed: " + path.name)
    info = probe(path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    require((video["codec_name"], video["pix_fmt"], video["width"], video["height"]) ==
            ("h264", "yuv420p", WIDTH, HEADER_HEIGHT + VIEW_HEIGHT + FOOTER_HEIGHT), "Unexpected delivery format.")
    return {"duration": float(info["format"]["duration"]), "sha256": sha(path), "bytes": path.stat().st_size,
            "decode": "passed", "black_frames": "none >= 0.2s at 98% of product-image area"}


def render(plan):
    work = WORK / plan_digest(plan)[:12]
    work.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    screenshots = {name: sha(OUT / name) for name in SCREENSHOTS if (OUT / name).is_file()}
    entries = {}
    for name in SCENES:
        scene = plan["scenes"][name]
        sources = scene_sources(scene)
        source_facts = {key: {"raw_file": source["raw_file"], "raw_sha256": sha(RAW / source["raw_file"]),
            "raw_duration": float(probe(RAW / source["raw_file"])["format"]["duration"]),
            "supplementary_capture": key != "main"} for key, source in sources.items()}
        for key, facts in source_facts.items():
            kept = sum(c["end"] - c["start"] for c in scene["segments"] if c.get("source", "main") == key)
            facts["removed_seconds"] = round(facts["raw_duration"] - kept, 3)
        trimmed = any(facts["removed_seconds"] > 0.1 for facts in source_facts.values())
        parts, cuts, cues, elapsed = [], [], [], 0.0
        for index, cut in enumerate(scene["segments"]):
            source_id = cut.get("source", "main")
            source = sources[source_id]
            raw = RAW / source["raw_file"]
            rect = cut.get("crop") or source["window_crop"]
            x, y, width, height = rect
            mode = "真实窗口" if rect == source["window_crop"] else "局部放大"
            header, footer = captions(source["chapter"], cut["title"], cut["subtitle"], mode, trimmed)
            prefix = work / f"{name}-{index}"
            header.save(prefix.with_suffix(".header.png")); footer.save(prefix.with_suffix(".footer.png"))
            part = prefix.with_suffix(".mp4")
            filters = (f"[0:v]crop={width}:{height}:{x}:{y},setpts=PTS-STARTPTS,"
                f"scale={WIDTH}:{VIEW_HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={WIDTH}:{VIEW_HEIGHT}:(ow-iw)/2:(oh-ih)/2:white,setsar=1,fps=30[v];"
                "[1:v][v][2:v]vstack=inputs=3[out]")
            run(FFMPEG, "-y", "-v", "error", "-ss", str(cut["start"]), "-i", str(raw),
                "-loop", "1", "-framerate", "30", "-i", str(prefix.with_suffix(".header.png")),
                "-loop", "1", "-framerate", "30", "-i", str(prefix.with_suffix(".footer.png")),
                "-filter_complex", filters, "-map", "[out]", "-an", "-t", str(cut["end"] - cut["start"]),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-map_metadata", "-1", "-movflags", "+faststart", str(part))
            duration = float(probe(part)["format"]["duration"])
            cues.append(f"{stamp(elapsed)} --> {stamp(elapsed + duration)}\n{source['chapter']} · {cut['title']}\n{cut['subtitle']}")
            cuts.append(dict(cut, source=source_id, crop=rect, view=mode, speed=1, output_start=round(elapsed, 3), output_end=round(elapsed + duration, 3)))
            elapsed += duration; parts.append(part)
        listing = work / f"{name}-concat.txt"
        # All generated filenames are fixed names under a hash directory, without shell quoting.
        listing.write_text("".join(f"file '{part.name}'\n" for part in parts))
        target = OUT / f"{name}.mp4"
        run(FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "1", "-i", str(listing),
            "-c", "copy", "-map_metadata", "-1", "-movflags", "+faststart", str(target))
        poster = OUT / f"{name}-poster.jpg"
        run(FFMPEG, "-y", "-v", "error", "-ss", str(scene["poster_time"]), "-i", str(target), "-frames:v", "1", "-q:v", "2", str(poster))
        (OUT / f"{name}.vtt").write_text("WEBVTT\n\n" + "\n\n".join(cues) + "\n")
        entries[name] = {"sources": source_facts, "cuts": cuts,
            "poster_time": scene["poster_time"], "poster_sha256": sha(poster),
            "independent_result": scene["independent_result"], "checks": decode_check(target, work / f"{name}-decode.log")}
    for name, before in screenshots.items():
        require(sha(OUT / name) == before, "Root-owned screenshot changed: " + name)
    for name in SCENES:
        for source in scene_sources(plan["scenes"][name]).values():
            require(sha(RAW / source["raw_file"]) == source["raw_sha256"], "Original recording changed.")
    report = {"product": "PhotoDesk", "recording": plan["recording"], "edit_plan_sha256": plan_digest(plan),
        "editing": {"caption_bands_outside_product_image": True, "retained_footage_speed": 1,
                    "local_zoom_labelled": True, "removed_waits_labelled": True},
        "scenes": entries, "final_visual_review": "pending-review"}
    (OUT / "recording.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: scene["checks"] for name, scene in entries.items()}, ensure_ascii=False, indent=2))


def finalize(plan):
    review = plan.get("review", {})
    require(review.get("privacy_reviewed") is True and review.get("final_visual_review") is True,
            "Final evidence requires actual privacy and final-frame review.")
    require(review.get("reviewer_role") in ("recording-owner", "media-reviewer"), "Record who reviewed the final media.")
    require(isinstance(review.get("caption"), str) and review["caption"].strip(), "Record the actual editing/coverage caption.")
    report = json.loads((OUT / "recording.json").read_text())
    require(report["edit_plan_sha256"] == plan_digest(plan), "The edit plan changed after rendering.")
    for name in SCENES:
        require(sha(OUT / f"{name}.mp4") == report["scenes"][name]["checks"]["sha256"], "Edited video changed.")
        require(sha(OUT / f"{name}-poster.jpg") == report["scenes"][name]["poster_sha256"], "Poster changed.")
    names = [*SCREENSHOTS, *[f"{name}{suffix}" for name in SCENES for suffix in (".mp4", "-poster.jpg")]]
    evidence = {"recorded_version": plan["recording"]["recorded_version"], "recorded_build": plan["recording"]["recorded_build"],
        "release_sha256": plan["recording"]["release_sha256"], "synthetic_inputs": True, "privacy_reviewed": True,
        "caption": review["caption"], "files": [{"path": name, "sha256": sha(OUT / name)} for name in names]}
    (OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    report["final_visual_review"] = "confirmed-by-" + review["reviewer_role"]
    (OUT / "recording.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("Final evidence written; no website was built or deployed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=OUT / "edit-plan.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--layout-preview", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.layout_preview:
        WORK.mkdir(parents=True, exist_ok=True)
        header, footer = captions("字幕样式预览", "先看清照片，再决定如何整理", "仅字幕色带，不是产品画面；操作字幕以实际原片为准。", "样式预览", False)
        header.save(WORK / "caption-header-preview.png"); footer.save(WORK / "caption-footer-preview.png")
        print(WORK); return
    plan = load_plan(args.plan)
    if args.check_only:
        print("PASS observed version/build/hash, original hashes, cuts, geometry and caption safe areas")
    elif args.finalize:
        finalize(plan)
    else:
        render(plan)


if __name__ == "__main__":
    main()

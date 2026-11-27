#!/usr/bin/env python3
"""Structural check for exported subtitle files: check_subtitle.py <srt|vtt|ass> <file>."""
import re
import sys

fmt, path = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
errors = []
if fmt == "vtt":
    if not text.startswith("WEBVTT"):
        errors.append("missing WEBVTT header")
    times = re.findall(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}", text, re.M)
elif fmt == "srt":
    times = re.findall(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$", text, re.M)
elif fmt == "ass":
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        if section not in text:
            errors.append(f"missing {section}")
    if not text.startswith("[Script Info]\nScriptType: v4.00+"):
        errors.append("header must start with [Script Info] / ScriptType: v4.00+")
    times = re.findall(r"^Dialogue: 0,(\d+:\d{2}:\d{2}\.\d{2}),(\d+:\d{2}:\d{2}\.\d{2}),Caption\d+,", text, re.M)
    styles = re.findall(r"^Style: Caption\d+,", text, re.M)
    if len(styles) != len(times):
        errors.append(f"{len(styles)} styles for {len(times)} dialogues")
    bad = [line for line in text.splitlines() if line.startswith("Dialogue:") and line.count(",") < 9]
    if bad:
        errors.append(f"malformed dialogue lines: {bad[:2]}")
else:
    sys.exit(f"unknown format {fmt}")
if not times:
    errors.append("no cue timing lines found")
print(f"{fmt} {path}: cues={len(times)} " + ("OK" if not errors else "FAIL " + "; ".join(errors)))
sys.exit(1 if errors else 0)

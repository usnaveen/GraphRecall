#!/usr/bin/env python3
"""Re-apply WebAssets (graph_force.html + boot.js + css) into project.pbxproj.

xcodegen generate wipes custom Resources entries. After regenerating:

    cd ios && xcodegen generate && python3 _patch_resources.py

Uses stable hex IDs A11A… / B11B… / C11C… so diffs stay deterministic.
"""
from pathlib import Path
import re

pbx = Path(__file__).resolve().parent / "GraphRecall.xcodeproj" / "project.pbxproj"
text = pbx.read_text()
if "graph_force.html in Resources" in text and "C11C11C11C11C11C11C11C01 /* WebAssets */," in text:
    print("already ok")
    raise SystemExit(0)

HTML_REF = "A11A11A11A11A11A11A11A01"
JS_REF = "A11A11A11A11A11A11A11A02"
CSS_REF = "A11A11A11A11A11A11A11A03"
HTML_BF = "B11B11B11B11B11B11B11B01"
JS_BF = "B11B11B11B11B11B11B11B02"
CSS_BF = "B11B11B11B11B11B11B11B03"
GROUP = "C11C11C11C11C11C11C11C01"

# Wipe prior partial patches so re-runs are idempotent.
for token in [HTML_REF, JS_REF, CSS_REF, HTML_BF, JS_BF, CSS_BF, GROUP]:
    text = re.sub(rf"^\t\t{token} /\*.*?\n(?:\t\t\t.*?\n)*\t\t\}};\n", "", text, flags=re.M)
    text = re.sub(rf"^\t\t{token} /\*.*?\}};\n", "", text, flags=re.M)
    text = text.replace(f"\t\t\t\t{token} /* WebAssets */,\n", "")
    for name in [
        "graph_force.html in Resources",
        "graph_force_boot.js in Resources",
        "graph_force.css in Resources",
        "graph_force.html",
        "graph_force_boot.js",
        "graph_force.css",
        "WebAssets",
    ]:
        text = text.replace(f"\t\t\t\t{token} /* {name} */,\n", "")

bf = (
    f"\t\t{HTML_BF} /* graph_force.html in Resources */ = {{isa = PBXBuildFile; fileRef = {HTML_REF} /* graph_force.html */; }};\n"
    f"\t\t{JS_BF} /* graph_force_boot.js in Resources */ = {{isa = PBXBuildFile; fileRef = {JS_REF} /* graph_force_boot.js */; }};\n"
    f"\t\t{CSS_BF} /* graph_force.css in Resources */ = {{isa = PBXBuildFile; fileRef = {CSS_REF} /* graph_force.css */; }};\n"
)
fr = (
    f"\t\t{HTML_REF} /* graph_force.html */ = {{isa = PBXFileReference; lastKnownFileType = text.html; path = graph_force.html; sourceTree = \"<group>\"; }};\n"
    f"\t\t{JS_REF} /* graph_force_boot.js */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.javascript; path = graph_force_boot.js; sourceTree = \"<group>\"; }};\n"
    f"\t\t{CSS_REF} /* graph_force.css */ = {{isa = PBXFileReference; lastKnownFileType = text.css; path = graph_force.css; sourceTree = \"<group>\"; }};\n"
)
grp = (
    f"\t\t{GROUP} /* WebAssets */ = {{\n"
    f"\t\t\tisa = PBXGroup;\n"
    f"\t\t\tchildren = (\n"
    f"\t\t\t\t{HTML_REF} /* graph_force.html */,\n"
    f"\t\t\t\t{JS_REF} /* graph_force_boot.js */,\n"
    f"\t\t\t\t{CSS_REF} /* graph_force.css */,\n"
    f"\t\t\t);\n"
    f"\t\t\tpath = WebAssets;\n"
    f"\t\t\tsourceTree = \"<group>\";\n"
    f"\t\t}};\n"
)

text = text.replace("/* Begin PBXBuildFile section */\n", "/* Begin PBXBuildFile section */\n" + bf)
text = text.replace("/* Begin PBXFileReference section */\n", "/* Begin PBXFileReference section */\n" + fr)
text = text.replace("/* Begin PBXGroup section */\n", "/* Begin PBXGroup section */\n" + grp)

insert = (
    f"\t\t\t\t{HTML_BF} /* graph_force.html in Resources */,\n"
    f"\t\t\t\t{JS_BF} /* graph_force_boot.js in Resources */,\n"
    f"\t\t\t\t{CSS_BF} /* graph_force.css in Resources */,\n"
)
m = re.search(r"(/\* Resources \*/ = \{\s*isa = PBXResourcesBuildPhase;\s*buildActionMask = \d+;\s*files = \(\n)", text)
if not m:
    raise SystemExit("Resources build phase not found")
text = text[: m.end()] + insert + text[m.end() :]

# Parent under main group as sibling of GraphRecall (children listing form).
web_child = f"\t\t\t\t{GROUP} /* WebAssets */,\n"
if web_child not in text:
    m = re.search(r"([A-F0-9]{24} /\* GraphRecall \*/,\n)", text)
    if not m:
        raise SystemExit("GraphRecall child not found")
    text = text[: m.start()] + web_child + text[m.start() :]

pbx.write_text(text)
print("patched clean")

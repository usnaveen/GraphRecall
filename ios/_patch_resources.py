#!/usr/bin/env python3
"""Re-apply WebAssets (graph_force.html + graph_force_boot.js) into project.pbxproj.

xcodegen generate wipes custom Resources entries. After regenerating:

    cd ios && xcodegen generate && python3 _patch_resources.py

Uses stable hex IDs A11A… / B11B… / C11C… so diffs stay deterministic.
"""
from pathlib import Path
import re

pbx = Path(__file__).resolve().parent / "GraphRecall.xcodeproj" / "project.pbxproj"
text = pbx.read_text()
if "graph_force.html in Resources" in text:
    print("already ok")
    raise SystemExit(0)

HTML_REF = "A11A11A11A11A11A11A11A01"
JS_REF = "A11A11A11A11A11A11A11A02"
HTML_BF = "B11B11B11B11B11B11B11B01"
JS_BF = "B11B11B11B11B11B11B11B02"
GROUP = "C11C11C11C11C11C11C11C01"

bf = (
    f"\t\t{HTML_BF} /* graph_force.html in Resources */ = {{isa = PBXBuildFile; fileRef = {HTML_REF} /* graph_force.html */; }};\n"
    f"\t\t{JS_BF} /* graph_force_boot.js in Resources */ = {{isa = PBXBuildFile; fileRef = {JS_REF} /* graph_force_boot.js */; }};\n"
)
fr = (
    f"\t\t{HTML_REF} /* graph_force.html */ = {{isa = PBXFileReference; lastKnownFileType = text.html; path = graph_force.html; sourceTree = \"<group>\"; }};\n"
    f"\t\t{JS_REF} /* graph_force_boot.js */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.javascript; path = graph_force_boot.js; sourceTree = \"<group>\"; }};\n"
)
grp = (
    f"\t\t{GROUP} /* WebAssets */ = {{\n"
    f"\t\t\tisa = PBXGroup;\n"
    f"\t\t\tchildren = (\n"
    f"\t\t\t\t{HTML_REF} /* graph_force.html */,\n"
    f"\t\t\t\t{JS_REF} /* graph_force_boot.js */,\n"
    f"\t\t\t);\n"
    f"\t\t\tpath = WebAssets;\n"
    f"\t\t\tsourceTree = \"<group>\";\n"
    f"\t\t}};\n"
)

text = text.replace("/* Begin PBXBuildFile section */\n", "/* Begin PBXBuildFile section */\n" + bf)
text = text.replace("/* Begin PBXFileReference section */\n", "/* Begin PBXFileReference section */\n" + fr)
text = text.replace("/* Begin PBXGroup section */\n", "/* Begin PBXGroup section */\n" + grp)

old = "\t\t\t\tB9F72CD6D433BE39DA5BB103 /* Assets.xcassets in Resources */,\n"
new = (
    old
    + f"\t\t\t\t{HTML_BF} /* graph_force.html in Resources */,\n"
    + f"\t\t\t\t{JS_BF} /* graph_force_boot.js in Resources */,\n"
)
if old in text:
    text = text.replace(old, new, 1)
else:
    m = re.search(r"(files = \(\n)(\t\t\t\t[A-F0-9]+ /\* Assets\.xcassets in Resources \*/,\n)", text)
    if not m:
        m = re.search(r"(/\* Resources \*/ = \{\s*isa = PBXResourcesBuildPhase;\s*buildActionMask = \d+;\s*files = \(\n)", text)
        if not m:
            raise SystemExit("Resources build phase not found")
        insert = (
            f"\t\t\t\t{HTML_BF} /* graph_force.html in Resources */,\n"
            f"\t\t\t\t{JS_BF} /* graph_force_boot.js in Resources */,\n"
        )
        text = text[: m.end()] + insert + text[m.end() :]
    else:
        text = text.replace(old if old in text else m.group(0), (old if old in text else m.group(0)) + f"\t\t\t\t{HTML_BF} /* graph_force.html in Resources */,\n\t\t\t\t{JS_BF} /* graph_force_boot.js in Resources */,\n", 1)

m = re.search(r"([A-F0-9]{24} /\* GraphRecall \*/,\n)", text)
if not m:
    raise SystemExit("GraphRecall child not found")
if f"{GROUP} /* WebAssets */" not in text:
    text = text[: m.start()] + f"\t\t\t\t{GROUP} /* WebAssets */,\n" + text[m.start() :]

pbx.write_text(text)
print("patched clean")

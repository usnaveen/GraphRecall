"""Check the test-set labels by hand (about 5 minutes for 160 questions).

    python3 eval/router/label.py            # only rows not yet human-checked
    python3 eval/router/label.py --all      # go through everything again
    python3 eval/router/label.py --write    # type your own real questions -> data/human.jsonl
                                            # (the clean set: score it once with train.py --eval-set human)

For each question: press Enter to keep the proposed label, type a number to change it,
s to skip, q to save and quit. Checked rows get label_source "human"; train.py reports how many
test labels are human-checked, so results can say whether the gold labels are trustworthy.
"""
import json
import sys
from pathlib import Path

PATH = Path(__file__).parent / "data" / "test.jsonl"
CLASSES = ["explain", "compare", "find", "summarize", "quiz", "path", "show_images", "general"]
HELP = {
    "explain": "explain a concept",
    "compare": "compare two or more things",
    "find": "look up something in MY notes",
    "summarize": "overview/summary of a topic or of my notes",
    "quiz": "test me / practice questions",
    "path": "what to learn first/next, prerequisites",
    "show_images": "show diagrams, figures, photos",
    "general": "chit-chat, app questions, no retrieval",
}


def write_mode() -> None:
    out = PATH.parent / "human.jsonl"
    print("Type a question you would really ask, then its label number. Empty question = done.")
    print("  ".join(f"{i}={c}" for i, c in enumerate(CLASSES)))
    n = 0
    with out.open("a") as f:
        while True:
            text = input("\nquestion> ").strip()
            if not text:
                break
            lab = input("label #> ").strip()
            if not (lab.isdigit() and int(lab) < len(CLASSES)):
                print("skipped (need a number 0-7)")
                continue
            f.write(json.dumps({"text": text, "intent": CLASSES[int(lab)], "label_source": "human"}) + "\n")
            n += 1
    print(f"added {n} to {out}")


def main() -> None:
    if "--write" in sys.argv:
        write_mode()
        return
    redo = "--all" in sys.argv
    rows = [json.loads(line) for line in PATH.open()]
    menu = "  ".join(f"{i}={c}" for i, c in enumerate(CLASSES))
    print("Labels:")
    for c in CLASSES:
        print(f"  {CLASSES.index(c)} {c:<12} {HELP[c]}")
    todo = [r for r in rows if redo or r.get("label_source") != "human"]
    print(f"\n{len(todo)} to check. Enter = keep, number = change, s = skip, q = save and quit\n")
    for n, r in enumerate(todo, 1):
        print(f"[{n}/{len(todo)}] {r['text']}\n    proposed: {r['intent']}   ({menu})")
        ans = input("> ").strip().lower()
        if ans == "q":
            break
        if ans == "s":
            continue
        if ans.isdigit() and int(ans) < len(CLASSES):
            r["intent"] = CLASSES[int(ans)]
        r["label_source"] = "human"
    with PATH.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    done = sum(r.get("label_source") == "human" for r in rows)
    print(f"saved. {done}/{len(rows)} test labels are human-checked.")


if __name__ == "__main__":
    main()

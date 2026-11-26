"""The showcase learner's resume (fictional: Jordan Avery, scripts/showcase_account.py).

Skills are picked from the showcase graph so the resume viewer has every colour to show: language
models (strong), algorithms (mixed), MLOps and serving (weak), and a few tools the graph has never
seen (new). Every name, employer and school here is made up.

    PYTHONPATH=. .venv/bin/python scripts/showcase_resume.py --out /path/jordan-avery-resume.pdf [--upload]

--upload posts the text as the showcase learner (Bearer showcase-token, local DEBUG API) and prints
the resume id; the app shows the original PDF when it is saved under that id on the device.
"""

from __future__ import annotations

import argparse
import json
import urllib.request

import pymupdf

HTML = """
<h1>Jordan Avery</h1>
<p class="role">Machine Learning Engineer · Seattle, WA</p>
<hr/>
<h2>Summary</h2>
<p>Machine learning engineer focused on language models and retrieval. Three years shipping NLP
features end to end, from tokenization and fine-tuning to evaluation and serving.</p>

<h2>Experience</h2>
<p class="job"><b>Machine Learning Engineer</b>, Northwind Analytics <span class="when">2023 – present</span></p>
<ul>
<li>Fine-tuned an open-weight decoder-only transformer with LoRA for support-ticket triage, cutting manual routing by 38%.</li>
<li>Built hybrid search over 2M documents (BM25 with an HNSW vector index and reranking) and added retrieval-augmented generation for agent answers.</li>
<li>Set up a feature store and model registry for the training pipeline, with continuous training on weekly data.</li>
<li>Served models on a single GPU using model quantization and KV cache tuning.</li>
</ul>
<p class="job"><b>Data Scientist</b>, Harbor &amp; Finch <span class="when">2021 – 2023</span></p>
<ul>
<li>Sentiment analysis and machine translation quality checks for product reviews in six languages.</li>
<li>Churn models with logistic regression and random forest; maintained the ETL and streaming pipeline in Airflow.</li>
</ul>

<h2>Projects</h2>
<ul>
<li><b>Pocket translator.</b> Sequence-to-sequence LSTM with attention and byte-pair encoding, evaluated with BLEU.</li>
<li><b>Judge study.</b> Few-shot prompting benchmark comparing pairwise comparison with Likert scale ratings.</li>
</ul>

<h2>Skills</h2>
<p><b>Language models:</b> Transformers, Positional Encoding, LoRA, Byte-Pair Encoding, Word Embeddings, Few-Shot Prompting</p>
<p><b>Retrieval:</b> Hybrid Search, HNSW, Cosine Similarity, Approximate Nearest Neighbor, Retrieval-Augmented Generation</p>
<p><b>MLOps:</b> Feature Store, Model Registry, Continuous Training, ZenML, Docker, Kubernetes, Terraform</p>
<p><b>Systems:</b> Model Parallelism, Tensor Parallelism, Model Quantization, KV Cache</p>
<p><b>Languages and tools:</b> Python, PyTorch, SQL, PostgreSQL</p>

<h2>Education</h2>
<p class="job"><b>M.S. Computer Science</b>, Northfield University <span class="when">2021</span></p>
<p class="job"><b>B.S. Mathematics</b>, Northfield University <span class="when">2019</span></p>
"""

CSS = """
* { font-family: sans-serif; color: #1d1d1f; }
h1 { font-size: 22pt; margin: 0 0 2pt 0; }
.role { font-size: 10.5pt; color: #555; margin: 0 0 6pt 0; }
h2 { font-size: 11pt; color: #2b6f3e; margin: 10pt 0 3pt 0; text-transform: uppercase; letter-spacing: 1pt; }
p, li { font-size: 9.6pt; line-height: 1.35; margin: 0 0 3pt 0; }
ul { margin: 0 0 4pt 12pt; }
.job { margin-top: 4pt; }
.when { color: #777; }
hr { color: #c9d6cc; }
"""


def build(out: str) -> str:
    story = pymupdf.Story(html=HTML, user_css=CSS)
    writer = pymupdf.DocumentWriter(out)
    page = pymupdf.paper_rect("letter")
    where = page + (54, 50, -54, -50)
    more = True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    with pymupdf.open(out) as doc:
        return "\n".join(p.get_text() for p in doc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--api", default="http://localhost:8001")
    args = ap.parse_args()
    text = build(args.out)
    print(f"wrote {args.out} ({len(text)} chars of text)")
    if args.upload:
        body = json.dumps({"text": text, "file_name": "Jordan Avery - Resume.pdf"}).encode()
        req = urllib.request.Request(f"{args.api}/api/profile/resume", data=body, method="POST",
                                     headers={"Authorization": "Bearer showcase-token",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            view = json.load(r)
        print("resume id", view["id"], "extraction", view.get("extraction"), "counts", view.get("counts"))
        for s in view.get("skills", []):
            print(f"  {s.get('status'):10s} {s['name']}  spans={len(s.get('spans') or [])}")


if __name__ == "__main__":
    main()

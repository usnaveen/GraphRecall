"""Build the synthetic TRAINING set for the chat intent router.

Training questions come from phrasing templates x topics, with light noise (lowercase, dropped
question marks, filler words). The TEST set is NOT made here: it lives in data/test.jsonl, written
by hand in phrasings that do not reuse these templates, so the score measures generalisation rather
than template recall. Run:  python eval/router/make_dataset.py  (writes data/train.jsonl)
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
SEED = 7

TOPICS = [
    "gradient descent", "backpropagation", "the transformer architecture", "self-attention", "LoRA",
    "batch normalization", "dropout", "overfitting", "the bias-variance tradeoff", "cross-entropy loss",
    "logistic regression", "random forests", "XGBoost", "k-means clustering", "PCA", "t-SNE",
    "support vector machines", "naive Bayes", "decision trees", "reinforcement learning",
    "Q-learning", "PPO", "RLHF", "word embeddings", "BERT", "GPT", "diffusion models", "GANs",
    "variational autoencoders", "convolutional neural networks", "ResNet", "LSTMs", "RAG",
    "vector databases", "HNSW", "BM25", "reciprocal rank fusion", "knowledge graphs",
    "spaced repetition", "FSRS", "supervised learning", "unsupervised learning",
    "the sliding window technique", "two pointers", "binary search", "dynamic programming",
    "backtracking", "Dijkstra's algorithm", "topological sort", "union-find", "tries",
    "monotonic stacks", "heaps", "the two-sum problem", "LRU cache", "merge intervals",
    "BFS", "DFS", "segment trees", "bit manipulation",
    "Postgres indexes", "database normalization", "ACID transactions", "the CAP theorem",
    "consistent hashing", "rate limiting", "Kafka", "Docker", "Kubernetes", "REST vs gRPC",
    "OAuth", "JWTs", "TCP congestion control", "DNS", "TLS handshakes",
    "photosynthesis", "the Krebs cycle", "mitosis", "CRISPR", "the immune system",
    "Newton's laws", "entropy", "quantum entanglement", "special relativity", "Bayes' theorem",
    "the central limit theorem", "p-values", "confidence intervals", "A/B testing",
    "eigenvalues", "matrix multiplication", "Fourier transforms", "the chain rule",
    "the French Revolution", "the Cold War", "supply and demand", "inflation",
    "compound interest", "opportunity cost", "Stoicism", "cognitive biases",
]

PAIRS = [
    ("L1", "L2 regularization"), ("bagging", "boosting"), ("BFS", "DFS"), ("RNNs", "transformers"),
    ("precision", "recall"), ("SQL", "NoSQL databases"), ("processes", "threads"), ("TCP", "UDP"),
    ("mitosis", "meiosis"), ("SM-2", "FSRS"), ("PCA", "t-SNE"), ("Adam", "SGD"),
    ("BERT", "GPT"), ("GANs", "diffusion models"), ("HNSW", "IVFFlat"), ("BM25", "dense retrieval"),
    ("supervised", "unsupervised learning"), ("stacks", "queues"), ("arrays", "linked lists"),
    ("REST", "GraphQL"), ("Docker", "virtual machines"), ("Kafka", "RabbitMQ"),
    ("inflation", "deflation"), ("DNA", "RNA"), ("LoRA", "full fine-tuning"),
    ("dynamic programming", "greedy algorithms"), ("heaps", "balanced BSTs"),
    ("batch norm", "layer norm"), ("ReLU", "GELU"), ("bias", "variance"),
]

TEMPLATES: dict[str, list[str]] = {
    "explain": [
        "how come {t} is so effective", "what's the role of {t}", "i get lost when people talk about {t}", "what exactly is happening during {t}", "in simple words, {t}?", "why is {t} important", "can you demystify {t}", "what are the mechanics of {t}", "how is {t} computed", "tell me about {t}", "what makes {t} work", "i never really understood {t}", "shed some light on {t}", "how does {t} help",
        "what is {t}", "what is {t}?", "explain {t}", "explain {t} to me", "can you explain {t}",
        "how does {t} work", "how does {t} actually work under the hood", "help me understand {t}",
        "i don't get {t}", "break down {t} for me", "explain {t} like i'm five", "ELI5 {t}",
        "what's the intuition behind {t}", "why does {t} work", "what does {t} mean",
        "define {t}", "give me a simple explanation of {t}", "walk me through how {t} works",
        "i'm confused about {t}, can you clarify", "what's the idea behind {t}",
        "teach me {t}", "can you go deeper on {t}", "what problem does {t} solve",
        "explain the math behind {t}", "why do people use {t}", "how would you describe {t} in one paragraph",
        "what's going on in {t}", "clarify {t} please", "i keep forgetting what {t} is",
        "what is meant by {t}",
    ],
    "compare": [
        "{a} or {b}?", "{a} or {b} for my project", "should i go with {a} or {b}", "what distinguishes {a} from {b}", "is {a} better than {b}", "which one is faster, {a} or {b}", "how does {a} improve on {b}", "{a} and {b}, which wins", "what's the gap between {a} and {b}", "how do {a} and {b} relate", "would {a} or {b} make more sense here", "between {a} and {b} what would you choose",
        "{a} vs {b}", "{a} versus {b}?", "compare {a} and {b}", "what's the difference between {a} and {b}",
        "how is {a} different from {b}", "{a} or {b}, which is better", "when should i use {a} instead of {b}",
        "pros and cons of {a} vs {b}", "contrast {a} with {b}", "how do {a} and {b} differ",
        "is {a} the same as {b}", "similarities and differences between {a} and {b}",
        "{a} compared to {b}", "which should i pick, {a} or {b}", "difference {a} {b}",
        "why choose {a} over {b}", "how does {a} stack up against {b}", "tradeoffs between {a} and {b}",
        "{a} and {b}: what separates them", "are {a} and {b} related or totally different",
    ],
    "find": [
        "what did i jot down on {t}", "dig up my notes about {t}", "is {t} somewhere in my notes", "bring back what i highlighted on {t}", "what exactly did i write regarding {t}", "which upload talks about {t}", "the note on {t}, where is it", "what number did i record for {t}", "what code did i save for {t}", "show me the line where i defined {t}", "what did that article i saved say about {t}",
        "what did my notes say about {t}", "find my notes on {t}", "where did i write about {t}",
        "which note mentions {t}", "search my notes for {t}", "show me what i saved about {t}",
        "did i take notes on {t}", "look up {t} in my notes", "find the part where i wrote about {t}",
        "what was the formula for {t} in my notes", "pull up my notes about {t}",
        "what did the lecture notes say about {t}", "find the definition of {t} i saved",
        "when did i add notes on {t}", "what source did i get {t} from", "do i have anything on {t}",
        "grep my notes for {t}", "find the quote about {t}", "which article did i save about {t}",
        "what page of my notes covers {t}", "get me the snippet on {t}", "where's that thing i wrote on {t}",
        "what example did i use for {t}", "find {t}", "locate my notes covering {t}",
    ],
    "summarize": [
        "boil down my notes on {t}", "digest my notes on {t}", "{t} in a nutshell", "give me the gist of {t}", "what's the essence of my {t} notes", "briefly sum up what my notes say on {t}", "what do my notes mostly cover", "what are the recurring themes in what i've saved", "one-paragraph summary of my notes on {t}", "short rundown of everything on {t}", "what have i learned about {t} overall", "synthesize my reading on {t}", "what did i study this month", "which areas have i covered the most", "tldr my {t} notes",
        "summarize {t}", "summarize everything i know about {t}", "give me a summary of {t}",
        "tldr of {t}", "overview of {t}", "what have i been learning lately", "summarize my notes",
        "what are the main themes in my notes", "give me the big picture of {t}",
        "recap {t}", "what are the key points of {t}", "summarise my notes on {t}",
        "what topics have i covered so far", "give me a high-level overview of everything",
        "what's in my knowledge base", "condense my notes on {t}", "short summary of {t} please",
        "what are the major areas i've studied", "recap what i learned this week",
        "main takeaways from my notes on {t}", "sum up {t}", "bird's eye view of {t}",
        "what do my notes cover overall", "outline the key ideas of {t}", "cliff notes for {t}",
    ],
    "quiz": [
        "see if i remember {t}", "check whether i know {t}", "make me recall {t}", "rapid fire questions on {t}", "let's practice {t}", "give me a problem on {t}", "examine me on {t}", "i want recall practice on {t}", "fill in the blank questions on {t}", "start a review session on {t}", "ask me to explain {t}", "give me a {t} question to answer",
        "quiz me on {t}", "test me on {t}", "give me questions about {t}", "ask me about {t}",
        "make a quiz on {t}", "can you quiz me", "quiz me", "test my knowledge of {t}",
        "give me practice questions on {t}", "i want to practice {t}", "drill me on {t}",
        "flashcards for {t}", "make me some flashcards on {t}", "check if i understand {t}",
        "ask me 5 questions about {t}", "give me a mock interview question on {t}",
        "hit me with a hard question on {t}", "test me", "let's do a quick quiz",
        "make multiple choice questions on {t}", "review {t} with me by asking questions",
        "challenge me on {t}", "i have an exam on {t}, quiz me", "pop quiz on {t}",
        "generate exam questions about {t}",
    ],
    "path": [
        "where do i begin with {t}", "what's step one for learning {t}", "i know {t}, what should i tackle next", "what do i need under my belt before {t}", "sequence the topics leading to {t}", "what are the building blocks of {t}", "what should i review before {t}", "what unlocks after {t}", "how do i work up to {t}", "plan a route to understanding {t}", "what am i missing to understand {t}",
        "what should i learn before {t}", "what are the prerequisites for {t}", "learning path for {t}",
        "how do i get started with {t}", "roadmap to learn {t}", "in what order should i learn {t}",
        "what do i need to know before {t}", "where should i start with {t}",
        "give me a study plan for {t}", "what comes after {t}", "what should i learn next after {t}",
        "steps to master {t}", "how do i build up to {t}", "what's the foundation for {t}",
        "what concepts lead up to {t}", "what should i study first to understand {t}",
        "plan my learning for {t}", "path from basics to {t}", "how to go from zero to {t}",
        "which topics depend on {t}", "curriculum for {t}", "what's the next step after {t}",
        "prereqs for {t}?", "build me a learning sequence for {t}",
    ],
    "show_images": [
        "bring up the diagram of {t}", "got any figures of {t}", "let me see the picture of {t}", "display my visuals on {t}", "is there a photo about {t} in my notes", "show the figure from the paper on {t}", "what does the {t} diagram look like", "show me the whiteboard photo on {t}", "the image with {t}, show it", "show me the plot for {t}",
        "show me a diagram of {t}", "show me images of {t}", "what does {t} look like",
        "do i have any figures about {t}", "show me the picture of {t}", "visualize {t}",
        "show the diagram from my notes on {t}", "any screenshots about {t}",
        "pull up the figure for {t}", "show me the chart on {t}", "draw {t}", "images of {t}",
        "show me visuals for {t}", "is there a diagram for {t} in my notes", "display the {t} figure",
        "show me the architecture diagram of {t}", "what did the slide on {t} show",
        "show me photos i saved about {t}", "find the image of {t}", "illustrate {t} with the figures i have",
        "can i see the diagram for {t}", "pictures of {t} please", "show the graph of {t}",
    ],
    "general": [
        "thanks a ton", "you there?", "good afternoon", "how do i change settings", "can you be shorter", "that's wrong", "what languages do you speak", "how do i export my data", "are you an ai", "see you later", "why was that slow", "how do i delete a note", "okay thanks", "cheers", "i'll be back",
        "hi", "hello", "hey there", "thanks", "thank you!", "ok cool", "good morning", "what can you do",
        "who are you", "how do i use this app", "help", "what features do you have", "you're awesome",
        "lol", "never mind", "ok", "sounds good", "bye", "how are you", "what's up",
        "can you remind me tomorrow", "i'm tired today", "tell me a joke", "what time is it",
        "how many notes do i have", "how does this app work", "is my data private",
        "can you speak another language", "that answer was wrong", "try again",
        "make it shorter", "say that again", "i'm going to study now", "what's the weather",
        "who made you", "nice", "great, thanks a lot", "hmm", "cool cool", "good night",
    ],
}

FILLERS = ["", "", "", "hey ", "so ", "quick question, ", "ok ", "can you ", "please "]


def _noise(rng: random.Random, s: str) -> str:
    if rng.random() < 0.3:
        s = rng.choice(FILLERS) + s
    if rng.random() < 0.4:
        s = s.rstrip("?")
    elif not s.endswith("?") and rng.random() < 0.3:
        s += "?"
    if rng.random() < 0.5:
        s = s[0].upper() + s[1:]
    return " ".join(s.split())


def build(n_per_intent: int = 350) -> list[dict]:
    rng = random.Random(SEED)
    rows: list[dict] = []
    seen: set[str] = set()
    for intent, templates in TEMPLATES.items():
        made = 0
        tries = 0
        while made < n_per_intent and tries < n_per_intent * 20:
            tries += 1
            tpl = rng.choice(templates)
            if "{a}" in tpl:
                a, b = rng.choice(PAIRS)
                text = tpl.format(a=a, b=b)
            else:
                text = tpl.format(t=rng.choice(TOPICS)) if "{t}" in tpl else tpl
            text = _noise(rng, text)
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            rows.append({"text": text, "intent": intent})
            made += 1
    rng.shuffle(rows)
    return rows


def main() -> None:
    rows = build()
    out = HERE / "data" / "train.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["intent"]] = counts.get(r["intent"], 0) + 1
    print(f"wrote {len(rows)} rows to {out}: {counts}")


if __name__ == "__main__":
    main()

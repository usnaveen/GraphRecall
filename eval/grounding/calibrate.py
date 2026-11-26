"""Grounding-guard calibration: retrieval signals and decisions for in-domain vs off-topic questions.

Runs the real chat retrieval (analyze + get_context) against a user's corpus and prints, per question:
best cosine, RRF, rerank score, query-term coverage of passages and concept names, and the guard's
decision. IN/OUT were used to pick thresholds; HIN/HOUT are held out.

    GR_EVAL_USER_ID=<uuid> PYTHONPATH=. python eval/grounding/calibrate.py eval/grounding/results.json
"""
import asyncio, json, sys
from langchain_core.messages import HumanMessage
import importlib; cg = importlib.import_module("backend.graphs.chat_graph")
from backend.services.grounding_guard import evaluate_retrieval_confidence, _extract_chunk_scores


import os
USER = os.environ["GR_EVAL_USER_ID"]
IN = ["How does a KV cache speed up autoregressive decoding?", "What is multi-query attention?",
      "Explain scaled dot-product attention", "How does an LSTM avoid vanishing gradients?",
      "What does word2vec skip-gram predict?", "How is GloVe different from word2vec?",
      "What is the Euclidean algorithm for GCD?", "When should I use binary search?",
      "What is a sequence-to-sequence model?", "How do you deploy an LLM with an inference pipeline?"]
OUT = ["How do I make a sourdough starter?", "Who won the 1998 FIFA World Cup?",
       "How do volcanoes form?", "What is the plot of Hamlet?", "How do I tune a guitar to drop D?",
       "What is the income tax rate in Norway?", "How does photosynthesis work in C4 plants?",
       "What are the rules of cricket's LBW?", "How do I fix a leaking kitchen tap?",
       "What is the best time to visit Kyoto?"]

async def probe(q):
    st = {"messages": [HumanMessage(content=q)], "user_id": USER}
    st.update(await cg.analyze_query_node(st))
    ctx = await cg.get_context_node(st)
    rag = cg.pack_context_chunks(ctx.get("rag_context", []), max_chars=cg._CHAT_RAG_CHAR_BUDGET)
    concepts = ctx.get("graph_context", {}).get("concepts", [])
    v, r, rr = _extract_chunk_scores(rag)
    d = evaluate_retrieval_confidence(rag, concepts, st.get("intent", "general"), query=st.get("retrieval_query") or q)
    sims = sorted([float(c["similarity"]) for c in rag if c.get("similarity") is not None], reverse=True)
    from backend.services.reranker import _tokenize, _chunk_text
    STOP = {"a","an","and","are","as","at","be","by","do","does","for","from","has","have","how","in","is","it","its","of","on","or","that","the","this","to","was","were","what","when","where","which","who","why","will","with","i","me","my","you","your","can","could","should","would","explain","describe","tell","about","between","difference","different","use","using","make","work","works","get","best","way","please","vs","versus","s"}
    terms = [t for t in dict.fromkeys(_tokenize(q)) if t not in STOP]
    chunk_toks = set(); [chunk_toks.update(_tokenize(_chunk_text(c))) for c in rag]
    concept_toks = set(); [concept_toks.update(_tokenize(str(c.get("name") or ""))) for c in concepts]
    cov_chunk = sum(t in chunk_toks for t in terms) / max(1, len(terms))
    cov_concept = sum(t in concept_toks for t in terms) / max(1, len(terms))
    return dict(q=q[:44], terms=terms, cov_chunk=round(cov_chunk, 2), cov_concept=round(cov_concept, 2), intent=st.get("intent"), n=len(rag), nsim=len(sims), vec=v, rrf=r, rerank=rr,
                graph=len(concepts), abstain=d.should_abstain, reason=d.reason)

HOLD_IN = ["Why is generating text one token at a time slow if you don't store earlier results?",
           "How do recurrent nets keep information over long sequences?",
           "What trick lets several attention heads share the same keys and values?"]
HOLD_OUT = ["How do I bake banana bread?", "What causes the northern lights?", "How do I renew a UK passport?"]

async def main():
    rows = []
    for label, qs in (("IN", IN), ("OUT", OUT), ("HIN", HOLD_IN), ("HOUT", HOLD_OUT)):
        for q in qs:
            try:
                x = await probe(q); x["set"] = label; rows.append(x)
                print(json.dumps(x, default=lambda o: round(o, 4) if isinstance(o, float) else str(o)), flush=True)
            except Exception as e:
                print(label, q[:40], "ERROR", repr(e)[:200], flush=True)
    json.dump(rows, open(sys.argv[1], "w"), default=str)
asyncio.run(main())

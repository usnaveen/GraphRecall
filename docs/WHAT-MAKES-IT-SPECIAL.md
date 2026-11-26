# GraphRecall — what makes it special to me

*Naveen U S · github.com/usnaveen/GraphRecall · graphrecall.online*

## The problem I kept running into

I learn from everywhere: papers, textbooks, YouTube, newsletters, LeetCode, and long conversations with AI assistants. A few weeks later most of it is gone. I would read something, understand it, highlight it, and then it would quietly disappear. When someone asked "do you know machine learning?", I couldn't actually picture what I knew and where the holes were.

Every friend I talked to had the same problem. Some of them built beautiful knowledge graphs in note-taking apps and never opened them again. Graphs are everywhere on LinkedIn and Reddit right now. They look impressive, but they are pictures, not memory.

There was a second problem I only noticed once I started working with AI agents every day. The assistants explain everything from zero, because they have no idea what I already know. They re-explain attention to me for the hundredth time and skip the one prerequisite I'm actually shaky on.

## What GraphRecall does

GraphRecall turns everything you learn into an **active knowledge graph**:

1. **Concepts are extracted from whatever you drop in.** You can type, paste a link or YouTube video, import a chat, upload a PDF or book, scan a page or simply talk. Each concept either joins the node you already have or becomes a new one, with directed links that say "this is a prerequisite of that" and "this is part of that".
2. **The graph comes back to you as a feed you actually want to open.** It scrolls like social media, not a to-do list, so it works even on days when focus is hard. Spaced repetition decides what returns when. If you slip on something, the scheduler goes back to the prerequisites underneath it.
3. **An assistant answers from your own notes**, with citations, and suggests the next question based on what you're weak at.
4. **The same graph becomes context for any AI agent.** Through an MCP server, Claude or any other agent can ask what you already know well, what's shaky and what you've never seen, and explain at your level. It can also write back what you learned during that conversation.

## The approaches I'm proudest of

- **A graph that measures you, not just your notes.** Every concept carries evidence: reviews, quiz answers, code results, self-ratings. Its status is strong, shaky, seen or new. That same evidence checks every skill on my resume, so I know which claims I could defend in an interview.
- **A "knowledge frontier" for AI agents.** Instead of handing an agent a database dump ("concept A: 60%"), GraphRecall answers one question: what does this person need from me right now? The answer has four parts: what to explain through (things you know well), what to refresh in a line (shaky prerequisites), what to teach properly (gaps), and where you learned each thing. It comes with a stable profile hash, so the agent can cache the profile part of its prompt. To me this is the most original part: your knowledge becomes a layer every AI tool can share.
- **No model calls where a model isn't needed.** A small trained classifier routes most questions without an LLM call. The three "ask next" suggestions come straight from the graph, a shaky prerequisite, an unstudied subtopic and what the concept unlocks, at zero tokens. I care about building AI products that stay cheap enough to run every day.
- **Hybrid GraphRAG retrieval.** Vector search, keyword search and the graph are fused with reciprocal rank fusion, then reranked and diversified. Answers are cached by a version of my notes, so a deleted note can never be served from cache.
- **Learning that respects attention.** The feed gives you a daily limit instead of an endless backlog. Recall is rated on a simple slider instead of grading buttons. You can say "remind me later" on any card. Videos and articles from sources you follow appear only when they match something you're learning.
- **Pictures that teach.** Real figures from my own papers and books appear on concept cards. Where there is no figure, a Gemini image model redraws the real reference diagram in the app's style, or draws one from scratch.

## Why it's personal

GraphRecall started as a tool for myself. Over the past year it became the place where every idea I had about learning ended up. Whenever something annoyed me while studying, it became a feature. The repository has more than 400 commits since January, and almost every one traces back to a moment where I thought "this should exist".

It also taught me how to build. I learned to design an end-to-end AI system: retrieval, caching, evaluation harnesses, graph databases, a native iOS app and a protocol server for agents. I learned to work with AI coding agents as teammates: splitting work between them, reviewing their output and keeping them honest. I learned to ship: build pipelines, devices, domains, deployment, and the discipline of only claiming what actually works.

GraphRecall is the project where I stopped forgetting what I learned, and it's the project I learned the most from building.

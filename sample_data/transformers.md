# Understanding Transformers and Self-Attention

The **Transformer** architecture, introduced in the paper "Attention Is All You Need" (2017), revolutionized Natural Language Processing (NLP). Unlike previous Recurrent Neural Networks (RNNs) or LSTMs, Transformers process input data in parallel, allowing for significantly faster training on larger datasets.

## Key Concepts

### 1. Self-Attention Mechanism
The core innovation is **Self-Attention**. It allows the model to weigh the importance of different words in a sentence relative to each other.
- **Query (Q), Key (K), Value (V):** Each word is transformed into these three vectors.
- **Score Calculation:** $Score = Q \cdot K^T$. This determines how much focus to put on other parts of the input.
- **Softmax:** applied to scores to get probabilities.
- **Weighted Sum:** $Attention(Q, K, V) = softmax(\frac{QK^T}{\sqrt{d_k}})V$

### 2. Multi-Head Attention
Instead of one attention mechanism, Transformers use multiple "heads" running in parallel. This allows the model to focus on different types of relationships (e.g., one head for syntax, another for semantics).

### 3. Positional Encoding
Since Transformers have no recurrence, they don't inherently know the order of words. **Positional Encodings** are added to the input embeddings to give the model information about the relative or absolute position of tokens in the sequence.

### 4. Encoder-Decoder Structure
- **Encoder:** Processes the input into a context vector (used in BERT).
- **Decoder:** Generates output based on the encoder's output and previous predictions (used in GPT).

## Why it matters
Transformers form the backbone of modern LLMs like BERT, GPT-4, and Claude. Their ability to handle long-range dependencies and parallelize training makes them the state-of-the-art for almost all sequence-to-sequence tasks.

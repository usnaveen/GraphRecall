import Foundation

/// NAV-24 — Rich sample teach cards when the feed API is empty / unreachable,
/// so Simulator and physical demos are never blank. All IDs use `demo-` prefix
/// and `domain: "Demo"` so UI can badge them clearly.
enum DemoFeedSeed {
    static let cards: [FeedItem] = [
        FeedItem(
            id: "demo-transformer-mcq",
            itemType: .mcq,
            content: [
                "question": AnyCodable("Which mechanism in the Transformer architecture allows it to weigh the importance of different words in a sequence simultaneously?"),
                "options": AnyCodable([
                    "Recurrent Neural Networks (RNNs)",
                    "Self-Attention Mechanism",
                    "Convolutional Layers",
                    "Long Short-Term Memory (LSTM)"
                ]),
                "correct_answer": AnyCodable("Self-Attention Mechanism"),
                "explanation": AnyCodable("Self-attention evaluates every token relative to every other token in parallel, removing the sequential bottleneck of RNNs/LSTMs.")
            ],
            conceptId: "demo-transformer",
            conceptName: "Transformer Architecture",
            domain: "Demo",
            priorityScore: 10
        ),
        FeedItem(
            id: "demo-attention-flashcard",
            itemType: .flashcard,
            content: [
                "front": AnyCodable("What role do Queries, Keys, and Values play in Self-Attention?"),
                "back": AnyCodable("Queries ask what the current token needs; Keys advertise what each token offers; Values carry the payload. Attention weights come from Query·Key and scale the Values.")
            ],
            conceptId: "demo-attention",
            conceptName: "Attention Mechanism",
            domain: "Demo",
            priorityScore: 9.5
        ),
        FeedItem(
            id: "demo-transformer-showcase",
            itemType: .showcase,
            content: [
                "title": AnyCodable("The Power of Transformers"),
                "description": AnyCodable("Transformers abandoned recurrence for attention, unlocking massive parallel training and models like GPT-4."),
                "definition": AnyCodable("A neural sequence model built entirely from multi-head attention and feed-forward blocks."),
                "tagline": AnyCodable("Attention is all you need"),
                "key_points": AnyCodable([
                    "Introduced in 'Attention Is All You Need' (2017)",
                    "Eliminates sequential processing bottlenecks",
                    "Multi-head attention captures different contextual relationships"
                ]),
                "real_world_example": AnyCodable("Every modern LLM chat completion is a stack of Transformer decoder blocks."),
                "emoji_icon": AnyCodable("⚡")
            ],
            conceptId: "demo-transformer-2",
            conceptName: "Transformer Architecture",
            domain: "Demo",
            priorityScore: 9
        ),
        FeedItem(
            id: "demo-relu-fillblank",
            itemType: .fillBlank,
            content: [
                "sentence": AnyCodable("The __________ function introduces non-linearity into neural networks, allowing them to learn complex patterns."),
                "answer": AnyCodable("activation"),
                "answers": AnyCodable(["activation"]),
                "hint": AnyCodable("ReLU is a popular example")
            ],
            conceptId: "demo-relu",
            conceptName: "Activation Functions",
            domain: "Demo",
            priorityScore: 8.5
        ),
        FeedItem(
            id: "demo-nn-diagram",
            itemType: .diagram,
            content: [
                "mermaid_code": AnyCodable("""
                graph TD
                A[Neural Network] --> B[Input Layer]
                A --> C[Hidden Layers]
                A --> D[Output Layer]
                C --> E[Backpropagation]
                """),
                "mermaidCode": AnyCodable("""
                graph TD
                A[Neural Network] --> B[Input Layer]
                A --> C[Hidden Layers]
                A --> D[Output Layer]
                C --> E[Backpropagation]
                """),
                "caption": AnyCodable("Neural Network Architecture"),
                "source_note": AnyCodable("Demo · Deep Learning Notes")
            ],
            conceptId: "demo-nn",
            conceptName: "Neural Networks",
            domain: "Demo",
            priorityScore: 8
        ),
        FeedItem(
            id: "demo-softmax-code",
            itemType: .codeChallenge,
            content: [
                "language": AnyCodable("python"),
                "instruction": AnyCodable("Implement a numerically stable softmax over a 1-D logits vector."),
                "initial_code": AnyCodable("import numpy as np\n\ndef softmax(x):\n    # TODO\n    pass"),
                "solution_code": AnyCodable("import numpy as np\n\ndef softmax(x):\n    z = x - np.max(x)\n    e = np.exp(z)\n    return e / e.sum()"),
                "explanation": AnyCodable("Subtracting max(x) keeps exp() in a safe range without changing the result.")
            ],
            conceptId: "demo-softmax",
            conceptName: "Softmax",
            domain: "Demo",
            priorityScore: 7.5
        ),
        FeedItem(
            id: "demo-lstm-quiz",
            itemType: .mcq,
            content: [
                "question": AnyCodable("What is the main advantage of LSTM over a vanilla RNN?"),
                "options": AnyCodable([
                    "Faster training speed",
                    "Better at long-term dependencies",
                    "Requires less data",
                    "Simpler architecture"
                ]),
                "correct_answer": AnyCodable("Better at long-term dependencies"),
                "explanation": AnyCodable("Gating lets LSTMs carry information across longer sequences and fight vanishing gradients.")
            ],
            conceptId: "demo-lstm",
            conceptName: "LSTM",
            domain: "Demo",
            priorityScore: 7
        ),
        FeedItem(
            id: "demo-screenshot-placeholder",
            itemType: .screenshot,
            content: [
                "title": AnyCodable("Upload a lecture screenshot"),
                "description": AnyCodable("On the real feed, your screenshots and infographics land here with linked concepts."),
                "linked_concepts": AnyCodable(["Transformers", "Attention", "Softmax"])
            ],
            conceptId: nil,
            conceptName: "User Upload",
            domain: "Demo",
            priorityScore: 6
        )
    ]

    static var response: FeedResponse {
        FeedResponse(
            items: cards,
            totalDueToday: cards.count,
            completedToday: 0,
            dailyGoal: 20,
            streakDays: 3,
            domains: ["Demo", "Gen AI"]
        )
    }
}

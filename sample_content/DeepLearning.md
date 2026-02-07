# Deep Learning Fundamentals

## Introduction
Deep Learning is a subset of machine learning that employs neural networks with multiple layers (hence "deep") to learn representations of data. Inspired by the human brain's structure, deep learning models can automatically extract features from raw input, making them highly effective for tasks like image recognition, natural language processing (NLP), and speech synthesis.

## Core Concepts

### 1. Artificial Neural Networks (ANNs)
At the heart of deep learning are Artificial Neural Networks.
- **Neurons (Nodes)**: The basic units of computation, similar to biological neurons. They receive input, apply a weight, add a bias, and pass the result through an activation function.
- **Layers**:
    - **Input Layer**: Receives the raw data (e.g., pixels of an image).
    - **Hidden Layers**: Intermediate layers where feature extraction and transformation occur. Deep networks have many hidden layers.
    - **Output Layer**: Produces the final prediction (e.g., "Cat" or "Dog").

### 2. The Perceptron
The simplest form of a neural network is the Perceptron, a single-layer network.
mathematically:
$$ y = f(\sum_{i=1}^{n} w_i x_i + b) $$
Where:
- $x_i$ are inputs
- $w_i$ are weights
- $b$ is bias
- $f$ is the activation function

### 3. Activation Functions
Activation functions introduce non-linearity, allowing the network to learn complex patterns.
- **Sigmoid**: Maps output to (0, 1). Used in binary classification but suffers from vanishing gradients.
- **ReLU (Rectified Linear Unit)**: $f(x) = max(0, x)$. Most popular due to computational efficiency and solving vanishing gradients.
- **Softmax**: Used in the output layer for multi-class classification to turn scores into probabilities.

## Training Deep Networks

### Backpropagation
The "engine" of learning. It involves:
1. **Forward Pass**: Data flows through the network to generate a prediction.
2. **Loss Calculation**: Comparing prediction to actual label (e.g., Cross-Entropy Loss).
3. **Backward Pass**: Calculating gradients of the loss with respect to weights using the Chain Rule.
4. **Weight Update**: Adjusting weights to minimize loss using an optimizer (like SGD or Adam).

### Overfitting & Regularization
Deep networks can memorize data (overfitting).
- **Dropout**: Randomly "dropping" neurons during training to force the network to learn robust features.
- **L1/L2 Regularization**: Penalizing large weights.
- **Early Stopping**: Stopping training when validation loss stops improving.

## Key Architectures

### Convolutional Neural Networks (CNNs)
Specialized for grid-like data (images).
- **Convolution Layers**: Use filters (kernels) to detect edges, textures, and shapes.
- **Pooling Layers**: Reduce spatial dimensions (downsampling).
- **Fully Connected Layers**: Perform the final classification.

### Recurrent Neural Networks (RNNs)
Designed for sequential data (time series, text).
- **Memory**: Output from the previous step is fed as input to the current step.
- **LSTM (Long Short-Term Memory)** & **GRU**: Advanced RNNs that solve the short-term memory problem of basic RNNs.

### Transformers
The modern state-of-the-art for NLP (e.g., GPT, BERT).
- **Self-Attention Mechanism**: Allows the model to weigh the importance of different words in a sentence relative to each other, irrespective of distance.
- **Parallelization**: Unlike RNNs, Transformers process entire sequences simultaneously.

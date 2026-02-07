# Neural Networks

Neural networks are computing systems inspired by biological neural networks. They consist of layers of interconnected nodes (neurons) that process information.

## Key Components

1. **Input Layer**: Receives the initial data
2. **Hidden Layers**: Process and transform data through weighted connections
3. **Output Layer**: Produces the final result or prediction

## Training Process

The **backpropagation** algorithm is used to train neural networks. It works by:

- Calculating the error at the output layer
- Propagating this error backwards through the network
- Updating weights using gradient descent to minimize the loss function

**Gradient descent** is the optimization algorithm that adjusts weights by moving in the direction that reduces error.

## Activation Functions

Common activation functions include:
- **Sigmoid**: S-shaped curve, outputs between 0 and 1
- **ReLU**: Rectified Linear Unit, outputs max(0, x)
- **Tanh**: Hyperbolic tangent, outputs between -1 and 1

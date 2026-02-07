# Graph Algorithms: BFS vs DFS

Graph traversal algorithms are fundamental for exploring nodes and edges in a graph data structure. The two most common are **Breadth-First Search (BFS)** and **Depth-First Search (DFS)**.

## Breadth-First Search (BFS)
Explores the neighbor nodes first, before moving to the next level neighbors.
- **Data Structure:** Queue (FIFO).
- **Behavior:** Moves layer by layer, like ripples in a pond.
- **Applications:**
    - Finding the **shortest path** in an unweighted graph.
    - Web crawling (limit depth).
    - Social network connections (friends of friends).
- **Time Complexity:** $O(V + E)$
- **Space Complexity:** $O(V)$ (can be high if the graph is wide).

## Depth-First Search (DFS)
Explores as far as possible along each branch before backtracking.
- **Data Structure:** Stack (LIFO) or Recursion.
- **Behavior:** Dives deep into one path until it hits a dead end.
- **Applications:**
    - Topological Sorting.
    - Detecting cycles in a graph.
    - Maze generating/solving.
    - finding connected components.
- **Time Complexity:** $O(V + E)$
- **Space Complexity:** $O(V)$ (linear with depth).

## Comparison
| Feature | BFS | DFS |
| :--- | :--- | :--- |
| **Strategy** | Level-order | Depth-order |
| **Pathfinding** | Guarantees shortest path (unweighted) | Does not guarantee shortest path |
| **Memory** | High (stores all nodes at current depth) | Lower (stores nodes on current path) |
| **Implementation**| Queue | Stack / Recursion |

## Code Example (Python)

```python
# BFS
def bfs(graph, start):
    queue = [start]
    visited = set([start])
    while queue:
        node = queue.pop(0)
        print(node)
        for neighbor in graph[node]:
            if neighbor not in visited:
                queue.append(neighbor)
                visited.add(neighbor)

# DFS (Recursive)
def dfs(graph, node, visited):
    if node not in visited:
        print(node)
        visited.add(node)
        for neighbor in graph[node]:
            dfs(graph, neighbor, visited)
```

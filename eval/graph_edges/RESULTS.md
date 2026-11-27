
== claude (n=120)
  strictly correct                           0.58  [0.49, 0.67]
  order right (correct + loose + part_of)    0.80  [0.72, 0.86]
  wrong (not_prereq + inverted)              0.17  [0.11, 0.24]
  inverted                                   0.04  [0.02, 0.09]

== neon (n=120)
  strictly correct                           0.62  [0.53, 0.70]
  order right (correct + loose + part_of)    0.82  [0.74, 0.88]
  wrong (not_prereq + inverted)              0.18  [0.12, 0.26]
  inverted                                   0.06  [0.03, 0.12]

agreement claude vs neon: exact 0.78, Cohen's kappa 0.63 (6 labels), 0.68 (ok / wrong / unclear)

disagreements on ok vs wrong (for a human to settle):
   18. Query Optimization -> Query Routing:  claude=not_prereq  neon=part_of
   24. Tree Traversal -> Depth-First Search:  claude=unclear  neon=inverted
   26. Artificial Intelligence -> Explainability:  claude=not_prereq  neon=loose
   29. Gradient Descent -> Solver:  claude=unclear  neon=not_prereq
   33. Word Embeddings -> Recurrent Neural Network:  claude=loose  neon=not_prereq
   64. Mini-Batch Gradient Descent -> Epoch:  claude=not_prereq  neon=correct
   66. Trees -> Graph:  claude=unclear  neon=not_prereq
   79. Tree Traversal -> Breadth-First Search:  claude=unclear  neon=inverted
   89. Depth-First Search -> State Space Tree:  claude=correct  neon=not_prereq
  112. Semantic Vector Space Model -> Matrix Factorization Method:  claude=loose  neon=not_prereq
  116. Feature, Training, and Inference Architecture -> LLM Twin:  claude=not_prereq  neon=correct
  120. ETL -> ZenML:  claude=not_prereq  neon=loose

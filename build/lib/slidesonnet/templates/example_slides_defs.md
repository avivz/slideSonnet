---
marp: true
---

# What is a Graph?

- A set of **vertices** (nodes)
- Connected by **edges**

<!-- say: A graph is a mathematical structure consisting of a set of vertices, sometimes called nodes, connected by edges. Think of it like a social network where people are vertices and friendships are edges. -->

---

# Euler's Theorem

$$\sum_{v \in V} \deg(v) = 2|E|$$

<!-- say: Euler's handshaking theorem tells us that the sum of all vertex degrees equals twice the number of edges. This is because each edge contributes exactly two to the total degree count. -->

---

# Dijkstra's Algorithm

- Finds shortest paths in weighted graphs
- Greedy approach

<!-- say: Dijkstra's algorithm is a fundamental algorithm for finding the shortest path between nodes in a weighted graph. It uses a greedy approach, always expanding the closest unvisited node. -->

# System Design: Database Sharding and Scalability

**Sharding** is a database architecture pattern related to **horizontal partitioning** — the practice of separating one table's rows into multiple different tables, known as partitions or shards.

## When to Shard?
Sharding is typically used when a database behaves too slowly because of:
1.  **High Throughput:** Too many write/read operations for a single instance.
2.  **Storage Limits:** Data volume exceeds the disk capacity of a single node.

## Sharding Strategies

### 1. Key Based Sharding (Hash Sharding)
Uses a hash function on a key (like `user_id`) to determine which shard to store data in.
- **Pros:** Even distribution of data.
- **Cons:** Resharding (adding new servers) is difficult and expensive.

### 2. Range Based Sharding
Divides data based on ranges of a specific value (e.g., `user_id` 1-1000 on Shard A, 1001-2000 on Shard B).
- **Pros:** Easy to implement.
- **Cons:** Can lead to **hotspots** if data is not uniformly distributed (e.g., all recent users on one shard).

### 3. Directory Based Sharding
Verified by a lookup service that knows the current partitioning scheme and maps keys to shards.
- **Pros:** Highly flexible.
- **Cons:** The lookup service becomes a single point of failure and adds latency.

## Challenges of Sharding

*   **Complexity:** Application logic must be aware of sharding to route queries correctly.
*   **Joins:** performing joins across shards is extremely expensive or impossible.
*   **Transactions:** Distributed transactions (ACID compliance across shards) are complex and slow (Two-Phase Commit).
*   **Resharding:** Moving data when a shard gets full is risky and operationally heavy.

## Alternatives
Before sharding, consider:
- **Read Replicas:** For read-heavy workloads.
- **Caching:** Using Redis/Memcached to reduce DB load.
- **Vertical Scaling:** Buying a bigger server (easier but has a ceiling).

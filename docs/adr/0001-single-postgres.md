# ADR 0001: Single PostgreSQL instance for transactional data and vector retrieval (pgvector)

## Status
Accepted

## Context
Incident Copilot needs (a) transactional storage for incident records and (b) vector
similarity search over runbook/error-catalogue content for RAG. The common pattern is
two separate systems: a relational DB plus a dedicated vector database (Pinecone,
Weaviate, Qdrant, or an embedded store like ChromaDB, which is what the earlier v1
prototype used).

## Decision
Use one PostgreSQL instance with the pgvector extension for both roles.

## Why
- Operational simplicity: one database to run, back up, monitor, and secure instead of two.
- At this project's scale (a handful of runbooks, low query volume), pgvector's
  approximate-nearest-neighbor performance is more than sufficient — the "you need a
  dedicated vector DB" argument is a scale problem this project doesn't have.
- Transactional consistency: an incident record and its related retrieval context can
  be queried/joined in one system if that's ever useful, without cross-system consistency
  concerns.

## When this decision would change
If retrieval corpus size grew into the millions of chunks, or query-per-second on the
vector search path significantly exceeded the transactional workload, a dedicated
vector store becomes worth the added operational surface — at that point you're scaling
the vector search independently of the transactional database, which pgvector doesn't
let you do.

## Consequences
- One fewer moving part to run locally and in the demo Kubernetes/Terraform setup.
- A production system with heavier retrieval needs would need to revisit this — this is a
  scoped tradeoff for this project's scale, not a universal recommendation.

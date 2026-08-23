"""
Build the local FAISS RAG index before starting the API.

Usage:
    python -m app.agent.build_rag_index

Set RAG_INDEX_DIR to point at a mounted volume or deployment artifact path.
This command is the only supported way to build or refresh an index.
"""

from app.agent.agent_core import RAG_INDEX_DIR, load_vector_store


def main():
    load_vector_store(rebuild=True)
    print(f"RAG index ready at: {RAG_INDEX_DIR}")


if __name__ == "__main__":
    main()

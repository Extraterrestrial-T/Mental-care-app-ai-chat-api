"""Rebuild the local Corpus-to-FAISS index on the VM's persistent volume."""

from __future__ import annotations

import shutil

from app.agent.agent_core import RAG_INDEX_DIR, load_vector_store


def main() -> None:
    # The corpus is part of the newly deployed image. Removing the prior index
    # ensures a corpus update is reflected before the replacement app starts.
    if RAG_INDEX_DIR.exists():
        shutil.rmtree(RAG_INDEX_DIR)

    load_vector_store(rebuild=True)
    print(f"RAG index created at {RAG_INDEX_DIR}")


if __name__ == "__main__":
    main()

This project, MoJoAssistant, is a Python-based AI assistant with an advanced memory system. The core of the project is its enhanced embedding system, which uses high-quality bi-directional transformer models for semantic search and retrieval across different memory tiers.

**Key Features:**

*   **Advanced Memory System:** The assistant's memory is divided into Working, Active, and Archival tiers, along with a Knowledge Manager for document storage. This allows for efficient context management and retrieval.
*   **High-Quality Embeddings:** It uses powerful embedding models like "nomic-ai/nomic-embed-text-v2-moe" for semantic search.
*   **Flexible Embedding Backends:** Supports various embedding backends, including HuggingFace, local servers, and API-based services like OpenAI and Cohere.
*   **CLI Interface:** An interactive CLI (`interactive-cli.py`) is provided for interacting with the assistant. It includes commands for managing embeddings and viewing memory statistics.
*   **Modular Architecture:** The project is structured into `app` and `utils` directories.
    *   `app`: Contains the core logic, including the LLM interface (`llm` subdirectory) and the memory management system (`memory` subdirectory).
    *   `utils`: Provides various utility modules, including different agent implementations (`PlanExecutorAgent`, `ZeroShotAgent`) and conversation management tools.

**How to Run:**

The main entry point for the interactive CLI is `app/interactive-cli.py`. The assistant's behavior can be configured through JSON files located in the `config/` directory (e.g., `config/embedding_config.json`, `config/llm_config.json`).

**Dependencies:**

The project requires several Python packages, including `sentence-transformers`, `torch`, `numpy`, and `requests`. These are listed in `requirements.txt`.

from typing import Dict, List, Any
from llama_index.core import Document, StorageContext
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core.indices.vector_store import VectorStoreIndex

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

class KnowledgeManager:
    """
    Document and knowledge management using LlamaIndex
    """
    def __init__(self, embedding):
        # Initialize with default settings
        self.parser = SimpleNodeParser.from_defaults()
        self.vector_store = None
        self.index = None
        self.embedding = embedding
        
    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]] = None):
        """Add documents to the knowledge base"""
        if metadatas is None:
            metadatas = [{}] * len(documents)
            
        doc_objects = []
        for i, doc in enumerate(documents):
            doc_objects.append(Document(text=doc, metadata=metadatas[i]))
            
        # Parse documents into nodes
        nodes = self.parser.get_nodes_from_documents(doc_objects)
        
        # Create or update index
        if self.vector_store is None:
            # Initialize vector store with Qdrant
            client = QdrantClient(":memory:")
            collection_name = "knowledge"
            
            # Create collection for knowledge
            collections = client.get_collections().collections
            collection_names = [collection.name for collection in collections]
            
            if collection_name not in collection_names:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=384,  # Assuming same embedding model as memory
                        distance=Distance.COSINE
                    )
                )
                
            self.vector_store = QdrantVectorStore(
                client=client,
                collection_name=collection_name
            )
            
            # Create storage context
            storage_context = StorageContext.from_defaults(
                vector_store=self.vector_store
            )
            
            # Create index
            self.index = VectorStoreIndex(
                nodes=nodes,
                storage_context=storage_context,
                embed_model=self.embedding
            )
        else:
            # Add to existing index
            self.index.insert_nodes(nodes)
    
    def query(self, query_text: str, similarity_top_k: int = 3):
        """Query the knowledge base"""
        if self.index is None:
            return []
            
        # Create retriever
        retriever = self.index.as_retriever(
            similarity_top_k=similarity_top_k
        )
        
        # Retrieve nodes
        nodes = retriever.retrieve(query_text)
        
        return [(node.node.text, node.score) for node in nodes]


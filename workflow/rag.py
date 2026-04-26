import os
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()

# Use DashScope native embeddings
embeddings = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=os.getenv("DASHSCOPE_API_KEY")
)

DB_PATH = "./chroma_db"

def get_vector_store():
    return Chroma(
        collection_name="cycling_reports",
        embedding_function=embeddings,
        persist_directory=DB_PATH
    )

def add_reports(texts: list[str], metadatas: list[dict] = None):
    vector_store = get_vector_store()
    docs = [Document(page_content=t, metadata=m or {}) for t, m in zip(texts, metadatas or [{}]*len(texts))]
    vector_store.add_documents(docs)

def query_reports(query: str, k=3):
    vector_store = get_vector_store()
    return vector_store.similarity_search(query, k=k)

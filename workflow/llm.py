import os
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

def get_llm(model="qwen-max"):
    """
    Returns a configured LLM instance for DashScope (Qwen).
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.7
    )

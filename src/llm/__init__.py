"""LLM integration package for Texas Hold'em Poker (LangChain version).

Provides:
    - LangChain-based LLM client (ChatOpenAI, ChatAnthropic, ChatOllama)
    - ChatPromptTemplate-based prompt construction
    - Chinese/English bilingual response parsing and validation
    - LLM-powered bot (LLMBot) as BotBase subclass
    - Strategy advisor and game commentator
    - Session context management (opponent stats, table image, hand history)
"""

from src.llm.config import LLMConfig, ProviderConfig, load_config
from src.llm.langchain_client import (
    LCDecisionOutput,
    LCDecisionAnalysis,
    LCChainWrapper,
    LCResponse,
    LCTrafficCallback,
    create_chat_model,
    build_decision_chain,
    build_fake_chat_model,
)
from src.llm.context_manager import ContextManager
from src.llm.prompt_builder import PromptBuilder
from src.llm.response_parser import ResponseParser

__all__ = [
    # 配置
    "LLMConfig",
    "ProviderConfig",
    "load_config",
    # LangChain 客户端
    "LCDecisionOutput",
    "LCDecisionAnalysis",
    "LCChainWrapper",
    "LCResponse",
    "LCTrafficCallback",
    "create_chat_model",
    "build_decision_chain",
    "build_fake_chat_model",
    # 上下文管理
    "ContextManager",
    # Prompt 与解析
    "PromptBuilder",
    "ResponseParser",
]

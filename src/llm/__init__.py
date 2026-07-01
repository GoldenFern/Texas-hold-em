"""LLM integration package for Texas Hold'em Poker.

Provides:
    - Multi-backend LLM client (Anthropic, OpenAI, Ollama)
    - State-to-prompt serialization
    - Response parsing and validation
    - LLM-powered bot (LLMBot) as BotBase subclass
    - Strategy advisor and game commentator
"""

from src.llm.config import LLMConfig, ProviderConfig, load_config
from src.llm.client import LLMClient, AnthropicClient, OpenAIClient, OllamaClient, LLMClientFactory
from src.llm.prompt_builder import PromptBuilder
from src.llm.response_parser import ResponseParser

__all__ = [
    "LLMConfig",
    "ProviderConfig",
    "load_config",
    "LLMClient",
    "AnthropicClient",
    "OpenAIClient",
    "OllamaClient",
    "LLMClientFactory",
    "PromptBuilder",
    "ResponseParser",
]

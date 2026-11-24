"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "gh/gpt-6.1-sol",
    "gh/gemini-4-argon",
    "ghe-copilot/gemini-4-carbon",
    "gh/claude-sonnet-5.5",
    "gh/gpt-6.1-terra",
]
COUNCIL_MODELS = [model.strip() for model in os.getenv("COUNCIL_MODELS", ",".join(COUNCIL_MODELS)).split(",")]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = os.getenv("CHAIRMAN_MODEL", "gh/gemini-4-argon")

# OpenRouter API endpoint
OPENROUTER_API_URL = (
    os.getenv("LLM_API", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
)

# Data directory for conversation storage
DATA_DIR = os.getenv("COUNCIL_DATA_DIR", "data/conversations")

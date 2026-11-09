"""Model configuration and SQL generation through any OpenAI-compatible chat API.

Settings come from Streamlit secrets or environment variables:
    LLM_MODEL     model name, e.g. qwen2.5-coder:7b for Ollama
    LLM_API_KEY   API key (any non-empty text for Ollama)
    LLM_BASE_URL  endpoint, e.g. http://localhost:11434/v1 for Ollama; leave unset for OpenAI
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

SYSTEM_PROMPT = """You turn questions into SQLite queries for the database described below.

Rules:
- Reply with exactly one SELECT statement (a WITH clause is allowed) inside a ```sql code block.
- Use only the tables and columns listed in the schema.
- Return only the columns the question asks for, in the order it asks for them.
- Never write queries that change data or the schema.
- If the schema cannot answer the question, reply with the single word UNANSWERABLE.

Schema:
{schema}
"""


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str
    base_url: str | None = None


def load_config(secrets: Mapping | None = None) -> LLMConfig | None:
    """Return the configuration, or None if the model or key is missing."""
    def get(name: str) -> str | None:
        value = (secrets or {}).get(name) or os.environ.get(name)
        return str(value).strip() if value else None

    model, key = get("LLM_MODEL"), get("LLM_API_KEY")
    if not model or not key:
        return None
    return LLMConfig(model=model, api_key=key, base_url=get("LLM_BASE_URL"))


def build_messages(question: str, schema: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(schema=schema)},
        {"role": "user", "content": question.strip()},
    ]


def generate_sql(question: str, schema: str, config: LLMConfig, client=None) -> str:
    """Ask the model for SQL and return its raw reply text."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    response = client.chat.completions.create(
        model=config.model,
        temperature=0,
        messages=build_messages(question, schema),
    )
    return response.choices[0].message.content or ""

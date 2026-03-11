"""
ARIA config — loads and validates all environment variables from .env.
All other modules import from here; nothing reads os.getenv() directly.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Cosmos DB ─────────────────────────────────────────────────────────────────
COSMOS_ENDPOINT: str = os.getenv("COSMOS_ENDPOINT", "")
COSMOS_KEY: str      = os.getenv("COSMOS_KEY", "")
COSMOS_DB: str       = os.getenv("COSMOS_DB", "aria_db")

# ── Azure Service Bus ─────────────────────────────────────────────────────────
SERVICE_BUS_CONN: str = os.getenv("SERVICE_BUS_CONN", "")

# ── Qwen (Azure AI Foundry) ───────────────────────────────────────────────────
QWEN_ENDPOINT: str  = os.getenv("QWEN_ENDPOINT", "")
QWEN_API_KEY: str   = os.getenv("QWEN_API_KEY", "")

# ── Google Custom Search ──────────────────────────────────────────────────────
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID: str  = os.getenv("GOOGLE_CSE_ID", "")

# ── Runtime ───────────────────────────────────────────────────────────────────
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION: bool = ENVIRONMENT == "production"

# ── Container names ───────────────────────────────────────────────────────────
CONTAINER_KNOWLEDGE   = "knowledge_base"
CONTAINER_LOGS        = "agent_logs"
CONTAINER_LESSONS     = "qwen_lessons"
CONTAINER_TRAINING    = "training_data"
CONTAINER_REPORTS     = "aria_reports"

# ── Service Bus queue names ───────────────────────────────────────────────────
QUEUE_RESEARCH  = "research-queue"
QUEUE_THINKING  = "thinking-queue"
QUEUE_CHECKER   = "checker-queue"

# ── Validation ────────────────────────────────────────────────────────────────
_REQUIRED = {
    "COSMOS_ENDPOINT":   COSMOS_ENDPOINT,
    "COSMOS_KEY":        COSMOS_KEY,
    "SERVICE_BUS_CONN":  SERVICE_BUS_CONN,
    "QWEN_ENDPOINT":     QWEN_ENDPOINT,
    "QWEN_API_KEY":      QWEN_API_KEY,
    "GOOGLE_API_KEY":    GOOGLE_API_KEY,
    "GOOGLE_CSE_ID":     GOOGLE_CSE_ID,
}

def validate() -> None:
    """Raise ValueError listing every missing required env var."""
    missing = [k for k, v in _REQUIRED.items() if not v]
    if missing:
        raise ValueError(f"ARIA config: missing required env vars: {', '.join(missing)}")

def is_valid() -> bool:
    """Return True if all required vars are present."""
    return all(_REQUIRED.values())

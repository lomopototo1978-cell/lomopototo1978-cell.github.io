import asyncio

from utils.text_processor import clean, fingerprint
from ml.bias_detector import bias_score
from ml.source_scorer import source_score
from agents.thinking_engine import DepthScorer
from ml.knowledge_validator import KnowledgeValidator
from agents.checker_agent import CheckerAgent
from utils.decay_manager import classify_knowledge_type, is_expired
from database.knowledge_graph import KnowledgeGraph
from ml.training_builder import TrainingBuilder
from agents.reporter_agent import TrendDetector, TopicSelector


def test_text_processor_clean_and_fingerprint():
    raw = "Visit https://example.com for MORE info!!!"
    cleaned = clean(raw, remove_urls=True)
    assert "http" not in cleaned.lower()
    assert len(fingerprint(cleaned)) == 64


def test_bias_detector_relative_scoring():
    biased = "Shocking conspiracy fake news propaganda they dont want you to know"
    factual = "World Bank report states transaction growth increased by 12 percent in 2025"
    assert bias_score(biased) > bias_score(factual)


def test_source_scorer_relative_scoring():
    assert source_score("https://reuters.com/world") > source_score("http://spam.blogspot.com")


def test_thinking_depth_short_vs_long():
    scorer = DepthScorer()
    short_score = scorer.score("ok")
    long_score = scorer.score(
        "A peer reviewed meta analysis over 47 trials found statistically significant improvements "
        "with robust methodology and clear confidence intervals across primary endpoints"
    )
    assert long_score > short_score


def test_knowledge_validator_duplicate_detection():
    validator = KnowledgeValidator()
    text = "Mobile money in Africa has expanded rapidly according to recent studies"
    fp = fingerprint(text)
    out = validator.validate(text, existing_fingerprints={fp})
    assert out["is_duplicate"] is True


def test_checker_agent_rejects_harmful_content():
    checker = CheckerAgent()

    async def _run():
        result = await checker.check({
            "content": "this includes bomb making instructions and harmful methods",
            "url": "http://spam.blogspot.com",
            "topic": "test",
        })
        return result

    result = asyncio.run(_run())
    assert result["verdict"] == "REJECTED"


def test_decay_manager_rules():
    assert classify_knowledge_type("breaking news urgent developing now") == "breaking_news"
    assert is_expired("economic_data", "2020-01-01T00:00:00+00:00") is True
    assert is_expired("mathematics", "2020-01-01T00:00:00+00:00") is False


def test_knowledge_graph_sparse_nodes():
    graph = KnowledgeGraph()
    graph.add_node("a", {"topic": "fintech", "content": "mobile money growth in zimbabwe"})
    graph.add_node("b", {"topic": "fintech", "content": "ecocash adoption and fintech expansion"})
    graph.add_edge("a", "b", relation="related", weight=0.7)
    stats = graph.stats()
    assert stats["nodes"] == 2
    assert stats["edges"] == 1


def test_training_builder_scores_high_vs_low():
    tb = TrainingBuilder()
    high = {
        "content": "World Bank research on mobile money growth and macroeconomic indicators",
        "source_score": 0.9,
        "bias_score": 0.1,
        "depth_score": 0.8,
        "knowledge_type": "economic_data",
        "created_at": "2026-03-01T00:00:00+00:00",
    }
    low = {
        "content": "fake",
        "source_score": 0.1,
        "bias_score": 0.9,
        "depth_score": 0.1,
        "knowledge_type": "breaking_news",
        "created_at": "2020-01-01T00:00:00+00:00",
    }
    assert tb.score(high) > tb.score(low)


def test_reporter_trend_and_topic_selector():
    trend = TrendDetector()
    assert trend.detect([1, 2, 3, 5, 8])["direction"] == "growing"
    assert trend.detect([8, 5, 3, 2, 1])["direction"] == "declining"

    selector = TopicSelector()
    selector.update("fintech", approved=10, rejected=1)
    selector.update("politics", approved=1, rejected=7)
    selected = selector.select(["fintech", "politics"], 1)
    assert len(selected) == 1

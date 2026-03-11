"""
ARIA Adversarial Agent — nightly adversarial testing.
Generates 500 challenge questions per cycle, detects knowledge weaknesses via
SVM classifier and Decision Tree weakness map, logs results to Cosmos.
"""
import asyncio
import json
import logging
import pickle
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline

import agents.qwen_interface as qwen
from database.cosmos_client import AriaCosmosClient
from utils.config import CONTAINER_KNOWLEDGE, CONTAINER_LOGS, CONTAINER_TRAINING
from utils.text_processor import clean_for_ml, extract_keywords

logger = logging.getLogger(__name__)

_MODELS_DIR   = Path(__file__).parent.parent / "ml" / "models"
_SVM_PATH     = _MODELS_DIR / "adversarial_svm.pkl"
_DT_PATH      = _MODELS_DIR / "weakness_tree.pkl"
_QUESTIONS_PER_CYCLE = 500
_BATCH_SIZE          = 10    # Qwen questions per batch call


# ── Weakness categories ────────────────────────────────────────────────────────

WEAKNESS_CATEGORIES = [
    "factual_error",       # answer contradicts known facts
    "incomplete",          # answer missing key detail
    "outdated",            # answer uses expired knowledge
    "biased",              # answer shows ideological lean
    "hallucination",       # answer fabricates information
    "correct",             # answer is good
]


# ── SVM Weakness Classifier ────────────────────────────────────────────────────

class WeaknessClassifier:
    """
    SVM pipeline that classifies adversarial results into weakness categories.
    Trained on labelled examples from Cosmos training_data container.
    """

    def __init__(self):
        self._pipeline: Optional[Pipeline] = None
        self._le = LabelEncoder()

    def _build_pipeline(self) -> Pipeline:
        return Pipeline([
            ("tfidf", TfidfVectorizer(max_features=2000, ngram_range=(1, 2))),
            ("svm",   SVC(kernel="linear", probability=True, C=1.0, random_state=42)),
        ])

    def fit(self, texts: list[str], labels: list[str]) -> float:
        """Fit on labelled texts. Returns cross-val accuracy."""
        if len(texts) < 6:
            # Not enough data — bootstrap with seed examples
            texts, labels = self._bootstrap(texts, labels)
        y = self._le.fit_transform(labels)
        self._pipeline = self._build_pipeline()
        # cv must not exceed the minimum class size
        from collections import Counter
        min_class = min(Counter(y).values())
        cv = max(2, min(5, min_class))
        if cv >= 2:
            scores = cross_val_score(self._pipeline, texts, y, cv=cv, scoring="accuracy")
            acc = float(np.mean(scores))
        else:
            acc = 0.0
        self._pipeline.fit(texts, y)
        return acc

    def _bootstrap(self, texts: list[str], labels: list[str]):
        """Seed with minimal examples per category."""
        seeds = {
            "factual_error":  ["the wrong date incorrect year false claim mistaken",
                               "actually that happened in different year wrong country"],
            "incomplete":     ["missing key detail answer lacks information",
                               "did not mention important aspect incomplete response"],
            "outdated":       ["old data deprecated statistics from before",
                               "this changed in recent years outdated information"],
            "biased":         ["one-sided political propaganda loaded language",
                               "ideologically skewed agenda-driven opinion piece"],
            "hallucination":  ["fabricated invented made up does not exist",
                               "fictional source no evidence for this claim"],
            "correct":        ["accurate complete well sourced factual correct answer",
                               "good comprehensive balanced response correct information"],
        }
        for cat, examples in seeds.items():
            for ex in examples:
                texts.append(ex)
                labels.append(cat)
        return texts, labels

    def predict(self, text: str) -> tuple[str, float]:
        """Returns (category, confidence)."""
        if self._pipeline is None:
            return ("correct", 0.5)
        probs = self._pipeline.predict_proba([clean_for_ml(text)])[0]
        idx   = int(np.argmax(probs))
        label = self._le.inverse_transform([idx])[0]
        return (label, float(probs[idx]))

    def save(self) -> None:
        _MODELS_DIR.mkdir(exist_ok=True)
        with open(_SVM_PATH, "wb") as f:
            pickle.dump({"pipeline": self._pipeline, "le": self._le}, f)

    def load(self) -> None:
        if _SVM_PATH.exists():
            with open(_SVM_PATH, "rb") as f:
                data = pickle.load(f)
                self._pipeline = data["pipeline"]
                self._le       = data["le"]


# ── Decision Tree Weakness Map ─────────────────────────────────────────────────

class WeaknessMap:
    """
    Decision Tree that maps (topic, source_score, bias_score, depth_score,
    days_old) → weakness category.
    Used to predict which topic areas are high-risk before generating questions.
    """

    def __init__(self):
        self._dt: Optional[DecisionTreeClassifier] = None
        self._le = LabelEncoder()

    def fit(self, features: list[list], labels: list[str]) -> None:
        if len(features) < 4:
            return
        y = self._le.fit_transform(labels)
        self._dt = DecisionTreeClassifier(max_depth=6, min_samples_leaf=2, random_state=42)
        self._dt.fit(features, y)

    def predict(self, feature_vec: list) -> str:
        if self._dt is None:
            return "correct"
        y = self._dt.predict([feature_vec])[0]
        return self._le.inverse_transform([y])[0]

    def feature_importance(self) -> dict:
        if self._dt is None:
            return {}
        names = ["topic_hash", "source_score", "bias_score", "depth_score", "days_old"]
        return {n: round(float(i), 3)
                for n, i in zip(names, self._dt.feature_importances_)}

    def save(self) -> None:
        _MODELS_DIR.mkdir(exist_ok=True)
        with open(_DT_PATH, "wb") as f:
            pickle.dump({"dt": self._dt, "le": self._le}, f)

    def load(self) -> None:
        if _DT_PATH.exists():
            with open(_DT_PATH, "rb") as f:
                data = pickle.load(f)
                self._dt = data["dt"]
                self._le = data["le"]


# ── Adversarial Agent ──────────────────────────────────────────────────────────

class AdversarialAgent:
    """
    Nightly adversarial testing pipeline:
    1. Fetch approved knowledge from Cosmos
    2. Generate QUESTIONS_PER_CYCLE challenge questions via Qwen (batched)
    3. Ask Qwen to answer each, classify result with SVM
    4. Update weakness map via Decision Tree
    5. Log results + update training_data with hard cases
    """

    def __init__(self):
        self._svm       = WeaknessClassifier()
        self._wmap      = WeaknessMap()
        self._svm.load()
        self._wmap.load()

    # ── Question generation ────────────────────────────────────────────────────

    async def _generate_questions(self, docs: list[dict], n: int) -> list[dict]:
        """
        Generate `n` adversarial questions from the knowledge docs.
        Returns list of {question, topic, doc_id, source_score, bias_score, depth_score}.
        """
        questions = []
        batches_needed = (n + _BATCH_SIZE - 1) // _BATCH_SIZE
        doc_cycle = docs * (batches_needed // max(len(docs), 1) + 1)   # repeat if needed

        for i in range(min(batches_needed, len(doc_cycle))):
            if len(questions) >= n:
                break
            doc = doc_cycle[i % len(doc_cycle)]
            snippet = doc.get("content", "")[:400]
            topic   = doc.get("topic", "general")

            prompt = (
                f"You are a rigorous adversarial QA tester. "
                f"Given this knowledge snippet about '{topic}':\n\n{snippet}\n\n"
                f"Generate exactly {_BATCH_SIZE} challenging questions that could expose "
                f"factual errors, outdated data, bias, or gaps. "
                f"Return ONLY a JSON array of strings, no other text. "
                f"Example: [\"Question 1?\", \"Question 2?\"]"
            )
            try:
                raw = await qwen.guide_search(prompt, [])
                # guide_search returns a list; join to get JSON text
                text = " ".join(raw) if isinstance(raw, list) else str(raw)
                # Extract JSON array
                start, end = text.find("["), text.rfind("]") + 1
                if start >= 0 and end > start:
                    batch = json.loads(text[start:end])
                    for q in batch[:_BATCH_SIZE]:
                        questions.append({
                            "question":    str(q),
                            "topic":       topic,
                            "doc_id":      doc.get("id", ""),
                            "source_score": doc.get("source_score", 0.5),
                            "bias_score":   doc.get("bias_score", 0.5),
                            "depth_score":  doc.get("depth_score", 0.5),
                        })
            except Exception as e:
                logger.debug(f"Question batch {i} failed: {e}")

        return questions[:n]

    # ── Answer + classify ──────────────────────────────────────────────────────

    async def _evaluate_question(self, item: dict) -> dict:
        """Ask Qwen to answer the question, classify the result."""
        q = item["question"]
        try:
            # Use a simple guide_search prompt for Q&A
            prompt = f"Answer this question accurately and concisely: {q}"
            raw = await qwen.guide_search(prompt, [])
            answer = " ".join(raw) if isinstance(raw, list) else str(raw)
        except Exception:
            answer = ""

        category, confidence = self._svm.predict(q + " " + answer)
        return {**item, "answer": answer[:300], "weakness": category, "confidence": round(confidence, 3)}

    # ── Main cycle ─────────────────────────────────────────────────────────────

    async def run_adversarial_cycle(self) -> dict:
        """
        Full nightly adversarial cycle.
        Returns summary stats.
        """
        logger.info("AdversarialAgent: starting cycle")

        # 1. Fetch approved knowledge
        async with AriaCosmosClient() as db:
            docs = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT * FROM c WHERE c.verdict = 'APPROVED'",
            )

        if not docs:
            logger.warning("AdversarialAgent: no approved knowledge found, skipping")
            return {"questions_generated": 0, "weaknesses_found": 0}

        # 2. Generate questions
        questions = await self._generate_questions(docs, _QUESTIONS_PER_CYCLE)
        logger.info(f"AdversarialAgent: generated {len(questions)} questions")

        # 3. Evaluate each question
        results = []
        for item in questions:
            result = await self._evaluate_question(item)
            results.append(result)
            await asyncio.sleep(0.05)   # rate limit

        # 4. Collect labelled data for SVM retraining
        texts  = [r["question"] + " " + r["answer"] for r in results]
        labels = [r["weakness"] for r in results]
        if len(texts) >= 6:
            acc = self._svm.fit(texts, labels)
            self._svm.save()
            logger.info(f"AdversarialAgent: SVM retrained, cv_accuracy={acc:.2f}")

        # 5. Build weakness map features
        features = []
        for r in results:
            topic_hash = hash(r["topic"]) % 1000 / 1000   # 0-1 normalised
            features.append([
                topic_hash,
                r.get("source_score", 0.5),
                r.get("bias_score", 0.5),
                r.get("depth_score", 0.5),
                0.0,   # days_old — not computed here, populated in full pipeline
            ])
        if features:
            self._wmap.fit(features, labels)
            self._wmap.save()

        # 6. Save hard cases to training_data
        hard_cases = [r for r in results if r["weakness"] not in ("correct",)]
        async with AriaCosmosClient() as db:
            for case in hard_cases[:100]:   # cap at 100 per cycle
                await db.upsert(CONTAINER_TRAINING, {
                    "type":     "adversarial_weakness",
                    "topic":    case["topic"],
                    "question": case["question"],
                    "answer":   case["answer"],
                    "weakness": case["weakness"],
                    "confidence": case["confidence"],
                })

            # Log summary
            weaknesses: dict[str, int] = defaultdict(int)
            for r in results:
                weaknesses[r["weakness"]] += 1

            await db.log("adversarial_agent", "CYCLE_COMPLETE", {
                "questions": len(questions),
                "weaknesses": dict(weaknesses),
                "hard_cases_saved": len(hard_cases[:100]),
                "svm_topics": self._wmap.feature_importance(),
            })

        summary = {
            "questions_generated": len(questions),
            "weaknesses_found":    len(hard_cases),
            "breakdown":           dict(weaknesses),
            "svm_importance":      self._wmap.feature_importance(),
        }
        logger.info(f"AdversarialAgent: cycle complete — {summary}")
        return summary

    def predict_weakness(self, topic: str, source_score: float = 0.5,
                         bias_score: float = 0.5, depth_score: float = 0.5,
                         days_old: float = 0.0) -> str:
        """Predict likely weakness category for a given content profile."""
        topic_hash = hash(topic) % 1000 / 1000
        return self._wmap.predict([topic_hash, source_score, bias_score, depth_score, days_old])

"""
evaluation/judge.py — LLM-as-judge response evaluator.

Uses Gemini Flash to score every agent response on 5 dimensions:
  - accuracy:     Is the data factually correct?
  - completeness: Does it answer everything asked?
  - relevance:    Is the response on-topic?
  - format:       Is the output well-structured (tables, markdown)?
  - overall:      Weighted average (0.0 – 5.0)

Results stored in Firestore arcl_evals collection and returned
alongside the chat response for frontend display.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from google.cloud import firestore

from src.adar.config import settings

logger = logging.getLogger(__name__)

EVALS_COLLECTION = "arcl_evals"
from src.adar.config import settings
GEMINI_MODEL = settings.ADK_MODEL  # same model as the ADK orchestrator
GOOGLE_API_KEY   = os.environ.get("GOOGLE_API_KEY", "")

JUDGE_PROMPT = """Score this cricket assistant Q&A. Output ONLY raw JSON, no markdown.

Q: {question}
A: {response}

JSON format (integers 0-5, explanation max 20 words):
{{"accuracy":4,"completeness":4,"relevance":4,"format":4,"explanation":"short reason here"}}"""


def _calc_overall(scores: dict) -> float:
    """Weighted average. Accuracy weighted higher."""
    weights = {"accuracy": 0.35, "completeness": 0.25, "relevance": 0.25, "format": 0.15}
    total = sum(scores.get(k, 0) * w for k, w in weights.items())
    return round(total, 2)


async def _call_judge(question: str, response: str) -> dict:
    """Call Gemini Flash to score the response. Returns scores dict."""
    prompt = JUDGE_PROMPT.format(question=question[:200], response=response[:500])

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_API_KEY)
    config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )

    # Run synchronous Gemini call in thread pool to avoid blocking async loop
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
    )
    # result.text can be None with some models — fall back to candidates
    if result.text:
        raw = result.text.strip()
    elif result.candidates and result.candidates[0].content.parts:
        raw = result.candidates[0].content.parts[0].text or ""
        raw = raw.strip()
    else:
        raise ValueError(f"Empty response from judge model. candidates={result.candidates}")
    logger.info(f"Judge raw response: {repr(raw[:200])}")

    import re

    # Strip markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()

    # Extract first complete JSON object if response has extra text
    import re as _re
    json_match = _re.search(r"{[^{}]*}", raw, _re.DOTALL)
    if json_match and len(json_match.group()) > 10:
        raw = json_match.group()

    # Remove // comments
    raw = re.sub(r"//[^\n]*", "", raw)

    # Remove trailing commas
    raw = re.sub(",(" + r"\s*[}\]]" + ")", r"\1", raw)

    # Extract JSON object — greedy to capture full object
    match = re.search(r"\{.+\}", raw, re.DOTALL)
    if match:
        raw = match.group(0).strip()

    try:
        scores = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Judge JSON parse error: {e}\nRaw: {repr(raw[:300])}")
        # Return safe defaults so chat still works
        scores = {
            "accuracy": 3, "completeness": 3,
            "relevance": 3, "format": 3,
            "explanation": "Evaluation parsing failed"
        }

    return scores


def get_db():
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


async def evaluate_response(
    question:    str,
    response:    str,
    team_id:     str = "arcl",
    session_id:  str = "",
    user_id:     str = "",
    enabled:     bool = True,
) -> dict | None:
    """
    Evaluate an agent response using LLM-as-judge.
    Stores result in Firestore and returns the eval dict.

    Returns None if evaluation is disabled or fails.

    Usage in main.py:
        eval_result = await evaluate_response(
            question=message,
            response=response_text,
            team_id=team_id,
            session_id=session.id,
        )
    """
    if not enabled or not GOOGLE_API_KEY:
        return None

    # Skip very short or error responses
    if len(response) < 30 or response.startswith("Sorry") or "error" in response.lower()[:40]:
        return None

    try:
        scores = await _call_judge(question, response)

        # Validate scores are in range 0-5
        for key in ["accuracy", "completeness", "relevance", "format"]:
            scores[key] = max(0, min(5, int(scores.get(key, 3))))

        overall = _calc_overall(scores)
        explanation = scores.get("explanation", "")

        eval_doc = {
            "eval_id":      str(uuid.uuid4()),
            "team_id":      team_id,
            "session_id":   session_id,
            "user_id":      user_id,
            "question":     question[:500],
            "response":     response[:1000],
            "scores": {
                "accuracy":     scores["accuracy"],
                "completeness": scores["completeness"],
                "relevance":    scores["relevance"],
                "format":       scores["format"],
                "overall":      overall,
            },
            "explanation":  explanation,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "model":        GEMINI_MODEL,
        }

        # Store in Firestore async (don't wait — don't block the chat response)
        db = get_db()
        await db.collection(EVALS_COLLECTION).document(eval_doc["eval_id"]).set(eval_doc)
        logger.info(
            f"Eval stored: overall={overall} accuracy={scores['accuracy']} "
            f"completeness={scores['completeness']} team={team_id}"
        )

        return eval_doc

    except Exception as e:
        logger.warning(f"Evaluation failed (non-fatal): {e}")
        return None


async def get_eval_summary(team_id: str = None, limit: int = 100) -> dict:
    """
    Aggregate eval scores for admin dashboard.
    Returns average scores across all evals (or per team).
    """
    db = get_db()
    query = db.collection(EVALS_COLLECTION)
    if team_id:
        query = query.where("team_id", "==", team_id)

    docs = []
    async for doc in query.order_by("created_at", direction=firestore.Query.DESCENDING)\
            .limit(limit).stream():
        docs.append(doc.to_dict())

    if not docs:
        return {"total": 0, "averages": {}, "recent": []}

    def avg(key):
        vals = [d["scores"].get(key, 0) for d in docs if "scores" in d]
        return round(sum(vals) / len(vals), 2) if vals else 0

    recent = [
        {
            "eval_id":     d.get("eval_id"),
            "question":    d.get("question", "")[:80],
            "overall":     d.get("scores", {}).get("overall", 0),
            "explanation": d.get("explanation", ""),
            "created_at":  d.get("created_at", "")[:10],
            "team_id":     d.get("team_id"),
        }
        for d in docs[:20]
    ]

    return {
        "total":   len(docs),
        "averages": {
            "accuracy":     avg("accuracy"),
            "completeness": avg("completeness"),
            "relevance":    avg("relevance"),
            "format":       avg("format"),
            "overall":      avg("overall"),
        },
        "recent":  recent,
        "low_scoring": [r for r in recent if r["overall"] < 3.0],
    }
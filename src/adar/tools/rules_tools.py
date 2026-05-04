import logging
from db import vector_search, get_documents_by_field
from config import ARCL_RULES_COLLECTION, ARCL_FAQ_COLLECTION

logger = logging.getLogger(__name__)


UMPIRE_KEYWORDS = {
    "umpire", "umpiring", "no ball", "no-ball", "wide", "wides",
    "dead ball", "dead-ball", "run out", "appeal", "lbw",
    "bye", "leg bye", "signal", "penalty", "fielding restriction",
}


async def vector_search_rules(query: str, top_k: int = 8) -> list[dict]:
    """
    Search ARCL rules by semantic similarity.
    Automatically expands umpiring queries for better recall.

    Args:
        query: Natural language question about rules
        top_k: Number of results to return (default 8)

    Returns:
        List of matching rule chunks with content and source section
    """
    # Expand umpiring queries to improve recall
    q_lower = query.lower()
    is_umpiring = any(kw in q_lower for kw in UMPIRE_KEYWORDS)

    if is_umpiring:
        # Search with explicit umpiring prefix and original query
        results1 = await vector_search(
            ARCL_RULES_COLLECTION,
            f"umpiring rule {query}",
            top_k=top_k,
        )
        results2 = await vector_search(
            ARCL_RULES_COLLECTION,
            query,
            top_k=top_k,
        )
        # Merge and deduplicate by content
        seen = set()
        results = []
        for r in results1 + results2:
            key = r.get("content", "")[:80]
            if key not in seen:
                seen.add(key)
                results.append(r)
        results = results[:top_k]
    else:
        results = await vector_search(ARCL_RULES_COLLECTION, query, top_k=top_k)

    # Detect league intent from query
    q_lower  = query.lower()
    want_men   = any(w in q_lower for w in ["men", "men's", "male", "men league", "div h", "div a", "div b", "div c", "div d", "div e", "div f", "div g"])
    want_women = any(w in q_lower for w in ["women", "woman", "women's", "female", "ladies", "girls"])

    formatted = []
    for r in results:
        league = r.get("extra", {}).get("league", "general")
        content = r.get("content", "")

        # Filter out wrong-league results when league is explicitly requested
        if want_men and league == "women":
            continue
        if want_women and league == "men":
            continue

        formatted.append({
            "content":     content,
            "section":     r.get("section", "General"),
            "source":      r.get("source_url", r.get("source", "arcl.org/Rules")),
            "page_type":   r.get("page_type", "rules"),
            "league":      league,
            "is_umpiring": r.get("extra", {}).get("is_umpiring", False)
                           or any(kw in content.lower() for kw in UMPIRE_KEYWORDS),
        })

    return formatted[:top_k]


async def get_rule_section(section: str) -> str:
    """
    Get all rules for a specific section by name.

    Args:
        section: Section name e.g. 'Boundaries', 'Penalties', 'Eligibility',
                 'Equipment', 'Bad Weather', 'Complaints Procedure'

    Returns:
        Full text of the requested rule section
    """
    docs = await get_documents_by_field(
        ARCL_RULES_COLLECTION, "section", section, limit=20
    )
    if not docs:
        # Fall back to semantic search for the section
        docs = await vector_search(ARCL_RULES_COLLECTION, section, top_k=5)

    if not docs:
        return f"Section '{section}' not found. Check arcl.org/Pages/Content/Rules.aspx for the complete rules."

    return "\n\n".join(d.get("content", "") for d in docs)


async def get_faq_answer(question: str, top_k: int = 3) -> list[dict]:
    """
    Search the ARCL FAQ for answers to common questions.

    Args:
        question: The question to search for
        top_k: Number of FAQ entries to return

    Returns:
        List of matching FAQ entries
    """
    results = await vector_search(ARCL_FAQ_COLLECTION, question, top_k=top_k)
    return [
        {
            "question": r.get("question", ""),
            "answer": r.get("content", ""),
            "source": r.get("source", "arcl.org/Pages/Content/FAQ.aspx"),
        }
        for r in results
    ]
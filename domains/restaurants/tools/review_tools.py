"""Restaurant review retrieval and summarization tools."""

from domains.restaurants.db import connect
from domains.restaurants.tools.query_utils import rows_to_json, table


async def get_restaurant_reviews(
    restaurant_id: str,
    item_query: str | None = None,
    limit: int = 20,
) -> dict:
    """Retrieve relevant restaurant or dish-level reviews."""
    conn = await connect()
    try:
        if item_query:
            rows = await conn.fetch(
                """
                select rating, text, review_date, source
                from reviews
                where restaurant_id = $1
                  and (search_tsv @@ plainto_tsquery('english', $2) or lower(text) like '%' || lower($2) || '%')
                order by review_date desc nulls last
                limit $3
                """,
                restaurant_id, item_query, limit,
            )
        else:
            rows = await conn.fetch(
                """
                select rating, text, review_date, source
                from reviews
                where restaurant_id = $1
                order by review_date desc nulls last
                limit $2
                """,
                restaurant_id, limit,
            )
    finally:
        await conn.close()
    formatted_rows = [
        [row["rating"] or "-", row["review_date"] or "-", (row["text"] or "")[:180]]
        for row in rows
    ]
    return {
        "status": "ok",
        "restaurant_id": restaurant_id,
        "item_query": item_query,
        "count": len(rows),
        "reviews": rows_to_json(rows),
        "formatted": table(["Rating", "Date", "Review"], formatted_rows) if formatted_rows else "No reviews found.",
    }


async def summarize_review_signals(
    restaurant_id: str,
    item_query: str | None = None,
) -> dict:
    """Summarize review quality, value, service, portion, and dish-specific sentiment."""
    result = await get_restaurant_reviews(restaurant_id, item_query=item_query, limit=20)
    reviews = result.get("reviews", [])
    if not reviews:
        return {"status": "ok", "summary": "No review data available.", "restaurant_id": restaurant_id}
    text = " ".join((r.get("text") or "").lower() for r in reviews)
    positives = [w for w in ["fresh", "great", "good", "excellent", "flavor", "portion", "value", "fast"] if w in text]
    negatives = [w for w in ["slow", "cold", "expensive", "bad", "small", "wait", "wrong"] if w in text]
    avg_rating = sum(float(r.get("rating") or 0) for r in reviews) / max(len(reviews), 1)
    return {
        "status": "ok",
        "restaurant_id": restaurant_id,
        "item_query": item_query,
        "review_count": len(reviews),
        "average_rating": round(avg_rating, 2),
        "positive_signals": positives,
        "negative_signals": negatives,
        "summary": f"{len(reviews)} relevant reviews found. Average rating {avg_rating:.1f}. Positive signals: {', '.join(positives) or 'none detected'}. Negative signals: {', '.join(negatives) or 'none detected'}.",
    }

"""
Tool registry for the restaurant recommender domain.

These functions are scaffolded so DOMAIN=restaurants can load the ADK config
while implementation lands incrementally.
"""

from domains.restaurants.tools.restaurant_tools import (
    parse_food_request,
    find_restaurants,
    count_restaurants,
    get_restaurant_details,
    list_restaurants,
    restaurant_genre_summary,
    rank_recommendations,
)
from domains.restaurants.tools.menu_tools import (
    get_restaurant_menu,
    hybrid_search_menu_items,
    check_menu_freshness,
    scrape_restaurant_menu,
)
from domains.restaurants.tools.pricing_tools import compare_menu_prices
from domains.restaurants.tools.review_tools import (
    get_restaurant_reviews,
    summarize_review_signals,
)


TOOL_REGISTRY: dict = {
    "parse_food_request": parse_food_request,
    "find_restaurants": find_restaurants,
    "count_restaurants": count_restaurants,
    "get_restaurant_details": get_restaurant_details,
    "list_restaurants": list_restaurants,
    "restaurant_genre_summary": restaurant_genre_summary,
    "get_restaurant_menu": get_restaurant_menu,
    "hybrid_search_menu_items": hybrid_search_menu_items,
    "check_menu_freshness": check_menu_freshness,
    "scrape_restaurant_menu": scrape_restaurant_menu,
    "compare_menu_prices": compare_menu_prices,
    "get_restaurant_reviews": get_restaurant_reviews,
    "summarize_review_signals": summarize_review_signals,
    "rank_recommendations": rank_recommendations,
}

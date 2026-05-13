"""
domains/geetabitan/tools/__init__.py
Maps tool name strings from agents_config.geetabitan.json to callable functions.
Follows the same pattern as domains/arcl/tools/__init__.py.
"""

from domains.geetabitan.tools.song_tools import (
    get_song_by_title,
    get_full_song,
    get_songs_by_paryay,
    get_song_stanza,
    get_song_summary,
    summarize_aspect,
)
from domains.geetabitan.tools.search_tools import (
    vector_search_songs,
    get_songs_by_raag,
    get_songs_by_taal,
    describe_raag,
    describe_taal,
)

TOOL_REGISTRY: dict = {
    # Search
    "vector_search_songs": vector_search_songs,
    "get_songs_by_raag":   get_songs_by_raag,
    "get_songs_by_taal":   get_songs_by_taal,
    "describe_raag":       describe_raag,
    "describe_taal":       describe_taal,
    # Song retrieval
    "get_song_by_title":   get_song_by_title,
    "get_full_song":       get_full_song,
    "get_songs_by_paryay": get_songs_by_paryay,
    "get_song_stanza":     get_song_stanza,
    # Summary
    "get_song_summary":    get_song_summary,
    "summarize_aspect":    summarize_aspect,
}

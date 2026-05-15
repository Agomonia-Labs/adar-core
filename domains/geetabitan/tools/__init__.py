"""
domains/geetabitan/tools/__init__.py
Maps tool name strings from agents_config.geetabitan.json to callable functions.
"""

from domains.geetabitan.tools.search_tools import (
    vector_search_songs,
    get_songs_by_raag,
    get_songs_by_taal,
    describe_raag,
    describe_taal,
)
from domains.geetabitan.tools.song_tools import (
    get_song_by_title,
    get_full_song,
    get_songs_by_paryay,
    get_song_stanza,
    get_song_summary,
    summarize_aspect,
    list_raags,
    list_taals,
    get_youtube_url,
)
from domains.geetabitan.tools.notation_tools import (
    get_notation_link,
    get_notation_text,
)

TOOL_REGISTRY: dict = {
    # Search
    "vector_search_songs":  vector_search_songs,
    "get_songs_by_raag":    get_songs_by_raag,
    "get_songs_by_taal":    get_songs_by_taal,
    "describe_raag":        describe_raag,
    "describe_taal":        describe_taal,
    # Song retrieval
    "get_song_by_title":    get_song_by_title,
    "get_full_song":        get_full_song,
    "get_songs_by_paryay":  get_songs_by_paryay,
    "get_song_stanza":      get_song_stanza,
    # Summary & analysis
    "get_song_summary":     get_song_summary,
    "summarize_aspect":     summarize_aspect,
    # Raag & taal listing
    "list_raags":           list_raags,
    "list_taals":           list_taals,
    "get_youtube_url":      get_youtube_url,
    # Notation / swaralipi
    "get_notation_link":    get_notation_link,
    "get_notation_text":    get_notation_text,
}
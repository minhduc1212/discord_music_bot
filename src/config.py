YTDL_SINGLE_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
    "skip_download": True,
}

YTDL_PLAYLIST_OPTIONS = {
    "format": "bestaudio/best",
    "extract_flat": "in_playlist",
    "playlistend": 30,
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "skip_download": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -reconnect_on_network_error 1 -thread_queue_size 4096",
    "options": "-vn -sn -dn -b:a 128k -bufsize 128k"
}
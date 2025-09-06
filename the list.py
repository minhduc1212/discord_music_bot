from yt_dlp import YoutubeDL

url = "https://www.youtube.com/watch?v=09Mh7GgUFFA&list=RD09Mh7GgUFFA&start_radio=1"

ydl_opts = {
    'extract_flat': 'in_playlist',
    'playlistend': 20
}

with YoutubeDL(ydl_opts) as ydl:
    info_dict = ydl.extract_info(url, download=False)
    if 'entries' in info_dict:
        for entry in info_dict['entries']:
            print(entry['url'])
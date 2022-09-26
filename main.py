import argparse
import json
import re
import urllib.parse
from pathlib import Path

import requests
import youtube_dl
from mutagen.mp4 import MP4, MP4Cover

# Arguments
parser = argparse.ArgumentParser(description='Download new mixes from mixcloud.')
parser.add_argument('-q', '--query', type=str, help='The query to search for.')
parser.add_argument('-a', '--artist', type=str, help='The artist to use  for metadata.')
parser.add_argument('-al', '--album', type=str, help='The album to use for metadata.')
parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode.', default=False)
parser.add_argument('-n', type=int, help="number of iterations to query the API.", default=5)

args = parser.parse_args()
DEBUG = args.debug
N_ITERS = args.n

# Create cache & download directory
CACHE_DIR = Path("./cache")

if not CACHE_DIR.exists():
    CACHE_DIR.mkdir(parents=True)

DOWNLOAD_DIR = Path("./downloads")

if not DOWNLOAD_DIR.exists():
    DOWNLOAD_DIR.mkdir(parents=True)

def extract_data(data: dict) -> dict:
    ret = {}

    for cloudcast in data["data"]:
        album = cloudcast["user"]["name"] if not args.album else args.album
        number = re.search(rf".*{album} #?(\d+).*?", cloudcast["name"])
        art = cloudcast["pictures"]["extra_large"]

        if number:
            number = number.group(1)

            ret[int(number)] = {
                "album": album,
                "url": cloudcast["url"],
                "art": art,
            }
        elif DEBUG:
            print("No number found for", cloudcast["name"])
    
    return ret


def query_mixcloud(query: str):
    safe_query = urllib.parse.quote_plus(query)

    cloudcasts = {}

    for _ in range(N_ITERS):
        has_next = True
        url = f"https://api.mixcloud.com/search/?limit=100&q={safe_query}&type=cloudcast"
        while has_next:
            res = requests.get(url=url)
            data = res.json()

            results = extract_data(data)
            cloudcasts.update(results)

            has_next = "next" in data["paging"]

            if has_next:
                url = data["paging"]["next"]

    return cloudcasts

def cache_results(results: dict) -> dict:
    album_cache = CACHE_DIR / f"{args.album}.json"
    if not album_cache.exists():
        new = results
    else:
        with open(album_cache, "r") as f:
            old = json.load(f)
        new = {k: v for k, v in results.items() if str(k) not in old.keys()}

    with open(album_cache, "w") as f:
        json.dump(dict(sorted(results.items())), f)

    return new

def download_mix(mix: int, mix_data: dict) -> Path:
    # Download cover
    cover_filename = DOWNLOAD_DIR / f"{args.album} - {mix}.jpg"
    urllib.request.urlretrieve(mix_data["art"], cover_filename)

    # Download mix
    filename = f"{args.album} - {mix}.m4a"
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio'
        }],
        "outtmpl": f"{DOWNLOAD_DIR}/{filename}",
    }
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        ydl.download([mix_data["url"]])

    return (DOWNLOAD_DIR / filename, cover_filename)


def edit_metadata(_file_data: tuple[Path, Path], mix: int, mix_data: dict):
    _file, _cover_file = _file_data
    audio = MP4(_file)

    audio["\xa9nam"] = f"{mix_data['album']} {mix}"
    audio["\xa9ART"] = args.artist
    audio["\xa9alb"] = mix_data["album"]
    audio["trkn"] = [(mix,0)]

    with open(_cover_file, "rb") as f:
        audio["covr"] = [
            MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)
        ]

    audio.save()

data = query_mixcloud(args.query)
new = cache_results(data)

for mix, mix_data in new.items():
    _file_data = download_mix(mix, mix_data)
    edit_metadata(_file_data, mix, mix_data)


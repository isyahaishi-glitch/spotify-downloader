import requests
import base64
import yt_dlp
import re
import os
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK, ID3NoHeaderError


# SPOTIFY CREDENTIALS

CLIENT_ID     = "your_client_id_here"
CLIENT_SECRET = "your_client_secret_here"

# OUTPUT 

OUTPUT_DIR = "downloads"
os.makedirs(OUTPUT_DIR, exist_ok=True)



# SPOTIFY TOKEN

def get_spotify_token():
    auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    result = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={"grant_type": "client_credentials"}
    )
    if result.status_code != 200:
        print(f" Failed to get Spotify token: {result.text}")
        return None
    print(" Spotify token acquired")
    return result.json()["access_token"]



# CLEAN YOUTUBE TITLE

def clean_title(title):
    noise_patterns = [
        r'\(full album.*?\)',
        r'\(official.*?\)',
        r'\(lyrics.*?\)',
        r'\(audio.*?\)',
        r'\(video.*?\)',
        r'\(visualizer.*?\)',
        r'\(live.*?\)',
        r'\[.*?\]',
        r'ft\..*',
        r'feat\..*',
    ]
    cleaned = title
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Split "Artist - Title" format
    if ' - ' in cleaned:
        parts = cleaned.split(' - ', 1)
        return parts[1].strip(), parts[0].strip()  # (song_title, artist)

    return cleaned.strip(), None



# GET YT METADATA

def get_yt_info(url):
    ydl_opts = {"quiet": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Handle playlist vs single video
    if info.get("_type") == "playlist":
        entries = info.get("entries", [])
        print(f"📋 Playlist detected: '{info.get('title')}' — {len(entries)} tracks")
        return entries, True
    else:
        return [info], False



# SEARCH SPOTIFY

def search_spotify(token, title, artist, album=None):
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    clean, extracted_artist = clean_title(title)
    if extracted_artist:
        artist = extracted_artist

    queries = [
        f'track:"{clean}" artist:"{artist}"',
        f"{clean} {artist}",
        clean,
    ]

    for query in queries:
        print(f"   🔍 Searching: {query}")
        result = requests.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params={"q": query, "type": "track", "limit": 5}
        )

        if result.status_code == 403:
            print("❌ 403 Forbidden — check CLIENT_ID and CLIENT_SECRET")
            return None

        if result.status_code != 200:
            print(f"❌ Search failed: {result.status_code}")
            return None

        items = result.json()["tracks"]["items"]
        if not items:
            continue

        # Prefer album match
        if album:
            for item in items:
                if album.lower() in item["album"]["name"].lower():
                    return item

        return items[0]

    return None



# DOWNLOAD COVER

def download_cover(url, path):
    response = requests.get(url)
    response.raise_for_status()
    with open(path, "wb") as f:
        f.write(response.content)


# EMBED METADATA
def embed_metadata(mp3_path, cover_path, title, artist, album, track_number=None):
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags["TIT2"] = TIT2(encoding=3, text=title)
    tags["TPE1"] = TPE1(encoding=3, text=artist)
    if album:
        tags["TALB"] = TALB(encoding=3, text=album)
    if track_number:
        tags["TRCK"] = TRCK(encoding=3, text=str(track_number))
    if cover_path and os.path.exists(cover_path):
        with open(cover_path, "rb") as f:
            tags["APIC"] = APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=f.read()
            )

    tags.save(mp3_path)



# SANITIZE FILENAME

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', '', name).strip()



# DOWNLOAD ONE TRACK

def download_track(entry, token, index=None):
    title  = entry.get("title", "Unknown Title")
    artist = entry.get("artist") or entry.get("creator") or entry.get("uploader", "Unknown Artist")
    album  = entry.get("album")
    url    = entry.get("webpage_url") or entry.get("url")

    print(f"\n🎵 [{index}] {title} — {artist}")

    # Search Spotify for clean metadata
    track = search_spotify(token, title, artist, album)

    if track:
        sp_title  = track["name"]
        sp_artist = track["artists"][0]["name"]
        sp_album  = track["album"]["name"]
        cover_url = track["album"]["images"][0]["url"]
        print(f"    Spotify match: {sp_title} — {sp_artist} ({sp_album})")
    else:
        clean, extracted = clean_title(title)
        sp_title  = clean
        sp_artist = extracted or artist
        sp_album  = album
        cover_url = None
        print(f"    No Spotify match, using YouTube metadata")

    # File paths
    safe_name   = sanitize_filename(f"{sp_artist} - {sp_title}")
    mp3_path    = os.path.join(OUTPUT_DIR, f"{safe_name}.mp3")
    cover_path  = os.path.join(OUTPUT_DIR, f"{safe_name}.jpg")

    # Download audio
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "outtmpl": mp3_path.replace(".mp3", ""),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }],
    }
    print(f"   ⬇️  Downloading audio...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Download cover
    if cover_url:
        download_cover(cover_url, cover_path)

    # Embed metadata
    embed_metadata(mp3_path, cover_path, sp_title, sp_artist, sp_album, track_number=index)
    print(f"    Done: {mp3_path}")

    # Clean up cover file
    if os.path.exists(cover_path):
        os.remove(cover_path)



# MAIN

if __name__ == "__main__":
    yt_url = input("Enter YouTube Music URL (track or playlist): ").strip()

    token = get_spotify_token()
    entries, is_playlist = get_yt_info(yt_url)

    if is_playlist:
        print(f"\n🚀 Starting playlist download — {len(entries)} tracks\n")
        # Re-fetch full info for each entry in playlist
        for i, entry in enumerate(entries, start=1):
            try:
                full_url = entry.get("url") or entry.get("webpage_url")
                with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                    full_entry = ydl.extract_info(full_url, download=False)
                download_track(full_entry, token, index=i)
            except Exception as e:
                print(f"    Skipping track {i}: {e}")
    else:
        download_track(entries[0], token, index=1)

    print(f"\n All done! Files saved to: ./{OUTPUT_DIR}/")

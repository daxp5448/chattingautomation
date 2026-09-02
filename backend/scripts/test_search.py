import urllib.request
import re
import json

def search_unsplash_photos(query, count=5):
    url = f"https://unsplash.com/napi/search/photos?query={urllib.parse.quote(query)}&per_page={count}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = []
            for r in data.get('results', []):
                raw_url = r.get('urls', {}).get('raw')
                if raw_url:
                    results.append((r.get('id'), raw_url, r.get('alt_description') or r.get('description')))
            return results
    except Exception as e:
        print(f"Error searching for '{query}': {e}")
        return []

print(search_unsplash_photos("car service garage entrance", 3))

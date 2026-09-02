import urllib.request
import re
import json

def get_unsplash_photos_from_search(query):
    # Unsplash search HTML page has JSON data embedded or img tags with images.unsplash.com/photo-...
    url = f"https://unsplash.com/s/photos/{urllib.parse.quote(query)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8')
            # find photo IDs like photo-1580273916550-e323be2ae537
            ids = re.findall(r'photo-([a-zA-Z0-9_-]+)', html)
            # deduplicate
            seen = set()
            unique_ids = []
            for photo_id in ids:
                if len(photo_id) > 5 and photo_id not in seen:
                    seen.add(photo_id)
                    unique_ids.append(f"photo-{photo_id}")
            return unique_ids[:10]
    except Exception as e:
        print(f"Error scraping '{query}': {e}")
        return []

print("Car garage:", get_unsplash_photos_from_search("modern car garage showroom"))
print("Dental clinic:", get_unsplash_photos_from_search("dental clinic equipment"))

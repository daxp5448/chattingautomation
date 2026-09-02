import urllib.request
from PIL import Image
import io

endpoints = [
    ('loremflickr', 'https://loremflickr.com/1200/800/car,garage/all'),
    ('picsum', 'https://picsum.photos/1200/800'),
    ('unsplash_direct', 'https://images.unsplash.com/photo-1617814076367-b759c7d7e738?w=1200&h=800&fit=crop&q=80')
]

for name, url in endpoints:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            img = Image.open(io.BytesIO(data))
            print(f"{name}: OK - {len(data)} bytes, format: {img.format}, size: {img.size}")
    except Exception as e:
        print(f"{name}: Error - {e}")

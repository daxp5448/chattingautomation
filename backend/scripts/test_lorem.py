import urllib.request
import os
from PIL import Image
import io

test_tags = [
    ("automobile", "welcome", "car,dealership,showroom"),
    ("automobile", "car_service", "mechanic,auto,repair"),
    ("clinic", "welcome", "clinic,reception,waiting"),
    ("clinic", "dental", "dentist,dental,chair"),
    ("restaurant", "starters", "appetizer,platter,food"),
]

os.makedirs("d:/whatsapp ordering/backend/media_storage/demo/test", exist_ok=True)

for niche, name, tags in test_tags:
    url = f"https://loremflickr.com/1200/800/{tags}/all"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            img = Image.open(io.BytesIO(content))
            img = img.convert('RGB')
            # resize / crop to exactly 1200x800 if not already
            if img.size != (1200, 800):
                # crop / resize to 1200x800
                img = img.resize((1200, 800), Image.Resampling.LANCZOS)
            out_path = f"d:/whatsapp ordering/backend/media_storage/demo/test/{niche}_{name}.jpg"
            img.save(out_path, format="JPEG", quality=85)
            size_kb = os.path.getsize(out_path) / 1024
            print(f"Saved {out_path}: {img.size}, {size_kb:.1f} KB")
    except Exception as e:
        print(f"Error {niche}/{name}: {e}")

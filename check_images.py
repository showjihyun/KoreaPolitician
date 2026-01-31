import os
from pathlib import Path
import sys

# Add backend to path to import image_manager
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from image_manager import image_manager

print(f"Current Working Directory: {os.getcwd()}")
print(f"ImageManager Base Dir: {image_manager.base_dir}")
print(f"ImageManager Images Dir: {image_manager.images_dir}")
print(f"Images Dir exists: {image_manager.images_dir.exists()}")

if image_manager.images_dir.exists():
    imgs = list(image_manager.images_dir.glob("*.jpg"))[:5]
    print(f"Found {len(list(image_manager.images_dir.glob('*')))} files in images dir.")
    print(f"Sample images: {[img.name for img in imgs]}")
else:
    print("WARNING: Images directory not found!")
    # Try common alternatives
    alt1 = Path(".") / "img"
    print(f"Alternative (./img) exists: {alt1.exists()}")
    alt2 = Path("backend") / ".." / "img"
    print(f"Alternative (backend/../img) exists: {alt2.is_dir()}")

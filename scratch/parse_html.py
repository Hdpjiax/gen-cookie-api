import os
from bs4 import BeautifulSoup

file_path = "scratch/dropdown_opened.html"
if not os.path.exists(file_path):
    print("HTML file does not exist")
    exit(1)

with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

print("--- Searching for dropdown/menu elements ---")
for tag in soup.find_all(True):
    classes = tag.get("class") or []
    classes_str = " ".join(classes).lower()
    tag_id = tag.get("id") or ""
    
    if any(x in classes_str or x in tag.name.lower() or x in tag_id.lower() for x in ["dropdown", "menu", "popover", "modal", "tooltip"]):
        text = tag.get_text().strip()
        print(f"Tag: <{tag.name}> | Classes: {classes} | ID: {tag_id} | Text (first 60 chars): {text[:60]}")

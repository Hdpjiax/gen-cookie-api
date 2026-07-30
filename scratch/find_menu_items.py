import os
from bs4 import BeautifulSoup

for fn in ["scratch/viva_loaded.html", "scratch/viva_after_click.html", "scratch/dropdown_opened.html"]:
    if not os.path.exists(fn):
        continue
    print(f"\n=================== Parsing {fn} ===================")
    with open(fn, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    
    # Let's print all buttons
    print("--- BUTTONS ---")
    for btn in soup.find_all("button"):
        text = btn.get_text().strip()
        if text:
            print(f"<button> class={btn.get('class')} role={btn.get('role')} text={text[:60]}")
            
    # Let's print all links
    print("--- LINKS ---")
    for link in soup.find_all("a"):
        text = link.get_text().strip()
        if text:
            print(f"<a> class={link.get('class')} role={link.get('role')} text={text[:60]}")
            
    # Let's print all list items
    print("--- LIST ITEMS ---")
    for li in soup.find_all("li"):
        text = li.get_text().strip()
        if text:
            print(f"<li> class={li.get('class')} role={li.get('role')} text={text[:60]}")

    # Let's search for elements with role='menuitem' or class containing 'menu' or 'item'
    print("--- MENU/ITEM ROLES/CLASSES ---")
    for tag in soup.find_all(True):
        role = tag.get("role") or ""
        classes = tag.get("class") or []
        classes_str = " ".join(classes).lower()
        if "menu" in role.lower() or "item" in role.lower() or any(x in classes_str for x in ["menu", "item"]):
            text = tag.get_text().strip()
            if text and len(text) < 100:
                print(f"<{tag.name}> class={classes} role={role} text={text}")

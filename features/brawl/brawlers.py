import json
import os 
from dataclasses import dataclass

@dataclass
class Brawler:
    id: str
    name: str
    rarity: str
    emoji_name: str

def load_brawlers():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "brawlers.json")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Match your JSON keys: id, name, rarity, emoji_name
        return [Brawler(
            id=item['id'], 
            name=item['name'], 
            rarity=item['rarity'], 
            emoji_name=item['emoji_name']
        ) for item in data]
    except Exception as e:
        print(f"Error loading brawlers: {e}")
        return []
    
BRAWLER_ROSTER = load_brawlers()
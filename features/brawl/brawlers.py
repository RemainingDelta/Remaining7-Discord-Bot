import json
import os 
from dataclasses import dataclass
from typing import List

@dataclass
class Brawler:
    id: str
    name: str
    rarity: str
    image_path: str

def load_brawlers():
    # 1. Get the folder where THIS python file lives
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Build the full path to the JSON file inside that same folder
    file_path = os.path.join(script_dir, "brawlers.json")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return [Brawler(**item) for item in data]
    
    except FileNotFoundError:
        print(f"Error: Could not find file at: {file_path}")
        return []
    except Exception as e:
        print(f"Error loading brawlers: {e}")
        return []

# --- Test Block (Runs only when you execute this file directly) ---
if __name__ == "__main__":
    # 1. Load the data
    all_brawlers = load_brawlers()
    
    if all_brawlers:
        print(f"✅ Successfully loaded {len(all_brawlers)} brawlers.")
        
        # 2. Print the first few to check
        print("\n--- First 3 Brawlers ---")
        for b in all_brawlers[:3]:
            print(f"Name: {b.name} | Rarity: {b.rarity}")
            
        # 3. Check a specific one (e.g., checking if image_path loaded)
        print(f"\nExample Image Path for {all_brawlers[0].name}: {all_brawlers[0].image_path}")
    else:
        print("❌ No brawlers loaded.")
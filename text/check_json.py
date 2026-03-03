import json

with open("text/textMaterial.json", encoding="utf-8") as f:
    data = json.load(f)

print(len(data))
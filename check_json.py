import json

with open("tanjing.json", encoding="utf-8") as f:
    data = json.load(f)

print(len(data))
import json
from dnsbuilder.api.main import app

def main():
    with open("doc/api/openapi.json", "w", encoding="utf-8") as f:
        json.dump(app.openapi(), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
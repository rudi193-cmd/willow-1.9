"""
seed_rules.py — Bootstrap default routing rules into SOIL store.
Run: python3 -m willow.routing.seed_rules [--dry-run]
b17: ROUT1  ΔΣ=42
"""
import argparse
import os

from willow.fylgja._mcp import call as mcp_call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
COLLECTION = "willow/routing/rules"

DEFAULT_RULES = [
    {
        "id": "rule-kart",
        "pattern": r"\b(task|build|deploy|run|execute|infrastructure|automat)\b",
        "agent": "kart",
        "priority": 10,
        "description": "Infrastructure and multi-step task work",
    },
    {
        "id": "rule-ganesha",
        "pattern": r"\b(debug|error|diagnose|fix|broken|obstacle|failing|crash)\b",
        "agent": "ganesha",
        "priority": 10,
        "description": "Debugging and obstacle removal",
    },
    {
        "id": "rule-jeles",
        "pattern": r"\b(search|find|retrieve|index|library|archive|look.?up)\b",
        "agent": "jeles",
        "priority": 10,
        "description": "Search and retrieval from KB",
    },
    {
        "id": "rule-grove",
        "pattern": r"\b(message|channel|send|notify|post|tell|grove|announce)\b",
        "agent": "grove",
        "priority": 10,
        "description": "Grove messaging and channel operations",
    },
    {
        "id": "rule-hanz",
        "pattern": r"\b(implement|refactor|write.?code|function|class|module|test)\b",
        "agent": "hanz",
        "priority": 8,
        "description": "Code implementation and technical work",
    },
    {
        "id": "rule-gerald",
        "pattern": r"\b(ponder|reflect|philosophi|reason|ethic|mean|understand)\b",
        "agent": "gerald",
        "priority": 6,
        "description": "Deep reasoning and philosophical questions",
    },
]


def seed(dry_run: bool = False) -> None:
    for rule in DEFAULT_RULES:
        if dry_run:
            print(f"[seed] Would write: {rule['id']} → {rule['agent']}")
            continue
        try:
            mcp_call("store_put", {
                "app_id": AGENT,
                "collection": COLLECTION,
                "record": rule,
            }, timeout=5)
            print(f"[seed] Written: {rule['id']} → {rule['agent']}")
        except Exception as e:
            print(f"[seed] Failed {rule['id']}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Seed default willow_route rules into SOIL store")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    seed(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

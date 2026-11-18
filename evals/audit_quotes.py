"""Сверить цитаты всех активных фактов с локальными снимками. Без API и записи в проекты."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategist.evidence import load_claims, load_sources, snapshot_text  # noqa: E402
from strategist.importer import verify_quote  # noqa: E402
from strategist.project import project_dir  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for pid in sys.argv[1:] or ["antifraud-family", "esim-travel"]:
        snapshots = {s["id"]: snapshot_text(s, project_dir(pid)) for s in load_sources(pid)}
        outcomes = Counter()
        for claim in load_claims(pid):
            if claim["kind"] != "fact" or claim["status"] != "active":
                continue
            matches = {verify_quote(claim["quote"], snapshots.get(s, "")) for s in claim["sources"]}
            result = next((m for m in ("verbatim", "partial", "not_found", "no_quote") if m in matches), "no_snapshot")
            outcomes[result] += 1
            if result != "verbatim":
                print(f"{pid} {claim['id']}  {result}")
        print(f"{pid}  total={outcomes.total()}  {dict(outcomes)}")

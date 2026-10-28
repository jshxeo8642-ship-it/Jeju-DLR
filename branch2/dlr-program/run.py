"""Run Branch 2 CLI or Branch 3 local UI from any working directory."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "risk-rating-engine"))
sys.path.insert(0, str(ROOT / "ui"))


def main():
    parser = argparse.ArgumentParser(description="제주 154 kV 확률·물리 DLR 프로그램")
    parser.add_argument("command", nargs="?", choices=["ui", "calculate"], default="ui")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "example_ascc430.json")
    parser.add_argument("--weather", type=Path, default=ROOT / "data" / "example_scenarios.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "result.json")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    from contracts import load_json
    if args.command == "ui":
        from server import serve
        serve(ROOT, args.config, args.weather, args.port)
    else:
        from engine import run_engine
        try:
            result = run_engine(load_json(args.config), load_json(args.weather))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            print(f"status={result['search']['status']}; SLR={result['SLR']}; DLR={result['recommended_DLR']}")
            print(f"Tmax risk={result['Tmax_risk']}; output={args.output.resolve()}")
        except (ValueError, KeyError, TypeError, OSError) as error:
            parser.exit(1, f"입력 또는 계산 오류: {error}\n")


if __name__ == "__main__":
    main()

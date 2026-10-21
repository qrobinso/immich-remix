"""Generate built-in style previews with Gemini: uv run python scripts/build_previews.py [--only a,b] [--force]"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.previews import estimate_preview_cost, generate_preview, write_preview  # noqa: E402
from app.providers.base import ProviderConfig  # noqa: E402
from app.providers.gemini import Gemini  # noqa: E402
from app.styles import BUILTIN_DIR, _read  # noqa: E402

ENV = Path(__file__).resolve().parents[2] / ".env"


def load_env() -> None:
    if ENV.is_file():
        for line in ENV.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


async def run(args, provider, out_dir: Path) -> int:
    styles = _read(BUILTIN_DIR)
    only = set(args.only.split(",")) if args.only else set(styles)
    if unknown := only - set(styles):
        print("unknown styles:", ", ".join(sorted(unknown)))
        return 1
    done = failed = 0
    for id in sorted(only):
        if not args.force and (out_dir / f"{id}.card.webp").exists():
            print(f"skip   {id}")
            continue
        try:
            write_preview(await generate_preview(styles[id], provider), out_dir, id)
            done += 1
            print(f"ok     {id}")
        except Exception as e:  # keep going; report at the end
            failed += 1
            print(f"FAILED {id}: {e}")
    cost = estimate_preview_cost(provider)
    print(f"{done} generated, {failed} failed" + (f", ~${done * cost:.2f}" if cost else ""))
    return 1 if failed else 0


def main(argv=None, provider=None, out_dir: Path | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    out_dir = out_dir or BUILTIN_DIR / "previews"

    async def go():
        if provider:
            return await run(args, provider, out_dir)
        load_env()
        if not os.environ.get("GEMINI_API_KEY"):
            print("GEMINI_API_KEY is not set")
            return 1
        async with httpx.AsyncClient() as http:
            g = Gemini(ProviderConfig(api_key=os.environ["GEMINI_API_KEY"], model=None, url=None, options={}), http)
            return await run(args, g, out_dir)

    return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())

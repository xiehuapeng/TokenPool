import argparse
import asyncio

from app.database.migrations import upgrade_database
from app.services.bootstrap import seed_initial_data
from app.services.usage_service import backfill_usage_costs


async def main(dry_run: bool) -> None:
    await upgrade_database()
    await seed_initial_data()
    result = await backfill_usage_costs(dry_run=dry_run)
    print(f"dry_run={result['dry_run']}")
    print(
        f"scanned={result['scanned']} updated={result['updated']} "
        f"estimated_cache_logs={result['estimated_cache_logs']} "
        f"total_estimated_cost={result['total_estimated_cost']}"
    )
    for model, rate in result["model_cache_hit_rates"].items():
        print(f"cache_hit_rate {model}: {rate:.6f}")
    global_rate = result.get("global_cache_hit_rate")
    if global_rate is not None:
        print(f"cache_hit_rate (global fallback): {global_rate:.6f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="历史日志费用回填（按平均缓存命中率推算，标记为 estimated）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览将回填的数量与总费用，不落库",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))

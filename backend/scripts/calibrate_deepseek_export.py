import argparse
import asyncio
import csv
from collections import defaultdict

from app.database.migrations import upgrade_database
from app.services.bootstrap import seed_initial_data
from app.services.usage_service import calibrate_estimated_cache_rates


def parse_amount_csv(path: str) -> dict:
    groups = defaultdict(lambda: {"hit": 0, "miss": 0, "requests": 0, "output": 0})
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            day = row["start_time_iso"].strip()[:10]
            model = row["model"].strip()
            usage_type = row["type"].strip()
            try:
                amount = int(row["amount"] or 0)
            except ValueError:
                continue
            group = groups[(day, model)]
            if usage_type == "input_cache_hit_tokens":
                group["hit"] += amount
            elif usage_type == "input_cache_miss_tokens":
                group["miss"] += amount
            elif usage_type == "request_count":
                group["requests"] += amount
            elif usage_type == "output_tokens":
                group["output"] += amount
    return groups


def parse_cost_csv(path: str) -> dict:
    costs = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            day = row["start_time_iso"].strip()[:10]
            costs[(day, row["model"].strip())] = float(row["cost"])
    return costs


async def main(amount_csv: str, cost_csv: str | None, dry_run: bool) -> None:
    await upgrade_database()
    await seed_initial_data()

    groups = parse_amount_csv(amount_csv)
    costs = parse_cost_csv(cost_csv) if cost_csv else {}

    calibrations = []
    for (day, model), group in sorted(groups.items()):
        total_input = group["hit"] + group["miss"]
        if total_input <= 0:
            continue
        calibrations.append(
            {"model": model, "date": day, "hit_rate": group["hit"] / total_input}
        )

    if not calibrations:
        print("导出数据中没有可用的缓存命中/未命中明细")
        return

    result = await calibrate_estimated_cache_rates(
        calibrations=calibrations, dry_run=dry_run
    )

    print(f"dry_run={result['dry_run']}")
    for group in result["groups"]:
        label = f"{group['date']} {group['model']}"
        print(
            f"{label}  hit_rate={group['hit_rate']:.6f}  "
            f"scanned={group['scanned']} updated={group['updated']}  "
            f"input_tokens={group['input_tokens']}  "
            f"est_cached={group['estimated_cached_tokens']}  "
            f"old_cost={group['old_total_cost']:.6f} -> "
            f"new_cost={group['new_total_cost']:.6f}"
        )
        if group.get("error"):
            print(f"{label}  error={group['error']}")
        official = costs.get((group["date"], group["model"]))
        if official is not None:
            deviation = (
                (group["new_total_cost"] - official) / official * 100
                if official
                else None
            )
            dev_str = f"{deviation:+.2f}%" if deviation is not None else "n/a"
            print(
                f"{label}  official_cost={official:.7f}  "
                f"new_vs_official={dev_str}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="用 DeepSeek 平台导出的用量明细校准历史估算日志的缓存命中率"
    )
    parser.add_argument("--amount-csv", required=True, help="amount-*.csv 路径")
    parser.add_argument("--cost-csv", help="cost-*.csv 路径（用于对照官方费用）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不落库")
    args = parser.parse_args()
    asyncio.run(main(args.amount_csv, args.cost_csv, args.dry_run))

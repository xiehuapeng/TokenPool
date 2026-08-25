import argparse
import asyncio
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.migrations import upgrade_database
from app.services.billing_reconciliation import (
    parse_aliyun_daily_bill,
    reconcile_aliyun_daily_bill,
)


async def main(path: str, *, apply: bool) -> None:
    await upgrade_database()
    bills = parse_aliyun_daily_bill(path)
    result = await reconcile_aliyun_daily_bill(bills, dry_run=not apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "按阿里云百炼日汇总账单，将真实目录费用按 Token 比例分摊到历史调用"
        )
    )
    parser.add_argument("daily_bill", help="阿里云 consumedetailbillv2daysummary CSV")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际写入；默认仅 dry-run 预览",
    )
    args = parser.parse_args()
    asyncio.run(main(args.daily_bill, apply=args.apply))

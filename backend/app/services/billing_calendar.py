"""DeepSeek Beijing peak calendar. Update annually from the State Council notice."""
from datetime import date

# https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm
# Published vacation periods; weekend make-up working days remain off-peak.
HOLIDAY_RANGES = {2026: (
    ("01-01", "01-03"), ("02-15", "02-23"), ("04-04", "04-06"),
    ("05-01", "05-05"), ("06-19", "06-21"), ("09-25", "09-27"),
    ("10-01", "10-07"),
)}


def calendar_known(day: date) -> bool:
    return day.year in HOLIDAY_RANGES


def is_holiday(day: date) -> bool:
    return any(start <= day.strftime("%m-%d") <= end
               for start, end in HOLIDAY_RANGES.get(day.year, ()))

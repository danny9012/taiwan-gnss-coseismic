#!/usr/bin/env python3
"""
plot_timeseries.py

命令列工具:讀取一份已篩選好時間窗的 NGL tenv3 檔案,畫出 East/North/Up
三分量的位移時間序列圖(以第一天為基準,單位 mm,標出地震日期)。

這是 ngl_timeseries.py 函式庫的命令列包裝版,讓使用者不用自己寫 Python
程式碼、不用打開檔案編輯,直接在終端機下一行指令就能畫圖。

用法:
    python3 plot_timeseries.py <tenv3檔案> --quake-date <YYYY-MM-DD> \
        --station <測站名稱> --label <地震名稱,例如 "M6.6 美濃地震"> \
        [--out <輸出檔名.png>] [--day-interval <X軸刻度間隔天數,預設1>]

範例:
    python3 plot_timeseries.py lnch_window.txt --quake-date 2016-02-06 \
        --station LNCH --label "M6.6 Meinong Earthquake" --out lnch.png

<tenv3檔案> 請先用 grep(或其他方式)篩選出單一測站、你想要的時間窗範圍,
格式跟 NGL 官網下載的 tenv3 ascii 檔案一致,見 SETUP.md 第 3-4 節的下載教學。
"""

import argparse
import sys
from datetime import datetime

from ngl_timeseries import load_tenv3, to_relative_mm, plot_enu_timeseries


def main():
    parser = argparse.ArgumentParser(
        description="畫出 NGL tenv3 座標時間序列的 East/North/Up 三分量圖"
    )
    parser.add_argument("tenv3_file", help="已篩選好單一測站、時間窗的 tenv3 檔案路徑")
    parser.add_argument("--quake-date", required=True,
                         help="地震日期,格式 YYYY-MM-DD,圖上會畫一條紅色虛線標示")
    parser.add_argument("--station", required=True,
                         help="測站名稱,會顯示在圖的標題上")
    parser.add_argument("--label", required=True,
                         help="地震描述文字,會顯示在圖的副標題上,例如 'M6.6 Meinong Earthquake'")
    parser.add_argument("--out", default=None,
                         help="輸出圖檔檔名(預設: <station>_timeseries.png)")
    parser.add_argument("--day-interval", type=int, default=1,
                         help="X 軸日期刻度間隔天數(預設 1;時間窗較長時可以設 2 或更大,避免刻度擠在一起)")
    args = parser.parse_args()

    try:
        quake_date = datetime.strptime(args.quake_date, "%Y-%m-%d")
    except ValueError:
        print(f"錯誤: --quake-date 格式不對,應為 YYYY-MM-DD,收到的是: {args.quake_date}", file=sys.stderr)
        sys.exit(1)

    try:
        dates, east, north, up = load_tenv3(args.tenv3_file)
    except FileNotFoundError:
        print(f"錯誤: 找不到檔案 {args.tenv3_file}", file=sys.stderr)
        sys.exit(1)

    if not dates:
        print(f"錯誤: {args.tenv3_file} 裡沒有讀到任何資料列,請確認檔案格式/篩選範圍是否正確", file=sys.stderr)
        sys.exit(1)

    east_mm, north_mm, up_mm = to_relative_mm(east, north, up)

    outname = args.out or f"{args.station}_timeseries.png"
    quake_label = f"{args.label} ({args.quake_date})"

    saved_path = plot_enu_timeseries(
        dates, east_mm, north_mm, up_mm,
        quake_date=quake_date,
        station_label=args.station,
        quake_label=quake_label,
        outname=outname,
        day_interval=args.day_interval,
    )

    print(f"已輸出: {saved_path}")
    print(f"  資料涵蓋範圍: {dates[0].date()} ~ {dates[-1].date()} (共 {len(dates)} 天)")
    print(f"  East  震前第一天 -> 最後一天: {east_mm[-1] - east_mm[0]:+.2f} mm")
    print(f"  North 震前第一天 -> 最後一天: {north_mm[-1] - north_mm[0]:+.2f} mm")
    print(f"  Up    震前第一天 -> 最後一天: {up_mm[-1] - up_mm[0]:+.2f} mm")


if __name__ == "__main__":
    main()

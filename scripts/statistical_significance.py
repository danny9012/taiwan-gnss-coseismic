#!/usr/bin/env python3
"""
statistical_significance.py

對 NGL tenv3 座標時間序列做「震前 vs 震後跳動是否具統計顯著性」的檢定,
取代單純用肉眼看圖形狀(有沒有像階梯)來判斷是不是真訊號。

原理:
  1. 震前 N 天的每日座標,計算平均值跟標準差(標準誤差 = std / sqrt(N))
  2. 震後(或震當天)那一天,直接用 tenv3 檔案裡該日的 formal uncertainty
     (sig_e / sig_n / sig_u 欄位,NGL 處理時給出的當日解算標準差)
  3. 合併不確定度: combined_sigma = sqrt(pre_sem^2 + post_sig^2)
  4. t 值 = |post_value - pre_mean| / combined_sigma

  重要:震前樣本數通常只有 4-7 天,樣本數這麼小時不能直接套用常態分布
  (z-distribution)的 3-sigma/2-sigma 門檻 —— 樣本數小,t 分布的尾巴比常態
  分布胖,用常態分布的固定門檻會高估顯著性。因此改用 **t 分布**,自由度
  df = n_pre - 1,針對每一筆資料的實際震前天數動態算出對應的臨界值:
    - t 值超過 99.7% 信心水準對應的臨界值 -> 顯著
    - t 值超過 95% 信心水準對應的臨界值 -> 邊界
    - 以下 -> 不顯著
  樣本數越小,臨界值會比固定的 3.0/2.0 更高(更保守),避免小樣本高估顯著性。

用法:
    python3 statistical_significance.py <tenv3_window_file> --n-pre <N>

<tenv3_window_file> 是已經用 grep 篩選出某測站、某時間窗的 tenv3 檔案
(格式跟本專案 ngl_timeseries.py 的 load_tenv3 相同)。
--n-pre 是震前天數(這些天會拿來算平均值跟標準誤差),之後的資料列
預設把最後一列當作要檢定的「震後/震當天」值,--n-pre 之前的所有天都當
「震前」樣本。

範例:
    python3 statistical_significance.py s169_window.txt --n-pre 5
"""

import argparse
import math
from datetime import datetime
from scipy import stats


def load_tenv3_full(fname):
    """讀取 tenv3 檔案, 回傳每列的 (date, east, north, up, sig_e, sig_n, sig_u)。"""
    rows = []
    with open(fname) as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] == "site":
                continue
            dt = datetime.strptime(parts[1], "%y%b%d")
            east, north, up = float(parts[8]), float(parts[10]), float(parts[12])
            sig_e, sig_n, sig_u = float(parts[14]), float(parts[15]), float(parts[16])
            rows.append((dt, east, north, up, sig_e, sig_n, sig_u))
    return rows


def mean_std(values):
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(var)


def significance_test(rows, n_pre, component_idx, component_name):
    """
    component_idx: 1=east, 2=north, 3=up (對應 rows 裡的欄位索引)
    sig_idx: 對應的不確定度欄位索引 (east->4, north->5, up->6)
    """
    sig_idx = component_idx + 3

    pre_values = [r[component_idx] for r in rows[:n_pre]]
    pre_mean, pre_std = mean_std(pre_values)
    pre_sem = pre_std / math.sqrt(len(pre_values)) if len(pre_values) > 0 else 0.0

    post_row = rows[-1]
    post_value = post_row[component_idx]
    post_sig = post_row[sig_idx]

    diff = post_value - pre_mean
    combined_sigma = math.sqrt(pre_sem ** 2 + post_sig ** 2)
    t_stat = abs(diff) / combined_sigma if combined_sigma > 0 else float('inf')

    df = max(len(pre_values) - 1, 1)
    t_crit_997 = stats.t.ppf(0.9985, df)  # 兩尾 99.7% 信心水準對應的臨界值
    t_crit_95 = stats.t.ppf(0.975, df)    # 兩尾 95% 信心水準對應的臨界值
    p_value = 2 * (1 - stats.t.cdf(t_stat, df)) if t_stat != float('inf') else 0.0

    verdict = (
        f"顯著 (t={t_stat:.1f} >= 臨界值{t_crit_997:.1f} [df={df}], 可信為真訊號)" if t_stat >= t_crit_997 else
        f"邊界 (t={t_stat:.1f}, 介於95%~99.7%臨界值[{t_crit_95:.1f}~{t_crit_997:.1f}, df={df}]之間,需謹慎)" if t_stat >= t_crit_95 else
        f"不顯著 (t={t_stat:.1f} < 95%臨界值{t_crit_95:.1f} [df={df}], 可能只是雜訊)"
    )

    print(f"  {component_name}: 震前平均={pre_mean*1000:+.2f}mm (pre_sem={pre_sem*1000:.2f}mm, n={len(pre_values)}天), "
          f"震後值={post_value*1000:+.2f}mm (當日formal uncertainty={post_sig*1000:.2f}mm)")
    print(f"    差值={diff*1000:+.2f}mm, 合併不確定度={combined_sigma*1000:.2f}mm, "
          f"t={t_stat:.1f}, p={p_value:.4f} -> {verdict}")


def main():
    parser = argparse.ArgumentParser(description="NGL tenv3 同震位移統計顯著性檢定")
    parser.add_argument("file", help="已篩選出單一測站時間窗的 tenv3 檔案")
    parser.add_argument("--n-pre", type=int, required=True,
                         help="震前天數 (檔案開頭這幾列會拿來算平均值與標準誤差)")
    args = parser.parse_args()

    rows = load_tenv3_full(args.file)
    if len(rows) <= args.n_pre:
        print(f"錯誤: 檔案只有 {len(rows)} 列資料, 不足以扣除 {args.n_pre} 天震前樣本後還有震後值可檢定")
        return

    station_date_range = f"{rows[0][0].date()} ~ {rows[-1][0].date()}"
    print(f"檔案: {args.file}  ({station_date_range}, 共 {len(rows)} 天, 震前樣本 n={args.n_pre}, "
          f"檢定目標: 最後一天 {rows[-1][0].date()})\n")

    significance_test(rows, args.n_pre, 1, "East ")
    significance_test(rows, args.n_pre, 2, "North")
    significance_test(rows, args.n_pre, 3, "Up   ")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
批次 PPP-static 解算 (美濃地震 IES 測站案例, 交叉驗證用第二批站網)

跟大屯火山案例相同的邏輯, 使用已修復跨日邊界 bug 的 pdp3 + redig。
額外處理這批資料的兩個差異:
  1. 觀測檔為 gzip 壓縮 (*.14o.gz), 需要先解壓縮才能給 pdp3 讀取
  2. RINEX 標頭沒有 PRN / # OF OBS 逐衛星統計欄位, 系統偵測改成
     直接掃描觀測記錄本體裡的衛星代碼 (例如 G05 / R21) 判斷 GPS/GLONASS

DATA_DIR 會遞迴掃描兩批資料夾 (高雄美濃IES 震前 DOY031-037,
高雄美濃IES2 震後 DOY038-045), 同一個「測站+年份+DOY」若同時有
已解壓縮與 .gz 兩種來源, 或有重複檔案, 一律去重只處理一份。

流程:
1. 掃描資料夾下所有 RINEX 觀測檔 (含 .gz), 解析測站代碼/年份/DOY, 去重
2. 若為 .gz, 解壓縮到與檔名同名的子資料夾 (跟大屯火山案例巢狀慣例一致)
3. 讀取 RINEX 標頭+觀測記錄, 自動判斷 GPS/GLONASS, 動態組出 pdp3 的
   -sys / -frq 參數
4. 用 pdp3 -m S 執行 PPP-static 解算, 完整輸出存成獨立 log 檔
5. 以「有沒有產生 pos_ 開頭的檔案」判斷成功/失敗, 失敗記錄原因但不中斷
6. 對每個成功案例, 額外檢查 redig 疊代是否真正收斂到 0
7. 成功結果整理成 CSV: 測站代碼, 年份, DOY, X, Y, Z (ECEF, ITRF), 是否收斂, 備註
8. 印出總結 (含收斂統計)

可重複執行: 若某檔案先前已成功產生 pos_, 預設會略過重跑, 只重新解析結果;
若要強制全部重跑, 用 --force。
"""

import argparse
import csv
import glob
import gzip
import os
import re
import shutil
import signal
import subprocess
import sys

# nohup 重導向到檔案時 stdout 預設為整塊緩衝, 進度會卡在緩衝區看起來像「卡住」
# 改成逐行緩衝, 讓 print() 立即寫進 log 檔
sys.stdout.reconfigure(line_buffering=True)

DATA_DIR = os.environ.get("PPP_IES_DATA_DIR", "/mnt/c/Users/user1/Downloads/高雄美濃IES")
OUTPUT_CSV = os.path.join(DATA_DIR, "ppp_results_ies.csv")
LOG_DIR = os.path.join(DATA_DIR, "pdp3_logs")

# 震前 5 天 + 震後 1 天 (美濃地震 2016/02/06 = DOY 037): 只處理 DOY 032-038,
# 其餘天數不解算 (即使觀測檔存在也略過)
DOY_RANGE = (32, 38)

# 單一站天處理逾時上限。pdp3 內部用 "echo $cmd | bash" 呼叫 lsq/redig 等子程式,
# 會產生巢狀子行程; 已觀察到部分站天 (例如訊號品質特殊的站/地震當天) 需要遠超過
# 一般 35-50 分鐘的時間才能完整收斂, 因此預設值設得寬鬆, 避免誤殺仍在正常收斂
# 中的處理。實際逾時時會強制終止整個 process group (見 run_pdp3)。
DEFAULT_TIMEOUT_SEC = 3 * 3600

# 測站4碼 + DOY3碼 + session1碼 + .YYo, 例如 s1690310.14o / s1690310.14o.gz
FILENAME_RE = re.compile(r'^([A-Za-z0-9]{4})(\d{3})[A-Za-z0-9]\.(\d{2})[oO]$')
GZ_FILENAME_RE = re.compile(r'^([A-Za-z0-9]{4})(\d{3})[A-Za-z0-9]\.(\d{2})[oO]\.gz$')

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(text):
    return ANSI_RE.sub('', text)


def find_rinex_tasks(root):
    """
    遞迴掃描 root 下所有 RINEX 觀測檔 (含 .gz), 依 (測站, 年份, DOY) 去重。
    同一站天若同時有已解壓縮版本與 .gz, 優先採用已解壓縮版本 (不必再解壓)。
    回傳 list of dict: {station, year, doy, plain, gz}
    """
    plain_candidates = {}
    gz_candidates = {}

    for dirpath, dirnames, filenames in os.walk(root):
        # 不遞迴進 pdp3 自己產生的工作目錄 (年份資料夾, 例如 "2014")
        dirnames[:] = [d for d in dirnames if not re.match(r'^\d{4}$', d)]
        for fn in filenames:
            m = FILENAME_RE.match(fn)
            if m:
                station, doy, yy = m.group(1).upper(), m.group(2), int(m.group(3))
                year = 2000 + yy if yy < 80 else 1900 + yy
                key = (station, year, doy)
                plain_candidates.setdefault(key, []).append(os.path.join(dirpath, fn))
                continue
            m2 = GZ_FILENAME_RE.match(fn)
            if m2:
                station, doy, yy = m2.group(1).upper(), m2.group(2), int(m2.group(3))
                year = 2000 + yy if yy < 80 else 1900 + yy
                key = (station, year, doy)
                gz_candidates.setdefault(key, []).append(os.path.join(dirpath, fn))

    tasks = []
    for key in sorted(set(plain_candidates) | set(gz_candidates)):
        station, year, doy = key
        if key in plain_candidates:
            path = sorted(plain_candidates[key])[0]
            tasks.append({'station': station, 'year': year, 'doy': doy, 'plain': path, 'gz': None})
        else:
            path = sorted(gz_candidates[key])[0]
            tasks.append({'station': station, 'year': year, 'doy': doy, 'plain': None, 'gz': path})
    return tasks


def ensure_decompressed(task):
    """若只有 .gz 版本, 解壓縮到跟檔名同名的巢狀子資料夾 (跟大屯火山案例慣例一致)。"""
    if task['plain']:
        return task['plain']

    gz_path = task['gz']
    base = os.path.basename(gz_path)[:-3]  # 去掉結尾 .gz
    target_dir = os.path.join(os.path.dirname(gz_path), base)
    target_path = os.path.join(target_dir, base)

    if os.path.exists(target_path):
        return target_path

    os.makedirs(target_dir, exist_ok=True)
    with gzip.open(gz_path, 'rb') as fin, open(target_path, 'wb') as fout:
        shutil.copyfileobj(fin, fout)

    return target_path


def detect_gnss_systems(filepath):
    """
    讀取 RINEX 標頭+觀測記錄, 回傳實際存在的衛星系統代碼集合。
    優先順序:
      1. 標頭 RINEX VERSION / TYPE 若為單一系統字元 (非 M), 直接採用
      2. 標頭若有 PRN / # OF OBS 或 SYS / # / OBS TYPES 統計欄位, 從中判讀
      3. 以上都沒有 (例如這批 IES 資料的 Trimble NetR9 RINEX2.11 格式):
         直接掃描觀測記錄本體裡的衛星代碼 (例如 G05 / R21) 判斷
    """
    header_lines = []
    body_sample = []
    with open(filepath, 'r', errors='ignore') as f:
        past_header = False
        for line in f:
            if not past_header:
                header_lines.append(line)
                if 'END OF HEADER' in line:
                    past_header = True
                continue
            body_sample.append(line)
            if len(body_sample) >= 4000:
                break

    version_line = next((l for l in header_lines if 'RINEX VERSION / TYPE' in l), '')
    m = re.search(r'OBSERVATION DATA\s+(\S)', version_line)
    sys_char = m.group(1).upper() if m else ''

    if sys_char and sys_char != 'M':
        return {sys_char}

    systems = set()
    for l in header_lines:
        if 'PRN / # OF OBS' in l:
            token = l[0]
            if token.strip() == '':
                systems.add('G')  # RINEX2 規範: 系統欄空白代表 GPS
            elif token.strip().upper() in 'GRECJSI':
                systems.add(token.strip().upper())
        elif 'SYS / # / OBS TYPES' in l:
            token = l[0]
            if token.strip().upper() in 'GRECJSI':
                systems.add(token.strip().upper())

    if systems:
        return systems

    # 標頭沒有統計欄位: 掃描觀測記錄本體。RINEX2 mixed 格式的 epoch 衛星列表,
    # 每顆衛星以 1 個系統字母 + 2 碼 PRN 表示 (個位數 PRN 前面補空白), 例如
    # "G 5G26G13R21G10G 4R22G 2G12R 8G17R 7"
    body_text = ''.join(body_sample)
    for letter in re.findall(r'([GRECJSI])[\d ]\d', body_text):
        systems.add(letter)

    return systems


def build_sys_frq_args(systems):
    """依偵測到的系統組出 pdp3 的 -sys / -frq 參數 (只處理 GPS/GLONASS)。"""
    sys_str = ''
    frq_args = []
    warn = None

    if 'G' in systems:
        sys_str += 'G'
        frq_args.append('G12')
    if 'R' in systems:
        sys_str += 'R'
        frq_args.append('R12')

    if not sys_str:
        warn = f"未偵測到 GPS 或 GLONASS 系統 (偵測到: {systems or '無'}), 改用預設 -sys G -frq G12"
        sys_str = 'G'
        frq_args = ['G12']

    return sys_str, frq_args, warn


def parse_pos_file(pos_path):
    """
    從 pdp3 產生的 pos_ 檔中擷取 ECEF (ITRF) X/Y/Z。
    格式 (已於大屯火山案例驗證):
        *Name    Mjd    X    Y    Z    Sx  Sy  Sz  Rxy  Rxz  Ryz  Sig0  Nobs
         xxxx  56696.4984  -3011413.40444   4928283.01413   2697296.15105  ...
    取檔案中最後一行有效資料列 (欄位: [0]=站名 [1]=Mjd [2]=X [3]=Y [4]=Z)。
    """
    with open(pos_path, 'r', errors='ignore') as f:
        lines = f.readlines()

    data_line = None
    past_header = False
    for line in lines:
        if 'END OF HEADER' in line:
            past_header = True
            continue
        if not past_header:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            continue
        data_line = line
    if data_line is None:
        raise ValueError("找不到 END OF HEADER 之後的座標資料列")

    parts = data_line.split()
    if len(parts) < 5:
        raise ValueError(f"座標資料列欄位不足: {data_line!r}")

    try:
        x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
    except ValueError as e:
        raise ValueError(f"座標欄位無法轉成數字: {data_line!r}") from e

    return x, y, z


def check_redig_convergence(log_text):
    """檢查 pdp3 輸出中 redig 疊代是否真正收斂到 0。回傳 (converged: bool, detail: str)。"""
    text = strip_ansi(log_text)

    if 'execution failed' in text:
        m = re.search(r'\)\s*(\S[^\n]*?) execution failed', text)
        bad_cmd = m.group(1).strip() if m else '(未知指令)'
        return False, f"有步驟執行失敗: {bad_cmd}"

    idx = text.find('Data cleaning done')
    if idx == -1:
        return False, "log 中找不到 'Data cleaning done', 疊代未跑完整"

    segment = text[:idx]
    rem_matches = re.findall(r'Newly removed observations:\s*(\d+)\s+([\d.]+)%', segment)
    amb_matches = re.findall(r'Newly inserted ambiguities:\s*(\d+)\s+([\d.]+)%', segment)

    if not rem_matches or not amb_matches:
        return False, "找不到 redig 收斂統計 (NEWLY REMOVED / NEWLY AMBIGUT)"

    last_rem = int(rem_matches[-1][0])
    last_amb = int(amb_matches[-1][0])

    if last_rem == 0 and last_amb == 0:
        return True, f"完整收斂 (共 {len(rem_matches)} 輪 redig)"
    else:
        return False, f"未收斂到 0 (最後一輪: removed={last_rem}, ambiguities={last_amb})"


def run_pdp3(filepath, station, year, doy, force=False, timeout_sec=DEFAULT_TIMEOUT_SEC):
    work_dir = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{station.lower()}_{year}{doy}.log")

    existing_pos = sorted(glob.glob(os.path.join(work_dir, '**', 'pos_*'), recursive=True))
    if existing_pos and not force:
        print(f"    偵測到既有 pos_ 檔, 略過重跑 (使用 --force 可強制重跑)")
        log_text = ''
        if os.path.exists(log_path):
            with open(log_path, 'r', errors='ignore') as f:
                log_text = f.read()
        return existing_pos[-1], None, log_text

    systems = detect_gnss_systems(filepath)
    sys_str, frq_args, warn = build_sys_frq_args(systems)
    if warn:
        print(f"    [警告] {warn}")
    print(f"    偵測到系統: {sorted(systems) or '未知'} -> -sys {sys_str} -frq {' '.join(frq_args)}")

    cmd = ['pdp3', '-m', 'S', '-sys', sys_str, '-frq'] + frq_args + [basename]
    print(f"    執行: {' '.join(cmd)}  (log: {log_path}, timeout={timeout_sec // 60} 分鐘, "
          f"可用 tail -f 該 log 追蹤即時進度)")

    # pdp3 內部用 "echo $cmd | bash" 呼叫 lsq/redig/curl 等子程式, 會產生巢狀子行程。
    # subprocess.run(timeout=...) 逾時後只會 kill 最上層那個 process, 若孫行程仍占著
    # stdout/stderr 管線不放, Python 會卡在收尾階段等管線關閉, 導致 timeout 形同虛設。
    # 改用 Popen + start_new_session=True (獨立 process group) + 直接寫檔 (不用 PIPE),
    # 逾時時用 os.killpg 把整個 process group 一次砍乾淨, 不會卡住, 也讓 log 即時落地。
    timed_out = False
    returncode = None
    try:
        with open(log_path, 'wb') as logf:
            proc = subprocess.Popen(
                cmd, cwd=work_dir, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                proc.wait(timeout=timeout_sec)
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
    except FileNotFoundError:
        return None, "找不到 pdp3 指令, 請確認已安裝並在 PATH 中", ''

    log_text = ''
    if os.path.exists(log_path):
        with open(log_path, 'r', errors='ignore') as f:
            log_text = f.read()

    if timed_out:
        return None, f"pdp3 執行逾時 (超過 {timeout_sec // 60} 分鐘), 已強制終止整個 process group", log_text

    pos_files = sorted(glob.glob(os.path.join(work_dir, '**', 'pos_*'), recursive=True))
    if not pos_files:
        tail = strip_ansi(log_text)[-1500:].strip()
        reason = tail if tail else f"pdp3 執行結束 (returncode={returncode}) 但未產生 pos_ 檔"
        return None, reason, log_text

    return pos_files[-1], None, log_text


def main():
    parser = argparse.ArgumentParser(description="批次 PPP-static 解算 (美濃 IES 案例)")
    parser.add_argument('--force', action='store_true', help='即使已有 pos_ 檔也強制重跑')
    parser.add_argument('--stations', type=str, default=None,
                         help='只處理指定測站 (逗號分隔, 例如 S169,LNCH), 預設全部')
    parser.add_argument('--doy-min', type=int, default=DOY_RANGE[0])
    parser.add_argument('--doy-max', type=int, default=DOY_RANGE[1])
    parser.add_argument('--timeout-min', type=int, default=DEFAULT_TIMEOUT_SEC // 60,
                         help='單一站天處理逾時分鐘數 (預設 %(default)d)')
    args = parser.parse_args()

    timeout_sec = args.timeout_min * 60
    station_filter = None
    if args.stations:
        station_filter = {s.strip().upper() for s in args.stations.split(',') if s.strip()}

    all_tasks = find_rinex_tasks(DATA_DIR)
    doy_lo, doy_hi = args.doy_min, args.doy_max
    tasks = [t for t in all_tasks if doy_lo <= int(t['doy']) <= doy_hi]
    if station_filter:
        tasks = [t for t in tasks if t['station'] in station_filter]
    skipped = len(all_tasks) - len(tasks)
    total = len(tasks)
    print(f"掃描到 {len(all_tasks)} 個測站天, 限制範圍 DOY {doy_lo:03d}-{doy_hi:03d}"
          + (f", 測站={sorted(station_filter)}" if station_filter else "")
          + f" 後剩 {total} 個 (略過 {skipped} 個), 單站逾時上限 {args.timeout_min} 分鐘\n")

    results = []
    failures = []
    not_converged = 0

    for idx, task in enumerate(tasks, 1):
        station, year, doy = task['station'], task['year'], task['doy']
        src_desc = task['plain'] or task['gz']
        print(f"[{idx}/{total}] {station} {year} DOY{doy}  (來源: {os.path.basename(src_desc)})")

        try:
            filepath = ensure_decompressed(task)
        except Exception as e:
            print(f"    失敗: 解壓縮失敗 ({e})")
            failures.append((station, year, doy, os.path.basename(src_desc), f"解壓縮失敗: {e}"))
            continue

        pos_file, err, log_text = run_pdp3(filepath, station, year, doy, force=args.force, timeout_sec=timeout_sec)
        if err:
            reason_line = strip_ansi(err).strip().splitlines()[-1] if err.strip() else '未知原因'
            print(f"    失敗: {reason_line}")
            failures.append((station, year, doy, os.path.basename(filepath), err))
            continue

        try:
            x, y, z = parse_pos_file(pos_file)
        except Exception as e:
            print(f"    失敗: 已產生 {os.path.basename(pos_file)} 但解析座標失敗 ({e})")
            failures.append((station, year, doy, os.path.basename(filepath), f"解析 pos_ 檔失敗: {e}"))
            continue

        converged, detail = check_redig_convergence(log_text) if log_text else (None, "沿用先前結果, 未重新檢查收斂狀態")

        if converged is True:
            print(f"    成功: X={x:.4f} Y={y:.4f} Z={z:.4f}  [redig 收斂: {detail}]")
        elif converged is False:
            not_converged += 1
            print(f"    成功但需留意: X={x:.4f} Y={y:.4f} Z={z:.4f}  [redig 未收斂: {detail}]")
        else:
            print(f"    成功: X={x:.4f} Y={y:.4f} Z={z:.4f}  [{detail}]")

        results.append((station, year, doy, x, y, z, converged, detail))

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['station', 'year', 'doy', 'X', 'Y', 'Z', 'redig_converged', 'note'])
        for station, year, doy, x, y, z, converged, detail in results:
            conv_str = '' if converged is None else ('YES' if converged else 'NO')
            writer.writerow([station, year, doy, x, y, z, conv_str, detail])

    print("\n===== 總結 =====")
    print(f"總共測站天數: {total}")
    print(f"成功 (有產生 pos_ 檔): {len(results)}")
    print(f"  - 其中 redig 完整收斂: {sum(1 for r in results if r[6] is True)}")
    print(f"  - 其中 redig 未收斂/需留意: {not_converged}")
    print(f"失敗: {len(failures)}")
    if failures:
        print("\n失敗清單:")
        for station, year, doy, fn, reason in failures:
            short_reason = strip_ansi(reason).strip().splitlines()[-1] if reason.strip() else '未知原因'
            print(f"  - {fn} ({station} {year} DOY{doy}): {short_reason}")
    if not_converged:
        print("\nredig 未收斂清單 (結果仍寫入 CSV, 但建議留意精度):")
        for station, year, doy, x, y, z, converged, detail in results:
            if converged is False:
                print(f"  - {station} {year} DOY{doy}: {detail}")
    print(f"\n結果已輸出至: {OUTPUT_CSV}")
    print(f"各站逐檔完整 log 存於: {LOG_DIR}")
    print("\n[提醒] TSHO / YENC / WLIP 這 3 個測站目前找不到觀測資料, 未包含在本次結果中。")
    print("       之後若補齊資料, 放進同一個資料夾底下重跑本腳本即可自動納入 (已成功的站天會自動略過)。")


if __name__ == '__main__':
    main()

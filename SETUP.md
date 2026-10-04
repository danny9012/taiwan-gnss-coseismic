# 環境建置與重現指南(SETUP.md)

這份文件是給想要下載本專案、重現分析流程的人看的完整教學,涵蓋:PPP-AR 軟體安裝、兩個已知的軟體 bug 與修正方式、資料下載管道、以及如何執行本專案的分析腳本。目標是讓你不用重新踩一次原作者踩過的坑。

---

## 目錄

1. [安裝 PRIDE PPP-AR](#1-安裝-pride-ppp-ar)
2. [已知 bug 與修正(重要)](#2-已知-bug-與修正重要)
3. [下載 GNSS 觀測資料](#3-下載-gnss-觀測資料)
4. [下載 NGL 座標時間序列(交叉驗證用)](#4-下載-ngl-座標時間序列交叉驗證用)
5. [執行批次 PPP-AR 處理](#5-執行批次-ppp-ar-處理)
6. [執行 NGL 時間序列分析與統計檢定](#6-執行-ngl-時間序列分析與統計檢定)
7. [常見問題(踩坑記錄)](#7-常見問題踩坑記錄)

---

## 1. 安裝 PRIDE PPP-AR

本專案使用**武漢大學 GNSS 研究中心開發的 PRIDE PPP-AR**(v3)進行 PPP 模糊度解算,這是開源軟體。

**官方套件庫**:https://github.com/PrideLab/PRIDE-PPPAR

### 1.1 前置需求

安裝前確認系統已有以下套件:

| 套件 | 用途 | 是否必要 |
|---|---|---|
| `gfortran`(gcc 的子套件) | 編譯 Fortran 原始碼 | 必要 |
| `make`(GNU make) | 執行 `install.sh` 內部的 `make` / `make install` | 必要 |
| `wget` | 下載精密星曆/鐘差等軌道產品 | 必要 |
| `python3` | PRIDE PPP-AR 自帶的繪圖工具 | 選用(不用繪圖工具可省略) |
| `gfzrnx` | 多天批次處理需要 | 選用(不做多天批次可省略) |

> **踩坑記錄(2026-09-21 測試)**:原本這裡只列了 `gfortran wget python3`,但 `install.sh` 一開頭就會檢查 `gfortran`、`gcc`、`make` 三者是否存在,少了 `make` 會在編譯前直接印出 `error: GNU make not found` 並中止安裝。在全新的 Ubuntu 26.04 (WSL) 環境實測時就踩到這個問題,已補進上表。另外實測環境本身其實已經預裝了 `wget`、`python3`(並非「完全乾淨」),只缺 `gfortran`(帶出 `gcc`)和 `make`,建議重現此文件的人先各自確認一次目前狀態,不要預設全部都要裝。

**Ubuntu/Debian(或 WSL)**:
```bash
sudo apt update
sudo apt install gfortran make wget python3
```

**如果沒有 sudo 權限**(例如某些共用主機或雲端環境),可以改用 conda-forge 安裝 gfortran,不需要系統管理員權限:
```bash
# 先安裝 Miniforge(如果還沒有 conda 環境)
# https://github.com/conda-forge/miniforge
conda install -c conda-forge gfortran
```

**macOS**:
```bash
brew install gcc wget
# gfortran 也可以從 https://github.com/fxcoudert/gfortran-for-macOS/releases 下載安裝包
```

### 1.2 下載與安裝

```bash
git clone https://github.com/PrideLab/PRIDE-PPPAR.git
cd PRIDE-PPPAR
bash install.sh
```

安裝腳本會把編譯好的執行檔複製到 `~/.PRIDE_PPPAR_BIN/`,並自動加進你的 PATH。**安裝完成後,重新開一個終端機(或執行 `source ~/.bashrc`)讓 PATH 生效。**

> **踩坑記錄(2026-09-21 測試)**:實測 `install.sh` 全程只有一個互動問題 ——「Run tests or not」(Y/N),**沒有**出現「選擇 IGN 或其他下載站點」的提示。所謂 IGN 站點,其實是寫死在 `scripts/pdp3.sh` 裡的其中一個自動下載來源(`igs.ign.fr`,程式會在下載軌道/鐘差產品時依序自動嘗試多個站點,包括 WHU、CDDIS、IGN 等),**不是安裝時會問你的問題**,使用者不需要也無法在安裝過程中手動選站點。這段文件描述跟實際行為不符,已在此更正。
>
> 另外,若你是用非互動式腳本或背景執行(例如 `echo "Y" | bash install.sh > log 2>&1 &`)來跑 `install.sh`,腳本內部在選擇跑測試(Y)時會呼叫 `source ~/.bashrc` 來讓 PATH 生效,但 Ubuntu 預設的 `~/.bashrc` 開頭有：
> ```bash
> case $- in
>     *i*) ;;
>       *) return;;
> esac
> ```
> 在非互動式 shell 裡執行到這裡就會直接 `return`,PATH 不会真的更新,導致腳本自帶的測試步驟出現 `error: PRIDE PPP-AR 3 lsq not found` 而失敗 —— 但這不代表編譯失敗,`make`/`make install` 通常已經成功、執行檔也已經複製到 `~/.PRIDE_PPPAR_BIN/`。實測時就遇到這個情況:編譯與安裝訊息都顯示成功,只有安裝腳本自帶的測試段因為 PATH 沒生效而報錯。**判斷安裝是否成功,請看有沒有印出 `PRIDE-PPPAR (v3.2.11) installation successfully completed!` 那段訊息,而不是看測試段是否通過**;如果要讓測試段也一起跑,建議在真正的互動式終端機手動執行 `install.sh`,或是自己重開一個終端機、`export PATH` 後再手動跑 `example/test.sh`。

### 1.3 驗證安裝

```bash
which pdp3
pdp3 -H
```

如果能看到說明文字,代表安裝成功。

> **踩坑記錄(2026-09-21 測試)**:原文寫的是 `pdp3 -h`(小寫),實測會直接報錯：
> ```
> error: invalid argument (the last argument should be observation file): -h
> :: use ‘pdp3 -H’ or ‘pdp3 --help’ for more information
> ```
> `pdp3` 的說明旗標是**大寫** `-H`(或 `--help`),小寫 `-h` 不是有效參數,已更正上面的指令。此外實測時還出現一行警告(不影響功能,但值得留意)：
> ```
> pdp3: line 52: warning: setlocale: LC_NUMERIC: cannot change locale (en_US.UTF-8): No such file or directory
> ```
> 這是因為全新環境通常沒有產生 `en_US.UTF-8` locale。若想消除這個警告,可以執行 `sudo locale-gen en_US.UTF-8 && sudo update-locale`,但不裝也不影響 `pdp3` 的核心功能。

### 1.4 引用聲明

如果你用這個軟體發表研究,依官方要求需要引用:

> Geng J, Chen X, Pan Y, Zhao Q (2019). A modified phase clock/bias model to improve PPP ambiguity resolution at Wuhan University. *Journal of Geodesy*, 93(10):2053-2067.
> Geng J, Chen X, Pan Y, Mao S, Li C, Zhou J, Zhang K (2019). PRIDE PPP‑AR: an open‑source software for GPS PPP ambiguity resolution. *GPS Solutions*, 23(91):1-10.

---

## 2. 已知 bug 與修正(重要)

原作者在處理過程中發現兩個會影響結果正確性的 bug。**這兩個 bug 可能已經在你下載的版本裡修好了**(官方持續在更新 pdp3 的相關問題),所以第一步是**先確認症狀是否存在**,再決定要不要手動修補。

> **踩坑記錄(2026-09-21 測試)**:實測時 clone 的是官方 repo 當時的最新版(`master` 分支,commit `87c3322`,`install.sh` 版本號 v3.2.11),**兩個 bug 都還存在,官方尚未修復**,套用下面的 diff 後重新編譯(`cd PRIDE-PPPAR/src && make clean && make && make install`)全部正常,沒有出現編譯錯誤。也就是說目前不能假設「官方已修好」,還是要照下面的方式實際檢查後手動 patch。
>
> **另外有個很重要的環境陷阱**:如果你是在 **Claude Code CLI** 或類似會把 `grep` 包裝成 `ugrep` 的環境裡執行下面的檢查指令,文件裡給的 `grep -n "ts_sec=\$(echo" ...` 這個寫法可能會**誤判成「找不到」**(即使 bug 明明存在)——原因是這類環境常把 `grep` 重新定義成一個 shell function,底層呼叫 `ugrep -G ...`,而 `ugrep` 對 `$(` 這種正規表示式的處理跟標準 GNU grep 不完全一致,导致同一個 pattern 用 GNU grep 找得到、用包裝過的 `grep` 卻找不到。**檢查前務必先確認自己實際用的是哪個 `grep`**:
> ```bash
> type grep          # 如果顯示 "grep is a function" 或指到非 /usr/bin/grep 的路徑,要小心
> /bin/grep -n "ts_sec=\$(echo" ~/.PRIDE_PPPAR_BIN/pdp3   # 直接指定系統的 GNU grep,避免被殼層的 grep 別名/function 誤導
> ```
> 為避免任何人被這個環境差異誤導成「以為已經修復」,以下第 2.1、2.2 節的檢查指令都建議加上 `/bin/grep`(而非直接呼叫 `grep`)。

### 2.1 pdp3 跨日期進位捨入錯誤

**症狀**:批次處理某些站天時,`spp`(單點定位)步驟無預警崩潰,尤其容易發生在接收儀第一個 epoch 的時鐘偏移剛好接近午夜整數的情況。

**原因**:pdp3 內部計算 epoch 時間時,捨入結果可能等於 86400 秒(也就是隔天的 24:00:00,實際上應該進位成隔天的 00:00:00),導致後續程式邏輯出錯。

**檢查方式**:在你的 `pdp3` 檔案(通常在 `~/.PRIDE_PPPAR_BIN/pdp3`)裡搜尋這幾行(**建議用 `/bin/grep` 而非直接打 `grep`**,理由見上方踩坑記錄):
```bash
/bin/grep -n "ts_sec=\$(echo" ~/.PRIDE_PPPAR_BIN/pdp3
```

**修正 diff**(如果你的版本症狀存在,套用這個修改):
```diff
876c876
<     ts_sec=$(echo "$hms_s" | awk -F: '{print $1*3600 + $2*60 + $3}')
---
>     ts_sec=$(echo "$hms_s" | awk -F: '{printf("%.7f", $1*3600 + $2*60 + $3)}')
878,880c878,880
<     print int((ts + b - 1e-9)/b)*b
---
>     v=int((ts + b - 1e-9)/b)*b
>     if (v>=86400) v=int(ts/b)*b
>     print v
```

（用更高精度的 `printf` 計算秒數,並加上明確的邊界檢查,避免捨入結果超過一天的秒數上限。）

### 2.2 redig 的 Fortran 格式字串錯誤

**症狀**:某些站天的 `redig`(疊代去雜訊/模糊度收斂)步驟會提早中止(log 裡出現 `jmp=400` 附近就停止),沒有跑完應有的收斂輪次,可能造成約 1.2-1.7cm 的座標誤差,而且不會有明顯的錯誤訊息——很容易被誤以為「這站正常跑完了」。

**原因**:redig 原始碼裡一個 Fortran 格式字串少打了逗號,導致編譯器誤判欄位寬度。

**檢查方式**:在 redig 的原始碼(通常在你 clone 的 `PRIDE-PPPAR/src/redig/get_redig_args.f90`)裡搜尋(同樣建議用 `/bin/grep`):
```bash
/bin/grep -n "4xi4i3" PRIDE-PPPAR/src/redig/get_redig_args.f90
```
如果找不到(表示格式字串已經是正確的),就不用修改。如果找到,套用下面的修正:

**修正 diff**:
```diff
- read (resfil(i:), '(4xi4i3)', err=200) jy, jdoy
+ read (resfil(i:), '(4X,I4,I3)', err=200) jy, jdoy
```

修改完原始碼後,需要重新編譯 redig 這個模組(通常整個套件重新 `make` 一次最保險):
```bash
cd PRIDE-PPPAR/src
make
make install
```

> **踩坑記錄(2026-09-21 測試)**:原文寫的 `cd PRIDE-PPPAR && make` 實測會失敗:
> ```
> make: *** No targets specified and no makefile found.  Stop.
> ```
> 因為 `Makefile` 其實放在 `PRIDE-PPPAR/src/` 底下,repo 根目錄並沒有 `Makefile`。已更正為 `cd PRIDE-PPPAR/src && make`。重新編譯完之後,`make install` 只會把新的執行檔搬到 `PRIDE-PPPAR/bin/`,**不會**自動更新到 `~/.PRIDE_PPPAR_BIN/`(那是 `install.sh` 才會做的事),如果要讓修好的 `redig`(或 `pdp3`)真正生效,還需要手動複製一次,或整個重跑 `bash install.sh`:
> ```bash
> cp -f ../bin/redig ~/.PRIDE_PPPAR_BIN/redig
> chmod 755 ~/.PRIDE_PPPAR_BIN/redig
> ```
> 實測套用兩個 patch 後重新編譯,`make`/`make install` 皆無錯誤,`pdp3 -H` 與 `redig`(不帶參數執行看說明)都能正常印出說明文字,確認 patch 沒有破壞既有功能。

**這個 bug 是機率性的**——只有在接收儀第一個 epoch 的時鐘偏移剛好觸發特定條件時才會出現,不是每次都會發生,所以就算你的批次資料大部分正常,也不代表完全沒有踩到過。**建議處理完一批資料後,檢查每個站天的 log 裡有沒有正常跑到 `Data cleaning done` 且收斂輪次的 `Newly removed observations` / `Newly inserted ambiguities` 都降到 0**(本專案的 `process_ppp_ies.py` 已經內建這個檢查,見第 5 節)。

---

## 3. 下載 GNSS 觀測資料

本專案分析的資料來自兩個台灣的 GNSS 觀測網,都透過中央氣象署的 GDMS(地球物理資料管理系統)下載:

**網站**:https://gdms.cwa.gov.tw/map.php

1. 進入網站後,在「觀測網」下拉選單選擇 **GNSS**(中央氣象署官方網路)或 **GNSS_IES**(中研院地球所獨立網路,可作交叉驗證用)
2. 用地圖或測站查詢功能篩選你要分析的區域跟時間範圍
3. 下載 RINEX 格式的觀測檔(`.XXo` 或 `.XXo.gz`)

**GNSS_IES 測站代碼可能跟其他資料庫(例如 NGL)不同**,常見的代碼對應(本專案已確認的部分):

| GDMS/GNSS_IES 代碼 | NGL 代碼 |
|---|---|
| PAOL | PAO1 |
| S106 | T106 |
| YENC | YEN2 |
| SCHN | SCH7 |
| HUAL | HUA3 |
| SLIN | SLI1 |

如果你分析的是其他站,遇到「NGL 上查不到這個站」的情況,先用座標比對確認是不是代碼不同,而不是直接判定沒有資料。

---

## 4. 下載 NGL 座標時間序列(交叉驗證用)

NGL(Nevada Geodetic Laboratory)提供獨立處理的座標時間序列,可用來交叉驗證你自己的 PPP-AR 結果,或在時間有限時直接作為分析資料源。

**網站**:https://geodesy.unr.edu/NGLStationPages/gpsnetmap/GPSNetMap.html

1. 用地圖瀏覽介面找到你要的測站(或直接組網址 `https://geodesy.unr.edu/NGLStationPages/stations/<站碼>.sta` 查詢)
2. 頁面上會顯示座標(可用來核對是不是你要找的站,避免代碼碰撞)跟資料涵蓋的時間範圍
3. 下載「24 Hour Final Solutions」的 tenv3 格式檔案(ASCII 文字檔)

**引用聲明**:依 NGL 使用條款,使用其資料需引用:
> Blewitt, G., W. C. Hammond, and C. Kreemer (2018), Harnessing the GPS data explosion for interdisciplinary science, *Eos*, 99, https://doi.org/10.1029/2018EO104623

**注意**:GNSS_IES 網的資料在 NGL 上可能有系統性的更新截止日期(跟地震本身無關,是資料流本身的限制),下載前先確認涵蓋範圍是否包含你要分析的地震日期。

---

## 5. 執行批次 PPP-AR 處理

用本專案的 `scripts/process_ppp_ies.py` 批次處理多個測站、多天的 RINEX 觀測檔。

```bash
cd <你的資料夾,裡面放 RINEX 觀測檔>

# 可選:用環境變數指定資料夾路徑(不設定的話會用腳本裡的預設值,記得先改成你自己的路徑)
export PPP_IES_DATA_DIR="$(pwd)"

python3 process_ppp_ies.py --stations LNCH,DONA --doy-min 32 --doy-max 38 --timeout-min 180
```

**參數說明**:
- `--stations`:只處理指定測站(逗號分隔),不指定則處理全部找到的站
- `--doy-min` / `--doy-max`:限制處理的積日(day-of-year)範圍
- `--timeout-min`:單一站天的處理逾時上限(分鐘),預設 180 分鐘(3 小時)——之所以設這麼寬鬆,是因為震當天的資料常需要更多輪疊代才能收斂,設太緊會誤殺合理但需要較長時間的處理
- `--force`:即使已經有成功結果也強制重跑

**建議用背景執行,避免處理時間過長時終端機斷線導致中斷**:
```bash
nohup python3 process_ppp_ies.py --stations LNCH,DONA --doy-min 32 --doy-max 38 --timeout-min 180 > batch.log 2>&1 &
echo "已啟動,PID=$!"
```

處理完成後,結果會寫入 `ppp_results_ies.csv`,每個站天的完整 log 存在 `pdp3_logs/` 資料夾。

---

## 6. 執行 NGL 時間序列分析與統計檢定

### 6.1 繪製 ENU 時間序列圖

直接用命令列工具 `plot_timeseries.py`,不用自己寫 Python 程式碼:

```bash
python3 plot_timeseries.py <你篩選好的tenv3檔案> \
    --quake-date 2016-02-06 \
    --station LNCH \
    --label "M6.6 Meinong Earthquake" \
    --out lnch_timeseries.png
```

**參數說明**:
- `<tenv3檔案>`:已篩選好單一測站、時間窗的 tenv3 檔案路徑(必填,第一個位置參數)
- `--quake-date`:地震日期,格式 `YYYY-MM-DD`,圖上會畫紅色虛線標示
- `--station`:測站名稱,顯示在圖的標題
- `--label`:地震描述文字(例如規模、名稱),顯示在圖的副標題
- `--out`:輸出檔名(選填,預設 `<測站名稱>_timeseries.png`)
- `--day-interval`:X 軸日期刻度間隔天數(選填,預設 1;時間窗較長時可設 2 或更大避免刻度擠在一起)

執行後會印出資料涵蓋範圍,以及 East/North/Up 三分量「第一天 → 最後一天」的位移量,方便快速確認數字合理再去看圖。

如果你想在自己的 Python 腳本裡呼叫底層函式(例如要客製化繪圖邏輯),`ngl_timeseries.py` 這個函式庫本身的函式(`load_tenv3`、`to_relative_mm`、`plot_enu_timeseries` 等)都可以直接 import 使用,`plot_timeseries.py` 的原始碼就是一個現成的呼叫範例。

### 6.2 統計顯著性檢定

```bash
python3 statistical_significance.py <tenv3窗口檔案> --n-pre <震前天數>
```

會針對 East/North/Up 三分量各自輸出 t 值、p 值,以及顯著性判斷(顯著/邊界/不顯著)。統計原理(虛無假設、對立假設、t 分布 vs 常態分布的差異)詳見主 README 的「統計顯著性檢定結果」段落。

---

## 7. 常見問題(踩坑記錄)

以下是原作者在建立本專案過程中實際遇到的問題,幫你提前避開:

1. **`nohup ... > log 2>&1 &` 看起來「卡住沒進度」**:Python 的 `print()` 輸出在重導向到檔案時預設是整塊緩衝(full buffering),不是逐行輸出,進度訊息會累積在記憶體緩衝區、沒有即時寫進 log 檔,看起來像沒有反應,其實程式一直在正常跑。解法:用 `python3 -u`(unbuffered)執行,或在腳本開頭加 `sys.stdout.reconfigure(line_buffering=True)`(本專案的 `process_ppp_ies.py` 已經內建這個修正)。

2. **`subprocess.run(timeout=...)` 沒有真的生效**:如果你自己寫批次腳本呼叫 pdp3,要注意 pdp3 內部用 `echo "$cmd" | bash` 呼叫子程序,會產生巢狀子行程。Python 的 timeout 機制在這種情況下可能卡在等待管線關閉,即使設定的 timeout 時間到了也不會確實觸發。解法:改用 `subprocess.Popen(..., start_new_session=True)` 搭配 `os.killpg()` 對整個 process group 送出終止訊號(本專案的 `process_ppp_ies.py` 已經這樣處理)。

3. **timeout 設太短會誤殺合理的長時間處理**:震當天的資料有時需要遠超過平常(35-50分鐘)的時間才能收斂(訊號受同震擾動影響),但這不是每個測站的震當天都會發生,是個別站的資料品質問題。建議 timeout 抓寬鬆一點(例如 3 小時),避免誤判失敗。

4. **背景執行的環境限制**:如果你是在 Claude Code(或類似的 AI 編碼助手)的對話視窗裡啟動長時間批次工作,助手自己的背景執行機制通常會在對話 session 結束或終端機關閉時中斷。長時間批次建議在獨立的終端機用 `nohup ... &` 執行。另外作業系統的睡眠/休眠也會中斷背景程序,長時間批次執行期間記得先關閉系統睡眠設定。如果中途需要暫時斷網或做其他事,可以用 `kill -STOP <PID>` 暫停(不是終止)整個 process,之後用 `kill -CONT <PID>` 恢復,不會遺失已完成的進度(針對整個 process group 記得在 PID 前加負號,例如 `kill -STOP -<PID>`)。

5. **測站代碼在不同資料庫間不一致**:GDMS/GNSS_IES 的站碼跟 NGL 的站碼可能不同(見第 3 節的對應表)。查不到站不代表沒有資料,先用座標比對確認。

6. **統計顯著性判斷不能用固定的 3-sigma/2-sigma 門檻**:震前樣本數通常只有 4-7 天,樣本數這麼小應該用 t 分布依實際自由度動態算臨界值,用常態分布的固定門檻會高估顯著性,誤判邊界案例為「顯著」。詳見主 README。

7. **資料源混用時要清楚標註**:如果同時用了自行 PPP-AR 的結果跟 NGL 現成結果,兩者的參考框架(ITRF 版本)、處理鏈可能不同,絕對座標可能有系統性偏移。如果兩者算出的位移量差了一個數量級以上且方向不一致,不要急著採信任一邊,先確認站是否正確、再排查框架版本問題,無法排除疑慮前不要引用該站數字。

---

有任何問題或發現新的坑,歡迎開 issue 或 PR 補充這份文件。

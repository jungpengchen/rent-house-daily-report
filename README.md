# 591 台北租屋日報爬蟲

每日自動爬取符合條件的台北市租屋物件，透過 Telegram / Email / LINE Notify 發送日報。

## 功能特色

- **多源爬取**：591 租屋網（主要）、PTT 租屋版、Dcard 租屋版
- **智慧過濾**：
  - 樓層與電梯邏輯（排除 1 樓、地下室、頂樓加蓋；3 樓以上需有電梯）
  - 家具狀態標記（⭐ 空屋 / ⚠️ 拎包入住）
  - 捷運距離過濾（800 公尺內）
- **跨平台去重**：同一物件只顯示一筆，附上各平台連結
- **每日新物件**：比對資料庫，只發送前日未出現的物件
- **多管道通知**：Telegram、Email、LINE Notify

## 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt
playwright install chromium  # 若啟用 Playwright 模式

# 2. 設定環境變數
cp .env.example .env
# 編輯 .env 填入 Telegram Bot Token 等設定

# 3. 調整搜尋條件（選填）
# 編輯 config.yaml

# 4. 立即執行一次
python main.py

# 5. 或啟動每日排程（每天 08:00 自動執行）
python main.py --schedule

# 測試模式（不發送通知、不更新資料庫）
python main.py --dry-run
```

## 搜尋條件（Phase 1）

| 條件 | 預設值 |
|------|--------|
| 縣市 | 台北市 |
| 類型 | 整層住家、獨立套房 |
| 最高租金 | 38,000 元 |
| 最小坪數 | 20 坪 |
| 特色標籤 | 可開伙 |

## 過濾邏輯（Phase 2）

### 樓層 & 電梯
- **排除**：1 樓、地下室、頂樓加蓋
- **2 樓**：直接保留（不檢查電梯）
- **3 樓以上**：必須有「有電梯」標籤

### 家具狀態
- 有「拎包入住」標籤 → ⚠️ 可能有電視/床墊，需與房東協商撤走
- 空屋或無拎包標記 → ⭐ 極佳物件：適合自備家具

## 捷運距離過濾（Phase 3）

限制物件距以下捷運站 800 公尺以內：
- **板南線**（東段）：忠孝新生 ～ 南港展覽館
- **松山新店線**（部分）：松江南京 ～ 松山
- **文湖線**：南京復興 附近

## 環境變數

| 變數 | 說明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 接收訊息的 Chat ID |
| `EMAIL_USERNAME` | Gmail 帳號 |
| `EMAIL_PASSWORD` | Gmail App Password |
| `EMAIL_TO` | 收件者信箱 |
| `LINE_NOTIFY_TOKEN` | LINE Notify Token |

## 專案結構

```
├── main.py              # 主程式入口
├── config.yaml          # 搜尋與過濾設定
├── crawlers/
│   ├── crawler_591.py   # 591 租屋網爬蟲
│   ├── crawler_ptt.py   # PTT 租屋版爬蟲
│   └── crawler_dcard.py # Dcard 租屋版爬蟲
├── normalizer.py        # 資料規格化
├── filters.py           # 過濾邏輯
├── deduplicator.py      # 跨平台去重
├── database.py          # SQLite 資料庫
├── report_generator.py  # 日報格式化
├── notifier.py          # 通知發送
└── mrt_data.py          # 捷運站座標資料
```

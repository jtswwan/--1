# 降價追蹤器

追蹤 91app（NineYi）平台商店的商品，一變便宜就寄 email 給你。

目前追的是 HOME SHOP 的「【初秋新品】HS 後鬆緊都會長裙 墨灰色」。

## 為什麼不能只看價格

這很重要，不然你會以為程式壞了：**商品頁上的 `Price` 欄位永遠是 2,190，不會因為打折而變動。**
79 折是掛在「促銷活動」清單裡的一檔活動（`【春夏單品】單件79折`），而且折扣率只寫在活動**名稱**裡，
API 不會給你折後數字。

所以這支程式做兩件事：

1. 讀出原價（`SuggestPrice` / `Price`）
2. 讀出進行中的活動清單，從名稱裡解析出「單件就能用」的折扣率，算出實際要付多少

滿額、滿件的活動（例如「滿額現折」「第二件5折」）不列入計算，因為單買一件吃不到，
但還是會列在信裡供參考。

## 安裝

不需要任何套件，Python 3.11 以上即可（只用標準函式庫）。

```bash
python -m tracker --dry-run   # 查一次並印出，不寄信也不寫檔
```

輸出長這樣：

```
【初秋新品】HS 後鬆緊都會長裙 墨灰色
  定價 NT$2,190 / 售價 NT$2,190 / 實付 NT$1,730（約 79折）
    【官網限定】雙11預購會，滿額現折再送券（需湊滿額），至 2026-11-04
  * 【春夏單品】單件79折（79折），至 2026-10-31
    加購限定優惠款，至 2026-10-31
```

`*` 標的那檔就是目前算進實付價的折扣。

## 設定要追什麼

編輯 `config.json`：

```json
{
  "watches": [
    {
      "id": "homeshop-11207741",
      "label": "【初秋新品】HS 後鬆緊都會長裙 墨灰色",
      "url": "https://bmai.app/2b776daf",
      "target_price": null
    }
  ]
}
```

- `url` 可以直接貼 bmai.app 的短網址，程式會自己解出真正的商品頁
- `target_price`：設成數字（例如 `1500`）就只有降到這個價以下才寄信；留 `null` 的話只要有降就寄
- 要追更多商品就在 `watches` 裡多加幾個，`id` 不要重複

想「再等折扣多些」的話，把 `target_price` 設在現在的 1,730 以下，例如 `1500`（約 68 折）。

## 設定信箱

用環境變數，不要寫進檔案：

| 變數 | 說明 |
| --- | --- |
| `SMTP_HOST` | 例如 `smtp.gmail.com` |
| `SMTP_PORT` | 預設 `587`；填 `465` 會自動改用 SSL |
| `SMTP_USER` | SMTP 帳號 |
| `SMTP_PASS` | SMTP 密碼。**Gmail 要用「應用程式密碼」，不是你的登入密碼** |
| `MAIL_FROM` | 寄件人，省略的話就用 `SMTP_USER` |
| `MAIL_TO` | 收件人，多個用逗號分隔 |

Gmail 的應用程式密碼要先開兩步驟驗證，再到 Google 帳戶 → 安全性 → 應用程式密碼 產生一組 16 碼。

測一下信箱通不通：

```bash
export SMTP_HOST=smtp.gmail.com SMTP_USER=你的@gmail.com SMTP_PASS=應用程式密碼 MAIL_TO=你的@gmail.com
python -m tracker --force
```

## 排程執行

### GitHub Actions（不用自己的機器）

1. 把上面那些變數加進 repo 的 Settings → Secrets and variables → Actions
2. `.github/workflows/track.yml` 預設每天台灣時間 09:00、13:00、17:00、21:00 各查一次
3. 每次查完會把 `state.json` commit 回 repo，當作下次比價的基準

也可以到 Actions 頁手動按 Run workflow，勾 `force` 就會寄一封測試信。

### 自己的機器

```cron
0 9,13,17,21 * * * cd /path/to/repo && /usr/bin/python3 -m tracker >> tracker.log 2>&1
```

## 通知規則

- **第一次執行不寄信**，只記錄現在的價格當基準
- 之後只要實付價比上次低就寄信（設了 `target_price` 的話還要降到目標價以下）
- 價格沒變或變貴都不吵你
- 信裡會寫現在多少、上次多少、省多少、是哪檔活動給的折扣

## 測試

```bash
pip install pytest
python -m pytest tests -q
```

## 檔案

```
tracker/discount.py   把「單件79折」這種活動名稱解析成 0.79，算出實付價
tracker/source.py     抓商品頁、解析內嵌的 JSON（含 bmai.app 短網址還原）
tracker/notify.py     組信並用 SMTP 寄出
tracker/state.py      上次的價格紀錄
tracker/__main__.py   指令列進入點與通知判斷
config.json           要追蹤的商品
state.json            自動產生的價格紀錄，不要手動改
```

## 已知限制

- 折扣率是從活動名稱的中文解析出來的。如果店家把活動取名成「限時優惠」這種沒有數字的，
  程式算不出折扣，會以原價計算（不會誤報降價，但可能漏掉）。
- 滿額、滿件的折扣不列入實付價計算。
- 只支援 91app / NineYi 平台的商店頁（`*/SalePage/Index/*`）。

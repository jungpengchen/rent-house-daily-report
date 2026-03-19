FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴（Playwright 需要）
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn flask

# 安裝 Playwright 瀏覽器
RUN playwright install chromium --with-deps

# 複製程式碼
COPY . .

# 建立資料目錄
RUN mkdir -p data

EXPOSE 8080

CMD ["gunicorn", "server:app", "-b", "0.0.0.0:8080", "--timeout", "300", "--workers", "1"]

FROM python:3.9-slim

WORKDIR /app

# 시스템 종속성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python 종속성 설치
COPY . .
RUN pip install --no-cache-dir .

# 포트 노출
EXPOSE 8000

# 기본 명령 설정
CMD ["docx-to-daisy-api"] 
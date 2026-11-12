FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
RUN useradd -m -u 1000 hub && mkdir -p /data /payslips && chown hub /data /payslips
USER hub
ENV FINANCE_HUB_DB=/data/finance.db IMPORT_ARCHIVE_DIR=/data/imports PAYSLIP_DIR=/payslips
EXPOSE 8092
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8092"]

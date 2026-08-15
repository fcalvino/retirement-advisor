FROM python:3.12-slim

WORKDIR /app

# No system compiler needed: every dependency in requirements.lock ships a
# manylinux wheel. gcc/g++ used to be here for pandas-ta (and its numba/llvmlite
# chain), which was dead code and was removed. Verified with:
#   uv pip compile requirements.txt --python-platform x86_64-manylinux_2_28 \
#     --only-binary :all:

# Reproducibility (audit D5): the image installs from the hash-pinned lockfile,
# not from the loose `>=` ranges. Two builds of the same commit therefore run
# the exact same numpy/scipy/pandas — a bump in any of those moves the numbers
# a retirement plan is built on. requirements.txt is copied only so the lock can
# be regenerated inside the image if needed (`make lock`).
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .

# SQLite data dir persisted via volume mount
RUN mkdir -p data/db reports

# Streamlit config — disable telemetry and set server options
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ENABLE_CORS=false

EXPOSE 8501

# python:3.12-slim has no curl — use urllib (same as docker-compose healthcheck)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"

CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0"]

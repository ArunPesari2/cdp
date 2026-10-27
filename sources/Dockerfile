# Mock source systems, run as Cloud Run jobs. Build context: repository root.
FROM python:3.11-slim
WORKDIR /app
COPY libs/cdp_common libs/cdp_common
COPY sources sources
RUN pip install --no-cache-dir ./libs/cdp_common ./sources
ENTRYPOINT ["python", "-m"]
CMD ["cdp_sources.care.mock_vendor", "--help"]

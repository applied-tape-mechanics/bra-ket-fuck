FROM python:3.12-slim AS base
WORKDIR /app

COPY . .

# Test stage: includes Node.js to run both Python and JS verification suites + differential fuzzer
FROM base AS test
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
CMD ["sh", "-c", "python3 tests/test_vm.py && node tests/test_vm.js && python3 tests/test_fuzz.py && python3 tools/gen_paper_tables.py --check"]

# Production CLI & Web Workbench stage
FROM python:3.12-slim AS production
WORKDIR /app

COPY src/ ./src/
COPY examples/ ./examples/
COPY papers/ ./papers/
COPY ui/ ./ui/
COPY index.html README.md LICENSE ./

EXPOSE 8085

ENTRYPOINT ["python3", "/app/src/braketfuck.py"]
CMD ["/app/examples/shor_15_recycled_opt.bfk", "-q", "5", "-s", "256", "--shor"]

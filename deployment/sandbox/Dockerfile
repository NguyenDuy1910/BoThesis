# The artifact sandbox image. Built once locally (make sandbox-image); the API
# creates a disposable container from it for every document operation.
#
# It contains only Python and the document libraries the runner may use. The
# runner script itself is not baked in: the backend ships its own copy into
# /workspace/context on each run, so image and code cannot drift apart.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
        python-docx==1.2.0 \
        markdown==3.9 \
        xhtml2pdf==0.2.17 \
    && mkdir -p /workspace \
    && chown 65534:65534 /workspace

USER 65534:65534
WORKDIR /workspace

FROM python:3.10-slim

WORKDIR /app

# Create a non-root user (Hugging Face requirement)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

COPY --chown=user requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Expose default port (Render will override this via $PORT env var)
ENV PORT=8080
EXPOSE 8080

CMD ["python3", "-m", "WebStreamer"]

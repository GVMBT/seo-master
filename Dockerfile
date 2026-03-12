FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies (without project — code not copied yet)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY . .

# Install the project itself (after code is copied, for proper python -m bot)
RUN uv sync --frozen --no-dev --no-editable

# Railway injects PORT env var
ENV PORT=8080
EXPOSE 8080

# Run the bot
CMD ["uv", "run", "--no-dev", "python", "-m", "bot"]

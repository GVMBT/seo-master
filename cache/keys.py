"""Redis key namespaces and TTL constants."""

# TTL values in seconds
FSM_TTL = 86400  # 24 hours
PUBLISH_LOCK_TTL = 300  # 5 minutes
CLEANUP_LOCK_TTL = 300  # 5 minutes
NOTIFY_LOCK_TTL = 300  # 5 minutes
BRANDING_TTL = 604800  # 7 days
SERPER_TTL = 86400  # 24 hours
PINTEREST_AUTH_TTL = 1800  # 30 minutes
RATE_LIMIT_WINDOW = 3600  # 1 hour (default for per-action rate limits)
PROMPT_CACHE_TTL = 3600  # 1 hour (prompts change only on sync_prompts CLI)
USER_CACHE_TTL = 300  # 5 minutes (AuthMiddleware user cache)


class CacheKeys:
    """Redis key builders for all namespaces."""

    @staticmethod
    def fsm(user_id: int) -> str:
        return f"fsm:{user_id}"

    @staticmethod
    def throttle(user_id: int, action: str) -> str:
        return f"throttle:{user_id}:{action}"

    @staticmethod
    def publish_lock(idempotency_key: str) -> str:
        return f"publish_lock:{idempotency_key}"

    @staticmethod
    def branding(project_id: int) -> str:
        return f"branding:{project_id}"

    @staticmethod
    def serper(query_hash: str) -> str:
        return f"serper:{query_hash}"

    @staticmethod
    def pinterest_auth(nonce: str) -> str:
        return f"pinterest_auth:{nonce}"

    @staticmethod
    def rate_limit(user_id: int, action: str) -> str:
        return f"rate:{user_id}:{action}"

    @staticmethod
    def cleanup_lock(msg_id: str) -> str:
        return f"cleanup_lock:{msg_id}"

    @staticmethod
    def notify_lock(msg_id: str) -> str:
        return f"notify_lock:{msg_id}"

    @staticmethod
    def prompt_cache(task_type: str) -> str:
        return f"prompt:{task_type}"

    @staticmethod
    def user_cache(user_id: int) -> str:
        return f"user:{user_id}"

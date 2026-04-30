import json
import secrets


def levenshtein(a: str, b: str, max_dist: int = 2) -> int:
    a = a.lower().strip()
    b = b.lower().strip()
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        min_val = dp[0]
        for j in range(1, m + 1):
            temp = dp[j]
            dp[j] = prev if a[i - 1] == b[j - 1] else 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
            if dp[j] < min_val:
                min_val = dp[j]
        if min_val > max_dist:
            return max_dist + 1
    return dp[m]


def generate_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def parse_likely_languages(val: str | None) -> list[str]:
    if not val:
        return []
    try:
        return json.loads(val)
    except Exception:
        return []

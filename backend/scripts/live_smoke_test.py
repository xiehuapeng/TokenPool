"""Run an opt-in real DeepSeek end-to-end smoke test against a running gateway.

The script never prints the generated team API Key or the upstream provider Key.
"""

import json
import os
import sys
from typing import Any

import httpx

from app.config.settings import get_settings


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def usage_matches(log: dict[str, Any], usage: dict[str, Any]) -> bool:
    return all(
        log.get(log_name) == usage.get(api_name)
        for log_name, api_name in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        )
    )


def main() -> int:
    settings = get_settings()
    provider_key = settings.deepseek_api_key.get_secret_value()
    admin_password = settings.admin_password.get_secret_value()
    require(bool(provider_key), "DEEPSEEK_API_KEY is not configured")
    require(bool(admin_password), "ADMIN_PASSWORD is not configured")

    gateway_root = os.getenv("GATEWAY_ROOT_URL", "http://127.0.0.1:8000").rstrip("/")
    timeout = httpx.Timeout(connect=10, read=180, write=30, pool=10)
    team_key_id: int | None = None

    with httpx.Client(base_url=gateway_root, timeout=timeout) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "username": settings.admin_username,
                "password": admin_password,
            },
        )
        require(login.status_code == 200, f"Admin login failed: {login.status_code}")
        web_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }

        created = client.post(
            "/api/me/api-keys",
            headers=web_headers,
            json={"name": "temporary-live-smoke-test"},
        )
        require(created.status_code == 201, "Failed to create temporary team key")
        team_key_id = created.json()["id"]
        team_key = created.json()["key"]
        api_headers = {"Authorization": f"Bearer {team_key}"}

        try:
            models = client.get("/v1/models", headers=api_headers)
            require(models.status_code == 200, "/v1/models failed")
            model_ids = [item["id"] for item in models.json()["data"]]
            require("deepseek-chat" in model_ids, "deepseek-chat is not visible")

            non_stream = client.post(
                "/v1/chat/completions",
                headers=api_headers,
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly: gateway-ok",
                        }
                    ],
                    "stream": False,
                    "max_tokens": 32,
                },
            )
            require(
                non_stream.status_code == 200,
                f"Non-stream request failed: {non_stream.status_code}",
            )
            non_usage = non_stream.json().get("usage") or {}
            non_request_id = non_stream.headers.get("x-request-id")
            require(bool(non_request_id), "Non-stream response has no request id")
            require(non_usage.get("total_tokens", 0) > 0, "Non-stream usage missing")

            stream_usage: dict[str, Any] = {}
            stream_done = False
            stream_request_id = ""
            with client.stream(
                "POST",
                "/v1/chat/completions",
                headers=api_headers,
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly: stream-ok",
                        }
                    ],
                    "stream": True,
                    "max_tokens": 32,
                },
            ) as stream:
                require(stream.status_code == 200, "SSE request failed")
                stream_request_id = stream.headers.get("x-request-id", "")
                for line in stream.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        stream_done = True
                        continue
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        stream_usage = chunk["usage"]
            require(stream_done, "SSE stream did not finish with [DONE]")
            require(stream_usage.get("total_tokens", 0) > 0, "SSE usage missing")

            failed = client.post(
                "/v1/chat/completions",
                headers=api_headers,
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "invalid request test"}],
                    "max_tokens": -1,
                },
            )
            require(failed.status_code >= 400, "Expected upstream validation failure")
            failed_request_id = failed.headers.get("x-request-id")
            require(bool(failed_request_id), "Failed response has no request id")

            def get_log(request_id: str) -> dict[str, Any]:
                response = client.get(
                    "/api/admin/usage-logs",
                    headers=web_headers,
                    params={"request_id": request_id},
                )
                require(response.status_code == 200, "Usage log query failed")
                items = response.json()["items"]
                require(len(items) == 1, f"Usage log not found for {request_id}")
                return items[0]

            non_log = get_log(non_request_id)
            stream_log = get_log(stream_request_id)
            failed_log = get_log(failed_request_id)
            require(usage_matches(non_log, non_usage), "Non-stream usage mismatch")
            require(usage_matches(stream_log, stream_usage), "SSE usage mismatch")
            require(failed_log["status"] == "failed", "Failure log status mismatch")

            stats = client.get("/api/admin/stats", headers=web_headers)
            require(stats.status_code == 200, "Admin stats query failed")
            expected_tokens = non_usage["total_tokens"] + stream_usage["total_tokens"]
            deepseek_tokens = sum(
                item["tokens"]
                for item in stats.json()["by_model"]
                if item["model"] == "deepseek-chat"
            )
            require(
                deepseek_tokens >= expected_tokens,
                "Admin token aggregation is lower than live usage",
            )

            print(
                json.dumps(
                    {
                        "models": model_ids,
                        "non_stream": {
                            "status": non_stream.status_code,
                            "usage": non_usage,
                            "log_status": non_log["status"],
                        },
                        "stream": {
                            "status": 200,
                            "done": stream_done,
                            "usage": stream_usage,
                            "log_status": stream_log["status"],
                        },
                        "failure": {
                            "status": failed.status_code,
                            "log_status": failed_log["status"],
                        },
                        "admin_stats_deepseek_tokens": deepseek_tokens,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        finally:
            if team_key_id is not None:
                client.delete(
                    f"/api/me/api-keys/{team_key_id}",
                    headers=web_headers,
                )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Live smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

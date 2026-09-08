import httpx


async def close_provider_connection(
    client: httpx.AsyncClient, response: httpx.Response | None = None
) -> None:
    """Close both resources even if closing the response itself fails."""
    try:
        if response is not None:
            await response.aclose()
    finally:
        await client.aclose()

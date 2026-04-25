import asyncio

from prefect import flow

from proxy_core import handle_proxy_request


@flow(name="awc-api-proxy-prefect")
def proxy_request_flow(method: str = "GET", path: str = "/healthz") -> dict:
    return asyncio.run(handle_proxy_request(method=method, path=path))


if __name__ == "__main__":
    print(proxy_request_flow())

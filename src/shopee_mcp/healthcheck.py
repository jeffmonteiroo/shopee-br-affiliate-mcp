"""Container health check with the public Host expected by the OAuth gateway."""
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    origin = os.environ["MCP_PUBLIC_URL"]
    request = Request("http://127.0.0.1:8765/health",
        headers={"Host": urlsplit(origin).netloc})
    with urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

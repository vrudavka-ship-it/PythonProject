# Comparison of Python Requests and HTTPX for CLI Research Tool

In the realm of Python development, making HTTP requests is a frequent task that requires efficient and reliable libraries. Two prominent libraries, **Requests** and **HTTPX**, have been widely adopted by developers for this purpose. This report provides a comprehensive comparison between Requests and HTTPX, considering various aspects such as asynchronous support, HTTP/2 compatibility, connection management, error handling, and performance metrics.

## Overview
### Requests
- **Established Library**: Requests is a well-known library celebrated for its simplicity and ease of use. It is often the go-to choice for developers who need to make straightforward, synchronous HTTP requests.
- **Limitations**: Lacks native support for asynchronous operations and HTTP/2, which can be a limitation for high-concurrency applications.

### HTTPX
- **Modern Alternative**: HTTPX is a newer library that offers advanced features such as asynchronous support and HTTP/2, making it a more powerful tool for performance-critical applications.
- **Dual Mode**: Supports both synchronous and asynchronous requests, allowing for greater flexibility in application design.

## Key Features Comparison
| Feature                     | Requests                       | HTTPX                          |
|-----------------------------|-------------------------------|--------------------------------|
| **Asynchronous Support**     | No                            | Yes (async/await)             |
| **HTTP/2 Support**          | No                            | Yes (http2=True)              |
| **Connection Pooling**      | Yes (Session)                 | Yes (Client/AsyncClient)      |
| **Streaming Uploads/Downloads** | Yes (iter_content())         | Yes (stream()/iter_bytes())   |
| **Error Handling**          | Basic (RequestException)      | Detailed (RequestError, HTTPStatusError) |
| **API Design**              | Simple and user-friendly       | More flexible and powerful     |

## Asynchronous Requests
One of the most significant differences between Requests and HTTPX is the support for asynchronous requests. HTTPX natively supports asynchronous operations, allowing developers to perform multiple HTTP requests concurrently without blocking the main thread. This feature is particularly beneficial for applications that require high concurrency, such as web scraping or interacting with multiple APIs simultaneously.

### Example of Asynchronous Request with HTTPX:
```python
import httpx
import asyncio

async def fetch(url):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text

async def main():
    urls = ['https://example.com', 'https://httpbin.org/get']
    tasks = [fetch(url) for url in urls]
    results = await asyncio.gather(*tasks)
    for result in results:
        print(result)

asyncio.run(main())
```

## HTTP/2 Support
HTTPX offers built-in support for HTTP/2, which is a more modern and efficient version of the HTTP protocol. HTTP/2 provides several advantages over HTTP/1.1, including multiplexing, header compression, and server push, which can significantly improve the performance of web applications. Requests, on the other hand, only supports HTTP/1.1 out of the box.

### Example of HTTP/2 Request with HTTPX:
```python
import httpx

async def fetch_http2(url):
    async with httpx.AsyncClient(http2=True) as client:
        response = await client.get(url)
        return response.text

asyncio.run(fetch_http2('https://http2.pro'))
```

## Connection Pooling and Keep-Alive
Both Requests and HTTPX support connection pooling and keep-alive, which are essential for maintaining persistent connections and improving the performance of HTTP requests. However, HTTPX has a more advanced connection management system that can handle multiple connections simultaneously more efficiently.

### Example of Connection Pooling:
```python
import requests

with requests.Session() as session:
    response = session.get('https://example.com')
    print(response.text)
```

```python
import httpx

with httpx.Client() as client:
    response = client.get('https://example.com')
    print(response.text)
```

## Performance
Performance is a critical factor when choosing an HTTP client library. HTTPX generally outperforms Requests in scenarios that involve high concurrency or multiple simultaneous requests due to its support for asynchronous requests and HTTP/2.

### Benchmarking Example:
```python
import time
import requests
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor

URL = "https://httpbin.org/get"
N = 50
MAX_WORKERS = 10

def run_requests_total():
    def fetch(session, url):
        r = session.get(url, timeout=10)
        return r.status_code
    start = time.perf_counter()
    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(fetch, session, URL) for _ in range(N)]
            for f in futures:
                f.result()
    elapsed = time.perf_counter() - start
    print(f"Requests (threadpool) {N} requests in {elapsed:.2f}s")

async def run_httpx_async():
    async def fetch(client, url):
        r = await client.get(url)
        return r.status_code
    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [fetch(client, URL) for _ in range(N)]
        await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    print(f"HTTPX async {N} requests in {elapsed:.2f}s")

if __name__ == "__main__":
    run_requests_total()
    asyncio.run(run_httpx_async())
```

## Conclusion
- **Use Requests** for simple, synchronous applications, small scripts, and when ease of use is a priority.
- **Use HTTPX** for applications that require asynchronous capabilities, HTTP/2 support, or higher concurrency. It is particularly suited for modern applications that need to handle multiple requests efficiently.

Both libraries have their strengths, and the choice between them should be based on the specific requirements of your CLI research tool.
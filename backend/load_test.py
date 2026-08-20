import asyncio
import aiohttp
import time

async def fetch(session, url, request_id):
    start = time.time()
    try:
        async with session.get(url) as response:
            data = await response.json()
            elapsed = time.time() - start
            print(f"Request {request_id} finished in {elapsed:.2f}s | Result: {data}")
            return elapsed
    except Exception as e:
        print(f"Request {request_id} failed: {e}")
        return None

async def main():
    url = "http://127.0.0.1:8000/test-duckdb"
    print("Starting 5 concurrent requests to the DuckDB ThreadPool wrapper...")
    overall_start = time.time()
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, url, i+1) for i in range(5)]
        results = await asyncio.gather(*tasks)
        
    overall_elapsed = time.time() - overall_start
    print(f"\n--- LOAD TEST COMPLETE ---")
    print(f"Total time for 5 requests (each sleeping 2s internally): {overall_elapsed:.2f}s")
    
    # If requests were blocked sequentially, total time would be ~10s.
    # If concurrent and non-blocking, total time should be ~2-3s.
    if overall_elapsed < 5.0:
        print("SUCCESS: Requests executed concurrently without blocking the event loop!")
    else:
        print("FAIL: Requests appear to have blocked sequentially.")

if __name__ == "__main__":
    asyncio.run(main())

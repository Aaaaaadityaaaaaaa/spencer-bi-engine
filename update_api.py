import sys
import re

with open('frontend/src/services/api.ts', 'r', encoding='utf-8') as f:
    content = f.read()

execute_sql_replacement = """// POST /sessions/{id}/execute -- submit SQL to the async query worker
export async function executeSql(
  sessionUuid: string,
  sql: string,
): Promise<{ query_id: string; status: string }> {
  const { data } = await http.post<{ query_id: string; status: string }>(
    `/sessions/${sessionUuid}/execute`,
    { sql },
  )
  return data
}

// Websocket wrapper for running a query
export function streamQueryProgress(
  sessionUuid: string,
  queryId: string,
  onProgress: (elapsedMs: number) => void,
): Promise<ExecuteResultResponse> {
  return new Promise((resolve, reject) => {
    // Determine ws:// or wss:// from current location (or import.meta.env)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = import.meta.env.VITE_API_URL 
      ? new URL(import.meta.env.VITE_API_URL).host 
      : window.location.host;
    
    // Support the local proxy in dev or direct connection
    const wsUrl = `${protocol}//${host}/api/sessions/${sessionUuid}/queries/${queryId}/ws`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.status === 'running') {
          onProgress(msg.elapsed_ms || 0);
        } else if (msg.status === 'completed') {
          ws.close();
          resolve(msg.result);
        } else if (msg.status === 'error') {
          ws.close();
          reject(new Error(msg.message));
        }
      } catch (e) {
        console.error("Failed to parse websocket message", e);
      }
    };

    ws.onerror = (e) => {
      console.error("Websocket error", e);
      reject(new Error("WebSocket connection failed"));
    };
  });
}

export async function cancelQuery(sessionUuid: string, queryId: string): Promise<void> {
  await http.post(`/sessions/${sessionUuid}/queries/${queryId}/cancel`);
}
"""

# Replace executeSql signature
content = re.sub(r'export async function executeSql\(.*?return data\n}', execute_sql_replacement, content, flags=re.DOTALL)

with open('frontend/src/services/api.ts', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated api.ts")

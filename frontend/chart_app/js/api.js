// Small fetch helpers for the /api/chart routes.

async function request(method, path, params, body) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  }
  const resp = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return resp.status === 204 ? null : resp.json();
}

export const api = {
  get: (path, params) => request('GET', path, params),
  post: (path, body, params) => request('POST', path, params, body),
  put: (path, body, params) => request('PUT', path, params, body),
  del: (path, params) => request('DELETE', path, params),
};

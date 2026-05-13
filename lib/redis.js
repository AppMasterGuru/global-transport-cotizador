/**
 * redis.js
 * Thin wrapper around the Upstash Redis REST API.
 *
 * Upstash gives us a free persistent key-value store that works on Vercel's
 * serverless functions — unlike the local filesystem which is read-only in prod.
 *
 * Required env vars (add to Vercel → Settings → Environment Variables):
 *   UPSTASH_REDIS_REST_URL    — from Upstash dashboard → REST API → Endpoint
 *   UPSTASH_REDIS_REST_TOKEN  — from Upstash dashboard → REST API → Read/Write Token
 *
 * If these env vars are absent (local dev without Redis), all writes are
 * silently skipped and reads return null. The app stays functional but
 * state won't persist across reloads.
 *
 * Keys used by this app:
 *   gt:state   — task checkbox state  { [taskId]: boolean }
 *   gt:log     — agent activity log   [{ timestamp, source, ... }, ...]
 */

const REDIS_URL   = process.env.UPSTASH_REDIS_REST_URL;
const REDIS_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN;

/** True when Upstash credentials are configured. */
export const hasRedis = !!(REDIS_URL && REDIS_TOKEN);

/**
 * Execute a Redis command array against Upstash REST API.
 * e.g. redisCmd(['SET', 'mykey', 'myvalue'])
 *      redisCmd(['GET', 'mykey'])
 * Returns the result field from the Upstash response.
 */
async function redisCmd(cmd) {
  if (!hasRedis) return null;
  const res = await fetch(REDIS_URL, {
    method:  'POST',
    headers: {
      Authorization:  `Bearer ${REDIS_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(cmd),
  });
  if (!res.ok) {
    console.error(`[Redis] Command failed: ${res.status} ${await res.text()}`);
    return null;
  }
  const data = await res.json();
  return data.result ?? null;
}

/**
 * Get a JSON value stored at key.
 * Returns parsed object, or null if key does not exist.
 */
export async function redisGet(key) {
  const raw = await redisCmd(['GET', key]);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

/**
 * Set a JSON value at key.
 * Value will be JSON-stringified before storage.
 */
export async function redisSet(key, value) {
  await redisCmd(['SET', key, JSON.stringify(value)]);
}

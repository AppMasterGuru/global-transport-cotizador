/**
 * agent-push.js
 * POST /api/agent-push
 *
 * Receives email summaries and task updates pushed by the local TimeBack AI
 * agent (gmail_monitor.py) whenever a GT/SINTAD email arrives.
 *
 * Request body (JSON):
 *   {
 *     "source":       "email | historical_sweep | manual",
 *     "from_email":   "sender address that triggered this update",
 *     "subject":      "email subject",
 *     "summary":      "Claude's summary of what this email means for the project",
 *     "task_updates": [{ "id": "c2", "done": true }, ...],
 *     "notes":        ["Jean Paul confirmed proposal reviewed", ...]
 *   }
 *
 * Security: set AGENT_SECRET env var (Vercel + local .env).
 * Agent must send the same value in the Authorization header:
 *   Authorization: Bearer <AGENT_SECRET>
 * Requests with a missing or wrong secret are rejected with 403.
 * If AGENT_SECRET is unset, all pushes are accepted (local dev mode).
 *
 * Storage: Upstash Redis keys gt:state and gt:log.
 * See lib/redis.js for setup instructions.
 */

import { redisGet, redisSet, hasRedis } from '../../lib/redis';
import { SECTIONS } from '../../data/tasks';

const MAX_LOG_ENTRIES = 50;

function defaultState() {
  const state = {};
  SECTIONS.forEach(s => s.tasks.forEach(t => { state[t.id] = t.done; }));
  return state;
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Secret check — prefer Authorization header, fall back to body field
  const agentSecret = process.env.AGENT_SECRET;
  if (agentSecret) {
    const authHeader = req.headers['authorization'] || '';
    const bodySecret  = req.body?.secret || '';
    const headerToken = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : authHeader;
    if (headerToken !== agentSecret && bodySecret !== agentSecret) {
      return res.status(403).json({ error: 'Invalid secret' });
    }
  }

  const { source, from_email, subject, summary, task_updates, notes } = req.body || {};

  // 1. Apply task state updates to Redis
  const state = (await redisGet('gt:state')) || defaultState();
  const applied = [];
  for (const update of (task_updates || [])) {
    if (update.id && typeof update.done === 'boolean') {
      state[update.id] = update.done;
      applied.push(update);
    }
  }
  // Always write state back so it's initialised in Redis on first push
  await redisSet('gt:state', state);

  // 2. Append to activity log in Redis
  const log = (await redisGet('gt:log')) || [];
  log.unshift({
    timestamp:    new Date().toISOString(),
    source:       source || 'unknown',
    from_email:   from_email || null,
    subject:      subject || null,
    summary:      summary || null,
    notes:        notes || [],
    task_updates: applied,
  });
  await redisSet('gt:log', log.slice(0, MAX_LOG_ENTRIES));

  if (!hasRedis) {
    console.warn('[agent-push] No Redis configured — state not persisted. Set UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN.');
  }

  return res.status(200).json({ ok: true, applied_count: applied.length, redis: hasRedis });
}

/**
 * tasks.js
 * GET  /api/tasks  — returns current task state
 * POST /api/tasks  — toggles a single task { id, done }
 *
 * State is stored in Redis (gt:state key) so it persists on Vercel.
 * Falls back to static task defaults if Redis is not configured.
 */

import { redisGet, redisSet } from '../../lib/redis';
import { SECTIONS } from '../../data/tasks';

function defaultState() {
  const state = {};
  SECTIONS.forEach(s => s.tasks.forEach(t => { state[t.id] = t.done; }));
  return state;
}

export default async function handler(req, res) {
  if (req.method === 'GET') {
    const state = (await redisGet('gt:state')) || defaultState();
    return res.status(200).json({ state });
  }

  if (req.method === 'POST') {
    const { id, done } = req.body;
    if (!id || typeof done !== 'boolean') {
      return res.status(400).json({ error: 'Missing id or done' });
    }
    const state = (await redisGet('gt:state')) || defaultState();
    state[id] = done;
    await redisSet('gt:state', state);
    return res.status(200).json({ ok: true, state });
  }

  res.status(405).json({ error: 'Method not allowed' });
}

/**
 * tasks.js
 * GET  /api/tasks  — returns current task state
 * POST /api/tasks  — toggles a single task { id, done }
 *
 * State is stored in Redis (gt:state key) so it persists across Vercel
 * redeploys. Falls back to static task defaults if Redis is not configured.
 *
 * First-load seeding: if Redis is empty on GET, the current done states
 * from data/tasks.js are written to Redis immediately, so the state is
 * locked in and survives all subsequent redeploys without resetting.
 */

import { redisGet, redisSet, hasRedis } from '../../lib/redis';
import { SECTIONS } from '../../data/tasks';

function defaultState() {
  const state = {};
  SECTIONS.forEach(s => s.tasks.forEach(t => { state[t.id] = t.done; }));
  return state;
}

export default async function handler(req, res) {
  if (req.method === 'GET') {
    let state = await redisGet('gt:state');

    if (!state) {
      // Redis is empty (first load after connecting, or after a manual flush).
      // Seed from data/tasks.js and write to Redis immediately so this only
      // happens once — subsequent redeploys won't reset anything.
      state = defaultState();
      if (hasRedis) {
        await redisSet('gt:state', state);
        console.log('[tasks] Seeded Redis with defaultState from data/tasks.js');
      }
    }

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

/**
 * agent-log.js
 * GET /api/agent-log
 *
 * Returns the agent activity log stored in Redis (gt:log key).
 * Polled every 30 seconds by the dashboard front-end.
 */

import { redisGet } from '../../lib/redis';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }
  try {
    const log = (await redisGet('gt:log')) || [];
    return res.status(200).json({ log });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

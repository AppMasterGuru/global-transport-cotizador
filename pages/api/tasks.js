import fs from 'fs';
import path from 'path';
import { SECTIONS } from '../../data/tasks';

const STATE_FILE = path.join(process.cwd(), 'data', 'state.json');

function loadState() {
  try {
    if (fs.existsSync(STATE_FILE)) {
      return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    }
  } catch {}
  // Build default state from task definitions
  const state = {};
  SECTIONS.forEach(s => s.tasks.forEach(t => { state[t.id] = t.done; }));
  return state;
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

export default function handler(req, res) {
  if (req.method === 'GET') {
    const state = loadState();
    return res.status(200).json({ state });
  }

  if (req.method === 'POST') {
    const { id, done } = req.body;
    if (!id || typeof done !== 'boolean') {
      return res.status(400).json({ error: 'Missing id or done' });
    }
    const state = loadState();
    state[id] = done;
    saveState(state);
    return res.status(200).json({ ok: true, state });
  }

  res.status(405).json({ error: 'Method not allowed' });
}

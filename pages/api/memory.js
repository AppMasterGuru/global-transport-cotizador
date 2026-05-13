import fs from 'fs';
import path from 'path';
import { parseMemory } from '../../lib/parseMemory';

// Path to the client's MEMORY.md
// Change this constant to point at a different client folder
const MEMORY_PATH = path.join(
  process.env.HOME || '/Users/barnwellelliott',
  'Documents',
  'CLAUDE CODE',
  'GLOBAL TRANSPORT',
  'MEMORY.md'
);

export default function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    if (!fs.existsSync(MEMORY_PATH)) {
      return res.status(404).json({
        error: `MEMORY.md not found at: ${MEMORY_PATH}`,
        hint: 'Check that the path exists and that the dev server has file system access.',
      });
    }

    const raw = fs.readFileSync(MEMORY_PATH, 'utf8');
    const sections = parseMemory(raw);
    const lastModified = fs.statSync(MEMORY_PATH).mtime.toISOString();

    return res.status(200).json({ sections, lastModified, path: MEMORY_PATH });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

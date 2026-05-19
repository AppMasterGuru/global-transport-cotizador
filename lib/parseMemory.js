/**
 * parseMemory.js — TimeBack AI
 *
 * Reads MEMORY.md from a client project folder and converts it into
 * the same SECTIONS shape that data/tasks.js uses, so the existing
 * dashboard UI can render it without any changes to its rendering logic.
 *
 * MEMORY.md task detection rules:
 *   - [x] Task name          → done: true
 *   - [ ] Task name          → done: false
 *   - Tags detected from line content:
 *       BLOCKED / blocked    → tags: ['blocked']
 *       READY / ready        → tags: ['ready']
 *       NEEDS CLIENT         → tags: ['client']
 *   - Sections come from ## headings
 *   - ### headings also work as sections
 *   - Lines without [ ] or [x] are skipped unless they're headings
 */

export function parseMemory(raw) {
  const lines = raw.split('\n');
  const sections = [];
  let currentSection = null;
  let taskCounter = 0;

  for (const line of lines) {
    // ## or ### heading → new section
    const headingMatch = line.match(/^#{2,3}\s+(.+)/);
    if (headingMatch) {
      const title = headingMatch[1]
        .replace(/[🔧📋📊💬🏗️🚀⚙️✅🔴🟢⚠️]/g, '')
        .trim();
      currentSection = {
        id: `mem-${sections.length}`,
        title,
        tasks: [],
      };
      sections.push(currentSection);
      continue;
    }

    // Skip lines that aren't task lines
    const taskMatch = line.match(/^\s*[-*]\s*\[([ xX])\]\s*(.+)/);
    if (!taskMatch) continue;

    // If no section yet, create a default one
    if (!currentSection) {
      currentSection = { id: 'mem-general', title: 'General', tasks: [] };
      sections.push(currentSection);
    }

    const isDone = taskMatch[1].toLowerCase() === 'x';
    const rawName = taskMatch[2].trim();
    taskCounter++;

    // Detect colour tags — [ADDED] = orange (scope addition), [EXTRA] = green (bonus)
    let colorTag = null;
    if (/\[ADDED\]/i.test(rawName)) colorTag = 'added';
    else if (/\[EXTRA\]/i.test(rawName)) colorTag = 'extra';

    // Detect status tags from line content
    const tags = [];
    const lower = rawName.toLowerCase();
    if (lower.includes('blocked')) tags.push('blocked');
    if (lower.includes('ready')) tags.push('ready');
    if (lower.includes('needs client') || lower.includes('client')) tags.push('client');

    // Strip [ADDED]/[EXTRA] and status suffixes from display name
    const name = rawName
      .replace(/\s*\[(ADDED|EXTRA)\]/gi, '')
      .replace(/\s*[-—–]\s*(BLOCKED|READY|DONE|IN PROGRESS|NEEDS CLIENT|COMPLETE|WIP|TODO)[^$]*/gi, '')
      .replace(/\s*\(BLOCKED\)|\(READY\)|\(DONE\)/gi, '')
      .trim();

    // Extract note (text after — or : following a status keyword)
    let sub = null;
    const noteMatch = rawName.match(/[-—–:]\s*(?:BLOCKED(?:\s+on)?|NEEDS CLIENT|WAITING FOR)[:\s]+(.+)/i);
    if (noteMatch) sub = noteMatch[1].trim();

    currentSection.tasks.push({
      id: `mem-task-${taskCounter}`,
      done: isDone,
      name: name || rawName,
      sub: sub || null,
      tags,
      colorTag,    // 'added' | 'extra' | null
      why: null,   // MEMORY.md tasks don't have why/how — detail panel won't render them
      how: [],
    });
  }

  // Remove empty sections
  return sections.filter(s => s.tasks.length > 0);
}

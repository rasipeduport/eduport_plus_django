/**
 * For a page made of several reads that each fail on their own (the staff and
 * tutor dashboards): a failed read keeps what that part last showed, and one
 * message names every part that failed -- those still showing what was loaded
 * before, and those that never loaded.
 */

/** "students", "students and sessions", "students, sessions and homework". */
export function listOf(names) {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}

/**
 * The message for the parts whose read failed (`failed`: their labels), told
 * apart by whether each had loaded before (`loaded`: a Set of labels). Empty
 * when nothing failed.
 */
export function partsFailedMessage(failed, loaded) {
  const kept = failed.filter((name) => loaded.has(name));
  const missing = failed.filter((name) => !loaded.has(name));
  return [
    missing.length ? `Could not load ${listOf(missing)}.` : '',
    kept.length ? `Could not refresh ${listOf(kept)}; showing what was loaded before.` : '',
  ]
    .filter(Boolean)
    .join(' ');
}

/**
 * The next value of each part: its fresh answer where its read succeeded,
 * otherwise what it showed before (`previous`), or its `empty` value when it
 * has never loaded. `fresh[name]` is undefined for a failed read.
 */
export function keepFailed(fresh, previous, empty) {
  const next = {};
  for (const name of Object.keys(empty)) {
    next[name] = fresh[name] !== undefined ? fresh[name] : (previous?.[name] ?? empty[name]);
  }
  return next;
}

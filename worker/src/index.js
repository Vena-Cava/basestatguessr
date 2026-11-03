/*
 * BaseStatGuessr ranked-run server (Cloudflare Worker + D1).
 *
 * The server owns every ranked Infinite run: it picks each Pokémon, checks each
 * guess, counts lives and keeps the score. The browser only ever sends guesses,
 * so a score can't be made up and posted to the leaderboard.
 *
 * Endpoints (all JSON):
 *   POST /run/start   {mode}                       -> {runId, state, round}
 *   POST /run/guess   {runId, no, stats:[6]}            (Build the Spread)
 *                     {runId, no, guess:id | giveUp:true} (Whose Spread?)   no = round number from the server
 *                                                  -> {result, state, reveal?, clues?, next?}
 *   POST /run/end     {runId}                       -> {state}          (quit early; score counts)
 *   POST /run/submit  {runId, name}                 -> {rank, entry}
 *   GET  /leaderboard?mode=spread|who               -> {entries:[...]}
 */
import DATA from './data.js';

const MODES = ['spread', 'who'];
const WHO_POINTS = [100, 75, 50, 25];
const LIVES = 3;
const RUN_TTL_MS = 6 * 60 * 60 * 1000; // a run left untouched for 6 hours can no longer be played

// ----- data -----
const MONS = DATA.mons.map(([id, n, s, g, t, st, form]) => ({ id, n, s, g, t, st, form, key: st.join(',') }));
const BY_ID = new Map(MONS.map(m => [m.id, m]));
const sum = a => a.reduce((x, y) => x + y, 0);

// Deterministic shuffle so a run only needs to store a seed and a position.
function mulberry32(a) {
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function monAt(seed, idx) {
  const cycle = Math.floor(idx / MONS.length), pos = idx % MONS.length;
  const rnd = mulberry32(seed + cycle * 7919);
  const order = MONS.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
  return MONS[order[pos]];
}

// What the player may see at the start of a round (never the answer).
function roundView(mode, m, no, misses = 0) {
  if (mode === 'spread') return { no, id: m.id, n: m.n, t: m.t, bst: sum(m.st) };
  return { no, st: m.st, bst: sum(m.st), clues: clues(m, misses) };
}
function clues(m, misses) {
  const c = {};
  if (misses >= 1) c.g = m.g;
  if (misses >= 2) c.t = m.t;
  if (misses >= 3) c.blur = DATA.blur[m.id] || null;
  return c;
}
const reveal = m => ({ id: m.id, n: m.n, s: m.s, t: m.t, g: m.g, st: m.st });
const publicState = r => ({ lives: r.lives, score: r.score, rounds: r.rounds, perfect: r.perfect, over: r.status !== 'active', submitted: !!r.submitted });

// ----- http helpers -----
function cors(env, req) {
  const allowed = (env.ALLOWED_ORIGINS || '*').split(',').map(s => s.trim());
  const origin = req.headers.get('Origin') || '';
  const allow = allowed.includes('*') ? '*' : allowed.includes(origin) ? origin : allowed[0];
  return { 'Access-Control-Allow-Origin': allow, 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Vary': 'Origin' };
}
const json = (data, status, h) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...h } });
class HttpError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
const bad = msg => { throw new HttpError(400, msg); };

async function loadRun(env, runId) {
  if (typeof runId !== 'string' || !/^[a-f0-9]{32}$/.test(runId)) bad('Bad run id');
  const r = await env.DB.prepare('SELECT * FROM runs WHERE id = ?').bind(runId).first();
  if (!r) throw new HttpError(404, 'Run not found');
  return r;
}
function assertPlayable(r) {
  if (r.status !== 'active') throw new HttpError(409, 'This run is over');
  if (Date.now() - r.updated > RUN_TTL_MS) throw new HttpError(409, 'This run has expired');
}
// Save only if nobody else changed the run since we read it (stops double-submitted guesses counting twice).
async function saveRun(env, before, after) {
  const res = await env.DB.prepare(
    `UPDATE runs SET idx=?, misses=?, lives=?, score=?, rounds=?, perfect=?, status=?, updated=?
     WHERE id=? AND idx=? AND misses=? AND status='active'`
  ).bind(after.idx, after.misses, after.lives, after.score, after.rounds, after.perfect, after.status, Date.now(),
         before.id, before.idx, before.misses).run();
  if (!res.meta || res.meta.changes !== 1) throw new HttpError(409, 'That guess was already counted');
}

// ----- handlers -----
async function start(env, body) {
  const mode = body.mode;
  if (!MODES.includes(mode)) bad('Unknown mode');
  const id = [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
  const seed = crypto.getRandomValues(new Uint32Array(1))[0];
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO runs (id, mode, seed, idx, misses, lives, score, rounds, perfect, status, created, updated, submitted)
     VALUES (?, ?, ?, 0, 0, ?, 0, 0, 0, 'active', ?, ?, 0)`
  ).bind(id, mode, seed, LIVES, now, now).run();
  const r = { id, mode, seed, idx: 0, misses: 0, lives: LIVES, score: 0, rounds: 0, perfect: 0, status: 'active' };
  return { runId: id, state: publicState(r), round: roundView(mode, monAt(seed, 0), 0) };
}

async function guess(env, body) {
  const r = await loadRun(env, body.runId);
  assertPlayable(r);
  if (body.no !== undefined && body.no !== r.idx) throw new HttpError(409, 'That guess was for an earlier round');
  const m = monAt(r.seed, r.idx);
  const after = { ...r };
  let pts = null, extra = {};

  if (r.mode === 'spread') {
    const g = body.stats;
    if (!Array.isArray(g) || g.length !== 6 || !g.every(v => Number.isInteger(v) && v >= 1 && v <= 255)) bad('Stats must be six whole numbers from 1 to 255');
    if (sum(g) !== sum(m.st)) bad('Stats must add up to the BST');
    pts = Math.max(0, 100 - sum(g.map((v, i) => Math.abs(v - m.st[i]))));
  } else {
    if (body.giveUp === true) { pts = 0; extra.gaveUp = true; }
    else {
      const x = BY_ID.get(body.guess);
      if (!x) bad('Unknown Pokémon');
      if (x.key === m.key) pts = WHO_POINTS[r.misses];
      else {
        after.misses = r.misses + 1;
        extra.near = x.s === m.s;
        if (after.misses >= WHO_POINTS.length) pts = 0;
      }
    }
  }

  if (pts === null) { // a wrong guess with guesses left: same round, one more clue
    await saveRun(env, r, after);
    return { result: 'miss', near: extra.near, misses: after.misses, worth: WHO_POINTS[after.misses], clues: clues(m, after.misses), state: publicState(after) };
  }

  // round finished
  after.score = r.score + pts;
  after.rounds = r.rounds + 1;
  after.perfect = r.perfect + (pts === 100 ? 1 : 0);
  if (pts === 0) after.lives = r.lives - 1;
  after.idx = r.idx + 1;
  after.misses = 0;
  if (after.lives <= 0) after.status = 'over';
  await saveRun(env, r, after);
  const out = { result: 'round', pts, misses: r.misses, near: extra.near, gaveUp: extra.gaveUp, reveal: reveal(m), state: publicState(after) };
  if (after.status === 'active') out.next = roundView(r.mode, monAt(r.seed, after.idx), after.idx);
  return out;
}

async function end(env, body) {
  const r = await loadRun(env, body.runId);
  if (r.status === 'active') {
    await env.DB.prepare(`UPDATE runs SET status='over', updated=? WHERE id=? AND status='active'`).bind(Date.now(), r.id).run();
    r.status = 'over';
  }
  return { state: publicState(r) };
}

async function submit(env, body) {
  const r = await loadRun(env, body.runId);
  if (r.status === 'active') { // ending a run by submitting it, e.g. after it expired
    if (Date.now() - r.updated <= RUN_TTL_MS) bad('Finish the run first');
  }
  let name = typeof body.name === 'string' ? body.name.normalize('NFC').replace(/[\u0000-\u001f\u007f<>]/g, '').trim().slice(0, 16) : '';
  if (!name) bad('Enter a name');
  if (r.rounds === 0) bad('Play at least one round first');
  const claim = await env.DB.prepare(`UPDATE runs SET submitted=1, status='over' WHERE id=? AND submitted=0`).bind(r.id).run();
  if (!claim.meta || claim.meta.changes !== 1) throw new HttpError(409, 'This run is already on the leaderboard');
  const now = Date.now();
  await env.DB.prepare(`INSERT INTO scores (mode, name, score, rounds, perfect, created, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)`)
    .bind(r.mode, name, r.score, r.rounds, r.perfect, now, r.id).run();
  const better = await env.DB.prepare(`SELECT COUNT(*) AS n FROM scores WHERE mode=? AND (score > ? OR (score = ? AND created < ?))`)
    .bind(r.mode, r.score, r.score, now).first();
  return { rank: (better ? better.n : 0) + 1, entry: { name, score: r.score, rounds: r.rounds, perfect: r.perfect, date: now } };
}

async function leaderboard(env, url) {
  const mode = url.searchParams.get('mode');
  if (!MODES.includes(mode)) bad('Unknown mode');
  const { results } = await env.DB.prepare(
    `SELECT name, score, rounds, perfect, created AS date FROM scores WHERE mode=? ORDER BY score DESC, created ASC LIMIT 50`
  ).bind(mode).all();
  return { entries: results || [] };
}

export default {
  async fetch(req, env) {
    const h = cors(env, req);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: h });
    const url = new URL(req.url);
    try {
      if (req.method === 'GET' && url.pathname === '/leaderboard') return json(await leaderboard(env, url), 200, h);
      if (req.method === 'GET' && url.pathname === '/') return json({ ok: true, name: 'BaseStatGuessr API', pokemon: MONS.length }, 200, h);
      if (req.method !== 'POST') throw new HttpError(404, 'Not found');
      let body;
      try { body = await req.json(); } catch { bad('Body must be JSON'); }
      const routes = { '/run/start': start, '/run/guess': guess, '/run/end': end, '/run/submit': submit };
      const fn = routes[url.pathname];
      if (!fn) throw new HttpError(404, 'Not found');
      return json(await fn(env, body || {}), 200, h);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status, h);
      console.error(e);
      return json({ error: 'Server error' }, 500, h);
    }
  }
};

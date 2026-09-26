// Serves public/ as static assets; POST /api/contact forwards the form to a Discord webhook.
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.hostname.startsWith('www.')) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }
    if (url.pathname === '/api/contact') {
      return req.method === 'POST' ? contact(req, env) : new Response(null, { status: 405, headers: { allow: 'POST' } });
    }
    const res = await env.ASSETS.fetch(req);
    if (env.STAGING !== '1') return res;
    const tagged = new Response(res.body, res);
    tagged.headers.set('x-robots-tag', 'noindex, nofollow'); // staging must never be indexed
    return tagged;
  },
};

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const clean = (v, max) => String(v ?? '').trim().slice(0, max);
// both sets: production still sends the USD values, staging sends the Ringgit ones
const BUDGET = { unsure: 'Not sure yet', lt5k: 'Under $5k', '5-15k': '$5k – $15k', '15-50k': '$15k – $50k', '50k+': '$50k+',
                 'rm6-8': 'RM 6,000 – 8,000', 'rm8-12': 'RM 8,000 – 12,000', 'rm12+': 'RM 12,000 and up' };

async function contact(req, env) {
  let body;
  try { body = await req.json(); } catch { return json({ error: 'invalid json' }, 400); }

  if (clean(body._hp, 10)) return json({ ok: true }); // honeypot filled → bot; pretend success, drop it

  const name = clean(body.name, 100), email = clean(body.email, 200), company = clean(body.company, 100),
        need = clean(body.need, 4000), budget = BUDGET[body.budget] || 'Not sure yet';
  if (!name || !need || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return json({ error: 'missing fields' }, 400);

  if (!env.DISCORD_WEBHOOK_URL) {
    // staging has no webhook of its own: let the form show its success state without posting anywhere
    return env.STAGING === '1' ? json({ ok: true }) : json({ error: 'not configured' }, 500);
  }

  const ip = req.headers.get('cf-connecting-ip') || 'unknown';
  if (env.RATE_LIMITER) {
    const { success } = await env.RATE_LIMITER.limit({ key: ip });
    if (!success) return json({ error: 'too many requests' }, 429);
  }

  const res = await fetch(env.DISCORD_WEBHOOK_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      username: 'reranklab.com',
      embeds: [{
        title: `New enquiry — ${name}`,
        color: 0xff6b3d,
        fields: [
          { name: 'Email', value: email, inline: true },
          { name: 'Company', value: company || '—', inline: true },
          { name: 'Budget', value: budget, inline: true },
          { name: 'What they need', value: need.slice(0, 1024) },
        ],
        footer: { text: `${req.cf?.city || ''} ${req.cf?.country || ''} · ${ip}`.trim() },
        timestamp: new Date().toISOString(),
      }],
    }),
  });
  if (!res.ok) return json({ error: 'upstream' }, 502);
  return json({ ok: true });
}

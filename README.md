# reranklab.com

Marketing site for RerankLab. One static page served by a Cloudflare Worker, which also proxies the contact form to Discord.

```
public/          static site (index.html, logo/, og.png, robots.txt, sitemap.xml)
worker.js        serves public/, POST /api/contact → Discord webhook, www → apex redirect
wrangler.jsonc   Worker config: custom domains, rate limit, assets
```

## Deploy

Push to `main` — the GitHub Action runs `wrangler deploy`. It needs a `CLOUDFLARE_API_TOKEN` repo secret (Workers Scripts:Edit, Workers Assets:Edit, Zone:Read on reranklab.com).

Manual: `npx wrangler deploy`

Secrets (set once, not in the repo): `npx wrangler secret put DISCORD_WEBHOOK_URL`

## Local dev

```bash
npx wrangler dev
```

Put a test webhook in `.dev.vars` (`DISCORD_WEBHOOK_URL=...`); it is git-ignored.

## After publishing a new page

Add it to `public/sitemap.xml`, then ping IndexNow (key is in `.indexnow-key`, git-ignored):

```bash
curl "https://api.indexnow.org/indexnow?url=https://reranklab.com/<path>&key=$(cat .indexnow-key)"
```

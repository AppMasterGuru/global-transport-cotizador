# GT × TimeBack AI — Pipeline #1 Checklist

A persistent task dashboard for the Global Transport cotizador project.

## Deploy to Vercel (one time)

### Step 1 — Push to GitHub

```bash
cd gt-checklist
git init
git add .
git commit -m "Initial checklist dashboard"
```

Create a new repo on github.com (call it `gt-checklist`), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/gt-checklist.git
git branch -M main
git push -u origin main
```

### Step 2 — Deploy on Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Import your `gt-checklist` GitHub repo
3. Leave all settings as default — Vercel detects Next.js automatically
4. Click **Deploy**

That's it. Your dashboard will be live at `https://gt-checklist.vercel.app` (or similar).

### Updating task state

Check/uncheck tasks in the browser — state saves automatically via the `/api/tasks` endpoint and persists in `data/state.json` on the server.

> **Note:** Vercel's serverless functions have an ephemeral filesystem — state resets on redeploy. For permanent persistence, swap the file-based store in `pages/api/tasks.js` for a database (Vercel KV, PlanetScale, or Supabase are all free-tier options). Ask Claude to upgrade this when you're ready.

## Local development

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

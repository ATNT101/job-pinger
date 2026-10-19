# Job Pinger

Checks bank, boutique, pension and Big 4 career sites, LinkedIn and Simplify about every 5 minutes, all day and night. When a new posting turns up, it buzzes your phone and emails you.

- **Summer 2028 IB** (or "Class of 2029") → 🚨 top-priority ping, which gets through Do Not Disturb if you allow it
- **Summer 2027 finance / capital markets / M&A / assurance** → normal ping, ⭐ when it's a big name
- Regions: Canada, APAC, Europe (add `us` in `config.yaml` to cover New York too)

The very first run sends **one email listing every matching role that's already open**. Summer 2027 recruiting has already started, so read that email first.

---

## Setup (about 15 minutes)

### 1. Phone alerts (ntfy)
1. Install **ntfy** from the App Store and open it.
2. Tap **+**, then subscribe to this topic: `xiaobo-jobs-d39b974bc7`
   (Treat it like a password. Anyone who knows the topic name can read your alerts.)
3. In iPhone Settings → Notifications → ntfy, turn on **Time Sensitive** so 2028 IB pings get through Focus modes.

### 2. Gmail alerts
1. Turn on 2-Step Verification for your Google account if it isn't on already.
2. Go to <https://myaccount.google.com/apppasswords>, create an app password called "Job Pinger", and copy the 16-character code.

### 3. Put it on GitHub
1. Go to <https://github.com/new>, name the repo `job-pinger`, choose **Public**, and **don't** add a README. Click Create.
   Public is what keeps it free: private repos only get 2,000 Actions minutes a month, and running every 5 minutes uses about 9,000. Nothing secret is stored in the code. Your passwords go in step 4.
2. Open Terminal and run (swap in your GitHub username):
   ```bash
   cd ~/Documents/job-pinger
   git init && git add . && git commit -m "job pinger"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/job-pinger.git
   git push -u origin main
   ```

### 4. Add your secrets
In the repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Name | Value |
|---|---|
| `NTFY_TOPIC` | `xiaobo-jobs-d39b974bc7` |
| `GMAIL_ADDRESS` | xiaobozhang111@gmail.com |
| `GMAIL_APP_PASSWORD` | the 16-character app password |

### 5. Turn it on
1. Go to the **Actions** tab. If GitHub asks, click "I understand my workflows, go ahead and enable them".
2. Click **job-pinger → Run workflow** and type `test-alert`. Your phone and inbox should each get a fake "TEST" ping.
3. Run it again with `doctor`, open the run log, and you'll see a table of every source showing OK/FAIL and how many postings each one returned.
4. Run it once more with `normal`. That's the first live run, and it sends the "already open" email. After that it runs by itself every 5 minutes.

---

## Day-to-day

- **FOUND.md** in the repo keeps a running log of every posting it has flagged, newest first.
- Around 8am Toronto time you get one quiet "still watching" ping, so you know it's alive.
- If a source that used to work fails for about 30 minutes straight, you get a ⚠️ ping naming it.
- **Add a firm:** open its careers page. If the URL has `myworkdayjobs.com`, copy the line format under `workday:` in `config.yaml`. Use `greenhouse:` for `greenhouse.io` URLs. For any other server-rendered careers page, add it under `html:`.
- **Too noisy / too quiet:** the keyword rules sit at the top of `pinger.py` (`IB`, `FIN`, `EXCLUDE`).

## How fast is it really?
GitHub's 5-minute schedule usually fires 5 to 15 minutes apart, so a posting on a bank's own site typically reaches you within about 15 minutes. LinkedIn queries rotate, so a boutique posting that only shows up there can take 30 to 60 minutes. To get under 2 minutes you'd need an always-on server, and the same code runs there unchanged.

## Sources
- **Direct (fastest):** TD, CIBC, BMO, Barclays, Deutsche, Wells Fargo, Mizuho/Greenhill, PJT, Houlihan Lokey, Harris Williams, Guggenheim, Piper Sandler, Blackstone, Brookfield, CPP Investments, OMERS, OTPP, Manulife, Sun Life (Workday); Solomon, Rothesay (Greenhouse); J.P. Morgan (Oracle)
- **Career pages:** Citi, Scotiabank, National Bank, Rothschild, RBC, Macquarie
- **Broad net:** LinkedIn public job search (catches GS, MS, BofA, Evercore, Lazard, Moelis, Centerview, CICC, HSBC and small M&A boutiques) plus the Simplify internship list

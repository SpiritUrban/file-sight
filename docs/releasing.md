# Releasing FileSight

Two halves: the steps only the repository owner can do (GitHub settings and
secrets), and the steps the pipeline does. Nothing in the first half can be
automated, and skipping any of it makes the pipeline fail in ways that look
like something else.

---

## Part 1 — owner-only, one time

Do these **in this order**. The order is not cosmetic: the `github-pages`
environment does not exist until Pages has deployed at least once, so its
protection rule cannot be configured before the first successful deploy.

| # | What | Where | If skipped, the symptom is |
| --- | --- | --- | --- |
| 1 | Active payment method, non-zero spending limit | Settings → Billing and plans | A job dies in ~3 s with an empty step list: "The job was not started because recent account payments have failed". Ordinary CI may keep working — jobs with an `environment` are the ones that get blocked |
| 2 | Pages: Source = **GitHub Actions** | Settings → Pages | Site 404s; `/repos/.../pages` also 404s |
| 3 | Workflow permissions: Read and write | Settings → Actions → General | The release is never created |
| 4 | Secrets `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Settings → Secrets and variables → Actions → **Repository secrets** | Every build fails: "A public key has been found, but no private key" |
| 5 | Push to `main`, confirm CI green and Pages deployed | Actions | — |
| 6 | Environment `github-pages`: allow branch `main` **and tag** `v*.*.*` | Settings → Environments → github-pages → Deployment branches and tags | `Tag "v0.6.1" is not allowed to deploy to github-pages due to environment protection rules` — and you find out only *after* the tag is pushed |
| 7 | Tag the release | locally | — |

### Step 4 in detail

The keypair already exists in the repository root and is gitignored:

- `TAURI_SIGNING_PRIVATE_KEY` ← the **entire contents** of `.tauri-key`
  (not `.tauri-key.pub`, and not a fragment of it)
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` ← the password printed when the key
  was generated

They must be **Repository** secrets, not Environment secrets: the build job
has no `environment:`, so environment secrets are simply absent there and
arrive as empty strings.

> **A trailing newline in the secret breaks the build, and costs a whole
> run doing it.** GitHub stores exactly what was pasted. Tauri's decoder then
> reports `failed to decode base64 secret key: Invalid symbol 10, offset 348`
> — symbol 10 is the newline — and it does so *after* a successful four-minute
> compile, on every platform at once, which reads like a bundling problem. It
> cannot be reproduced locally, because `$(cat .tauri-key)` strips the newline
> in a shell.
>
> The `Prepare signing key` step in `release.yml` now strips trailing
> whitespace and verifies the key is a *secret* key (pasting `.tauri-key.pub`
> is the other way this fails) before anything is compiled. So a bad paste now
> fails in five seconds with a message that names the problem. Nothing needs
> to be re-pasted for this reason alone.

The matching public key is already in `tauri.conf.json`
(`plugins.updater.pubkey`) and was verified byte-for-byte against
`.tauri-key.pub`.

> **Losing the private key or its password is unrecoverable.** Updates can
> no longer be signed, and replacing the key means every installed copy stops
> accepting updates. Back both up somewhere that is not this repository.

### Step 6 has a trap that only surfaces after the tag

The `Add deployment branch or tag rule` dialog has a **Ref type** switch that
defaults to **Branch**. A `v*.*.*` pattern added as a *branch* rule looks for
a branch with that name, never matches a tag, and the deploy is rejected.

**The signal that it is right:** the list header reads
**"1 branch and 1 tag allowed"**. If it says "1 branch and **0 tags**
allowed", or `v*.*.*` shows "Currently applies to 0 branches", delete the
rule and re-add it with `Ref type: Tag`.

If a tag deploy is rejected anyway, **do not move the tag** — the release
itself is already published and fine. Fix the environment rule and use
`Actions → Release → <the tag's run> → Re-run failed jobs`. Only
`deploy-site` re-runs, the builds are not repeated, and `GITHUB_REF_NAME`
stays the tag, so the manifest still asks for the right release.

---

## Part 2 — cutting a release

```powershell
# 1. everything green locally
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path desktop/src-tauri/Cargo.toml
python -m pytest -q
cd desktop; npm run build; npm test; cd ..
node --test scripts/

# 2. bump the version in all eight files at once
node scripts/sync-version.mjs 0.7.0
node scripts/check-version.mjs

# 3. commit, push, and wait for a GREEN Rust job on the Linux runner.
#    This is the only real check for platform assumptions in the code:
#    "green on Windows" says nothing about it.
git commit -am "release: 0.7.0"
git push

# 4. dry run: Actions -> Release -> Run workflow.
#    Builds all four platforms and publishes nothing.

# 5. only then
git tag v0.7.0
git push origin v0.7.0
```

### What the dry run cannot tell you

`deploy-site` carries `if: startsWith(github.ref, 'refs/tags/')`, so a manual
run **skips** it — correctly, because there is nothing published to build a
manifest from and running it would overwrite the live manifest with an empty
one. The consequence: a green dry run means "the builds are fine", not "the
release will pass". The site deploy is first exercised by the tag itself,
which is why step 6 of part 1 must be done before the tag.

---

## Part 3 — verifying a release actually landed

Never say "it works" without one of these answers.

```bash
# run and job status (no auth needed; 60 requests/hour per IP)
curl -s "https://api.github.com/repos/SpiritUrban/file-sight/actions/runs?per_page=3"
curl -s "https://api.github.com/repos/SpiritUrban/file-sight/actions/runs/<RUN_ID>/jobs"

# the error text of a failed job lives HERE -- run logs need authentication
# even in a public repository, annotations do not
curl -s "https://api.github.com/repos/SpiritUrban/file-sight/check-runs/<JOB_ID>/annotations"

# rate limit exhausted?
curl -s "https://api.github.com/rate_limit"

# the updater endpoint
curl -s -L "https://github.com/SpiritUrban/file-sight/releases/latest/download/latest.json"

# every download link must answer 206
curl -s -o /dev/null -w '%{http_code}\n' -L -r 0-0 \
  "https://github.com/SpiritUrban/file-sight/releases/download/<TAG>/<FILE>"

# what the live site believes
curl -s "https://spiriturban.github.io/file-sight/download-manifest.json"
```

**A release is only finished when `latest.json` lists every platform.** Each
matrix job uploads its installers *first* and appends its updater entries
*afterwards*, so "the file downloads" happens before "an update is available
for this platform". The intermediate state looks exactly like a complete
release — all installers present, Windows entries still missing — and
Windows clients see no update. For four platforms expect the platform keys
for windows-x86_64, darwin-aarch64, darwin-x86_64 and linux-x86_64:

```bash
curl -s -L "https://github.com/SpiritUrban/file-sight/releases/download/<TAG>/latest.json" \
  | python -c "import json,sys; d=json.load(sys.stdin); print(len(d['platforms']), sorted(d['platforms']))"
```

### When the deploy is green but the site is stale

Observed on v0.6.4, and worth writing down because everything looks correct:

* the job's `::notice` said the manifest was generated for the right tag
  (`ref=v0.6.4 -> tag v0.6.4, version 0.6.4, 8 assets`);
* the Deployments API showed the tag's deployment `success` and **active**,
  and the previous one marked `inactive` at the same second;
* the live URL kept serving the previous release's manifest — ten hours
  later, with `Last-Modified` still pointing at the earlier deployment.

A CDN TTL was the obvious explanation and it is wrong: `Cache-Control` on
Pages is ten minutes, and this outlasted it by two orders of magnitude. The
cause is still unknown. What is now certain is that `deploy-pages` reporting
success does not mean the site serves what was built.

`pages.yml` therefore ends by asking the live URL what it actually serves and
failing if it never catches up. That does not fix the underlying problem, but
it stops a green run from hiding it.

If it happens: the release itself is unaffected — installers, `latest.json`
and the updater all come from the GitHub release, not from Pages. Re-run
`Actions → Deploy site → Run workflow`, or push anything matching the
workflow's `paths` filter.

---

## A red job whose work actually succeeded

Seen on `macos-x64` during the dry run: every step green, including
`Build desktop app` and `Build, sign and upload`, and then the job went red
on `Post Run actions/setup-node@v4`. The annotation is a .NET stack trace
entirely inside `GitHub.Runner.*` — the runner crashed flushing its own log
file at job completion. Nothing to do with this project, and re-running the
job is the only response.

Read the **step list** before reading the error: if the failing steps are
`Set up job`, `Post Run ...` or `Complete job`, the failure is the runner's,
not the build's. `deploy-site` is deliberately tolerant of this
(`!cancelled()` rather than requiring every matrix job to succeed), because
the assets are already uploaded by the time those steps run.

## Reading a failure

| Duration | Where to look |
| --- | --- |
| 1–3 s | configuration: billing, a missing secret, a YAML error |
| 20–40 s | dependency install or a small step |
| minutes | genuinely the code |

"Works locally, fails in CI" is an environment difference. Check in this
order: what is not in git (`git check-ignore -v <path>`), what only CI has
(an unset secret arrives as an empty string, not an error), a different OS.

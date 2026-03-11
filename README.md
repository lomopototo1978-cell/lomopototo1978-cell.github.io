# Project Handoff README

This file is for the next Copilot/session so you do not need to re-explain the project.

## 1) Project Summary

- Site type: static HTML/CSS/JS project
- Main repo: lomopototo1978-cell/lomopototo1978-cell.github.io
- Branch in use: main
- Current AI/chat page branding: BaobabGpt
- Auth mode: Supabase cloud auth is primary, localStorage fallback exists in code

## 2) Key Files

- index.html: login page (Supabase login + remember session + typing title animation)
- register.html: signup page (Supabase sign up in cloud mode)
- dashboard.html: protected user dashboard
- stargenzimbabwe.html: BaobabGpt chat UI + local knowledge engine
- auth-config.js: runtime config values (Supabase + optional EmailJS)
- model-data.json: model/knowledge data file in repo
- styles.css + script.js: shared site styles and JS for non-chat pages

## 3) Important Runtime Keys (Current Values)

From auth-config.js:

- SUPABASE_URL
  - https://xnwagtojdworipbrfaeu.supabase.co
- SUPABASE_ANON_KEY
  - eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhud2FndG9qZHdvcmlwYnJmYWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMxMzI5ODgsImV4cCI6MjA4ODcwODk4OH0.p2Y5CglEHcrIXy0XWTnslQxTdvO-qCCAH-3uw2PAO5k
- EMAILJS_PUBLIC_KEY
  - empty
- EMAILJS_SERVICE_ID
  - empty
- EMAILJS_TEMPLATE_ID
  - empty

Note:
- Supabase anon key is designed for client use, but still treat it as sensitive config and rotate if leaked beyond expected use.

## 4) Auth Architecture and Behaviors

### Supabase client init

All auth pages use:
- window.supabase CDN library
- local variable name sbClient (NOT supabase)

Reason:
- Previous critical bug was a name collision with UMD global var supabase.
- Always keep local variable as sbClient to avoid breaking all page scripts.

### Session storage keys

- USER_KEY = mvumi_users_v1
- SESSION_KEY = mvumi_session_v1
- REMEMBER_PREF_KEY = mvumi_remember_pref_v1 (login remember checkbox)
- PENDING_KEY = mvumi_pending_signup_v1 (legacy OTP/local mode flow)

### Flow notes

- index.html:
  - If Supabase configured, checks cloud session first.
  - If no cloud session, clears stale local session to avoid redirect loops.
- register.html:
  - In Supabase mode, uses direct signUp (no OTP dependency).
- dashboard.html:
  - Uses Supabase session first.
  - If Supabase configured but no cloud session, clears local session and redirects to login.

## 5) Branding Changes Completed

- Ask Star renamed to BaobabGpt in stargenzimbabwe.html text/UI.
- Dashboard app card text now shows Baobab/Gpt.
- Chat logic still on same page path: stargenzimbabwe.html.

## 6) Hosting and Deployment

### GitHub Pages

- Repo pushes to main still work as normal.
- Historical domain used: mvumi.me.

### Azure Web App (active)

- Subscription: Azure for Students (c61c3d8d-59d5-4a80-b9e1-14c6cd05109f)
- Resource group: mvumi-rg
- App Service plan: mvumi-plan (Linux Free tier)
- Web app name: mvumi-site
- Default host: mvumi-site.azurewebsites.net
- Region: South Africa North

### Deploy command used successfully

From project root:

1) Create zip:
- Compress-Archive -Path .\* -DestinationPath "$env:TEMP\mvumi-deploy.zip" -Force

2) Deploy:
- $az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
- & $az webapp deploy --name mvumi-site --resource-group mvumi-rg --src-path "$env:TEMP\mvumi-deploy.zip" --type zip

## 7) Domain and SSL Notes

- Custom hostnames bound in Azure:
  - mvumi.me
  - www.mvumi.me
- TXT verification value used (asuid):
  - 65A275D2E67CE06DBF9C80C2B4AC450D1F771DEF635E720830C01DC8D0B84612

Important SSL constraint:
- Azure managed cert is not supported on Free tier App Service.
- SSL must be handled via CDN/proxy or by upgrading App Service plan.

Cloudflare/Namecheap path in progress:
- Namecheap Supersonic CDN/SSL was in validating state during setup.
- If SSL errors persist, verify DNS target and CDN SSL mode.

## 8) Known Gotchas

1. Do not rename sbClient back to supabase.
2. Free App Service tier has SSL limitations for custom domains.
3. If login/register suddenly reloads form with no JS behavior, check browser console first for script parse errors.
4. If custom domain works on HTTP but not HTTPS, it is usually certificate/proxy propagation, not app code.

## 9) Fast Troubleshooting Commands

### Check latest commits
- git log --oneline -5

### Check Azure app status
- $az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
- & $az webapp show --name mvumi-site --resource-group mvumi-rg --query "{state:state,url:defaultHostName}" -o table

### Check hostname bindings
- & $az webapp config hostname list --webapp-name mvumi-site --resource-group mvumi-rg -o table

### Quick DNS check (PowerShell)
- Resolve-DnsName mvumi.me
- Resolve-DnsName www.mvumi.me

## 10) If Next Copilot Needs to Continue Work

Suggested first checks:

1. Read auth-config.js for current runtime keys.
2. Verify Supabase session behavior on index/register/dashboard.
3. Verify domain SSL status at mvumi.me and www.mvumi.me.
4. If UI changes requested for BaobabGpt, edit stargenzimbabwe.html only unless shared assets are needed.

## 11) Last Important Commits

- 903831a Rename Ask Star branding to BaobabGpt
- 43ec72c Redesign Ask Star UI to modern centered chat layout
- bda7295 Fix supabase variable collision by using sbClient

End of handoff.

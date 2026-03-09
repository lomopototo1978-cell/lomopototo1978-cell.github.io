const sections = document.querySelectorAll('.reveal');

const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.2 }
);

sections.forEach((section, index) => {
  section.style.animationDelay = `${index * 120}ms`;
  observer.observe(section);
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js', { updateViaCache: 'none' });
  });
}

/* ---- Install App ---- */
let deferredPrompt = null;
const installBtn = document.getElementById('installBtn');
const installBanner = document.getElementById('installBanner');
const installBannerBtn = document.getElementById('installBannerBtn');
const installBannerText = document.getElementById('installBannerText');
const dismissBannerBtn = document.getElementById('dismissBannerBtn');
const isMobile = window.matchMedia('(max-width: 860px)').matches;
const isStandalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
const dismissed = localStorage.getItem('installDismissed') === '1';

// Show floating banner on mobile if not already installed/dismissed
if (installBanner && isMobile && !isStandalone && !dismissed) {
  installBanner.hidden = false;
}

// Capture the browser install prompt when it fires (requires HTTPS)
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  if (installBtn) installBtn.hidden = false;
});

async function triggerInstall() {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    hideInstallUI();
  } else {
    // No native prompt available — show manual instructions
    if (installBannerText) {
      installBannerText.textContent =
        'Tap the \u22ee menu (3 dots) at the top-right of Chrome, then tap "Install app" or "Add to Home screen".';
    }
    if (installBanner) installBanner.hidden = false;
  }
}

function hideInstallUI() {
  if (installBtn) installBtn.hidden = true;
  if (installBanner) installBanner.hidden = true;
  localStorage.setItem('installDismissed', '1');
}

if (installBtn) installBtn.addEventListener('click', triggerInstall);
if (installBannerBtn) installBannerBtn.addEventListener('click', triggerInstall);
if (dismissBannerBtn) dismissBannerBtn.addEventListener('click', hideInstallUI);

window.addEventListener('appinstalled', hideInstallUI);

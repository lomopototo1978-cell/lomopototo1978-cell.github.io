const sections = document.querySelectorAll('.reveal');
const installButton = document.getElementById('installButton');
const installHint = document.getElementById('installHint');
let deferredInstallPrompt;

const ua = window.navigator.userAgent.toLowerCase();
const isIos = /iphone|ipad|ipod/.test(ua);
const isInStandaloneMode = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

if (installHint && !isInStandaloneMode) {
  if (isIos) {
    installHint.hidden = false;
    installHint.textContent = 'iPhone: tap Share, then Add to Home Screen.';
  } else if (/android/.test(ua)) {
    installHint.hidden = false;
    installHint.textContent = 'Android: use browser menu and tap Install app.';
  }
}

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

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;

  if (installButton) {
    installButton.hidden = false;
  }
});

if (installButton) {
  installButton.addEventListener('click', async () => {
    if (!deferredInstallPrompt) {
      return;
    }

    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installButton.hidden = true;
    if (installHint) {
      installHint.hidden = true;
    }
  });
}

window.addEventListener('appinstalled', () => {
  deferredInstallPrompt = null;
  if (installButton) {
    installButton.hidden = true;
  }
  if (installHint) {
    installHint.hidden = true;
  }
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js');
  });
}

const sections = document.querySelectorAll('.reveal');
const installButton = document.getElementById('installButton');
const installHint = document.getElementById('installHint');
const installBanner = document.getElementById('installBanner');
const installBannerAction = document.getElementById('installBannerAction');
const dismissBanner = document.getElementById('dismissBanner');
let deferredInstallPrompt;

const ua = window.navigator.userAgent.toLowerCase();
const isIos = /iphone|ipad|ipod/.test(ua);
const isAndroid = /android/.test(ua);
const isInStandaloneMode = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
const shouldUseMobileBanner = window.matchMedia('(max-width: 860px)').matches;
const bannerDismissed = window.localStorage.getItem('installBannerDismissed') === '1';

if (installBanner && shouldUseMobileBanner && isAndroid && !isInStandaloneMode && !bannerDismissed) {
  installBanner.hidden = false;
}

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

  if (installBannerAction) {
    installBannerAction.disabled = false;
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

if (installBannerAction) {
  installBannerAction.addEventListener('click', async () => {
    if (!deferredInstallPrompt) {
      if (installHint) {
        installHint.hidden = false;
        installHint.textContent = 'Open browser menu and tap Install app.';
      }
      return;
    }

    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    if (installBanner) {
      installBanner.hidden = true;
    }
  });
}

if (dismissBanner) {
  dismissBanner.addEventListener('click', () => {
    window.localStorage.setItem('installBannerDismissed', '1');
    if (installBanner) {
      installBanner.hidden = true;
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
  if (installBanner) {
    installBanner.hidden = true;
  }
  window.localStorage.setItem('installBannerDismissed', '1');
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js', { updateViaCache: 'none' });
  });
}

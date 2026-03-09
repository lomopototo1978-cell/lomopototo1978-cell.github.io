const sections = document.querySelectorAll('.reveal');
const installButton = document.getElementById('installButton');
let deferredInstallPrompt;

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
  });
}

window.addEventListener('appinstalled', () => {
  deferredInstallPrompt = null;
  if (installButton) {
    installButton.hidden = true;
  }
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js');
  });
}

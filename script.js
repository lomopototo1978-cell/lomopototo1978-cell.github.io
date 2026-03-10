const shell = document.getElementById("shell");
const panel = document.getElementById("panel");
const ticker = document.getElementById("ticker");
const loginForm = document.getElementById("loginForm");
const loginBtn = document.getElementById("loginBtn");
const statusText = document.getElementById("statusText");
const email = document.getElementById("email");
const emailHint = document.getElementById("emailHint");
const password = document.getElementById("password");
const strengthBar = document.querySelector("#strengthBar span");
const togglePassword = document.getElementById("togglePassword");

function setPointerVars(x, y) {
  const w = window.innerWidth || 1;
  const h = window.innerHeight || 1;
  const px = (x / w) * 100;
  const py = (y / h) * 100;
  document.documentElement.style.setProperty("--mx", px + "%");
  document.documentElement.style.setProperty("--my", py + "%");

  const centerX = w / 2;
  const centerY = h / 2;
  const dx = (x - centerX) / centerX;
  const dy = (y - centerY) / centerY;
  const tiltX = dy * -5;
  const tiltY = dx * 6;
  panel.style.transform = "rotateX(" + tiltX.toFixed(2) + "deg) rotateY(" + tiltY.toFixed(2) + "deg)";
}

window.addEventListener("pointermove", (event) => {
  setPointerVars(event.clientX, event.clientY);
});

window.addEventListener("pointerleave", () => {
  panel.style.transform = "rotateX(0deg) rotateY(0deg)";
});

function scorePassword(value) {
  let score = 0;
  if (value.length >= 6) score += 25;
  if (/[A-Z]/.test(value)) score += 20;
  if (/[0-9]/.test(value)) score += 20;
  if (/[^A-Za-z0-9]/.test(value)) score += 20;
  if (value.length >= 10) score += 15;
  return Math.min(100, score);
}

password.addEventListener("input", () => {
  const score = scorePassword(password.value);
  strengthBar.style.width = score + "%";

  if (score < 40) {
    strengthBar.style.background = "#ff5c35";
  } else if (score < 70) {
    strengthBar.style.background = "#ffd12f";
  } else {
    strengthBar.style.background = "#00c95f";
  }
});

togglePassword.addEventListener("click", () => {
  const isPassword = password.type === "password";
  password.type = isPassword ? "text" : "password";
  togglePassword.textContent = isPassword ? "HIDE" : "SHOW";
});

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

email.addEventListener("input", () => {
  if (!email.value) {
    emailHint.textContent = "Use a valid email address.";
    return;
  }
  emailHint.textContent = isValidEmail(email.value)
    ? "Looks good."
    : "Email format is incorrect.";
});

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const okEmail = isValidEmail(email.value);
  const okPassword = password.value.length >= 6;

  if (!okEmail || !okPassword) {
    statusText.textContent = "Access denied. Check credentials and try again.";
    statusText.style.background = "#ffc7b8";
    statusText.style.animation = "shake 0.28s linear";
    setTimeout(() => {
      statusText.style.animation = "";
    }, 280);
    return;
  }

  loginBtn.disabled = true;
  statusText.textContent = "Authenticating...";
  statusText.style.background = "#fff4cb";

  setTimeout(() => {
    statusText.textContent = "Access granted. Redirecting to dashboard...";
    statusText.style.background = "#d8ffbf";
    loginBtn.disabled = false;
  }, 1200);
});

const style = document.createElement("style");
style.textContent = "@keyframes shake { 0%,100%{transform:translateX(0)} 25%{transform:translateX(-4px)} 75%{transform:translateX(4px)} }";
document.head.appendChild(style);

if (ticker) {
  ticker.innerHTML += ticker.innerHTML;
}

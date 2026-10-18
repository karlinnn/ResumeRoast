/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ResumeRoast – app.js
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

// ── SVG gradient ──────────────────────────────────────
const svgNS = 'http://www.w3.org/2000/svg';
const defs = document.createElementNS(svgNS, 'svg');
defs.setAttribute('class', 'svg-defs');
defs.innerHTML = `
  <defs>
    <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ff6200"/>
      <stop offset="100%" stop-color="#ffb830"/>
    </linearGradient>
  </defs>`;
document.body.prepend(defs);

// ── State ─────────────────────────────────────────────
let reportId = null;
let selectedFile = null;

// ── Capture ?src= on first visit ─────────────────────
(function captureSrc() {
  const params = new URLSearchParams(window.location.search);
  const src = params.get('src');
  if (src) {
    try { sessionStorage.setItem('rr_src', src); } catch (_) {}
  }
})();

// ── DOM refs ──────────────────────────────────────────
const dropZone    = document.getElementById('drop-zone');
const fileInput   = document.getElementById('resume-file');
const fileInfo    = document.getElementById('file-info');
const jdInput     = document.getElementById('jd-input');
const jdChars     = document.getElementById('jd-chars');
const submitBtn   = document.getElementById('submit-btn');
const roastForm   = document.getElementById('roast-form');

const uploadSection  = document.getElementById('upload-section');
const resultSection  = document.getElementById('result-section');
const loadingOverlay = document.getElementById('loading-overlay');
const loadingMsg     = document.getElementById('loading-msg');

const scoreNum    = document.getElementById('score-num');
const ringProgress = document.getElementById('ring-progress');
const scoreVerdict = document.getElementById('score-verdict');
const scoreBadge  = document.getElementById('score-badge');
const roastList   = document.getElementById('roast-list');

const unlockBanner  = document.getElementById('unlock-banner');
const paidReport    = document.getElementById('paid-report');

// ── File handling ─────────────────────────────────────
dropZone.addEventListener('click', (e) => {
  if (e.target === fileInput || e.target.closest('label')) return;
  fileInput.click();
});

dropZone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});

dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

function handleFile(file) {
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    showToast('Please upload a PDF file.', 'error'); return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showToast('File is larger than 2 MB. Please compress it.', 'error'); return;
  }
  selectedFile = file;
  dropZone.classList.add('has-file');
  fileInfo.classList.remove('hidden');
  fileInfo.innerHTML = `✅ <strong>${escHtml(file.name)}</strong> — ${(file.size / 1024).toFixed(0)} KB`;
  checkFormReady();
}

// ── JD counter ────────────────────────────────────────
jdInput.addEventListener('input', () => {
  jdChars.textContent = jdInput.value.length;
  checkFormReady();
});

function checkFormReady() {
  submitBtn.disabled = !(selectedFile && jdInput.value.trim().length > 10);
}

// ── Form submit ───────────────────────────────────────
roastForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!selectedFile || !jdInput.value.trim()) return;

  showLoading('Reading your resume…');
  setTimeout(() => setLoadingMsg('Roasting with AI… 🔥'), 3000);

  const fd = new FormData();
  fd.append('resume', selectedFile);
  fd.append('jd', jdInput.value.trim());

  try {
    const res = await fetch('/analyze', { method: 'POST', body: fd });
    const data = await res.json();

    if (!res.ok) { throw new Error(data.detail || 'Analysis failed.'); }

    reportId = data.report_id;
    hideLoading();
    renderFreeResult(data);

  } catch (err) {
    hideLoading();
    showToast(err.message || 'Something went wrong. Please try again.', 'error');
  }
});

// ── Render free result ────────────────────────────────
function renderFreeResult(data) {
  uploadSection.classList.add('hidden');
  resultSection.classList.remove('hidden');
  resultSection.scrollIntoView({ behavior: 'smooth' });

  // Score ring
  const score = Math.max(0, Math.min(100, data.score || 0));
  scoreNum.textContent = score;
  const circumference = 327; // 2π×52
  const offset = circumference - (score / 100) * circumference;
  // Animate
  setTimeout(() => {
    ringProgress.style.strokeDashoffset = offset;
  }, 100);

  // Verdict & badge
  scoreVerdict.textContent = data.verdict || '';
  const { label, cls } = badgeTier(data.badge);
  scoreBadge.textContent = label;
  scoreBadge.className = `score-badge ${cls}`;

  // Roast items
  roastList.innerHTML = '';
  (data.roast || []).forEach((item, i) => {
    const li = document.createElement('li');
    li.innerHTML = `<span class="roast-num">${i + 1}</span><span>${escHtml(item)}</span>`;
    roastList.appendChild(li);
    setTimeout(() => li.classList.add('visible'), 200 + i * 150);
  });
}

function badgeTier(badge) {
  switch (badge) {
    case 'Needs work':    return { label: '💀 Needs work',    cls: 'poor' };
    case 'Getting there': return { label: '⚠️ Getting there', cls: 'average' };
    case 'Strong':        return { label: '👍 Strong',        cls: 'good' };
    case 'Excellent':     return { label: '🌟 Excellent',     cls: 'great' };
    default:              return { label: '🔥 Roasted',       cls: 'average' };
  }
}

// ── Unlock / payment ──────────────────────────────────
async function unlockReport() {
  if (!reportId) { showToast('No report loaded.', 'error'); return; }

  const btn = document.getElementById('unlock-btn');
  btn.disabled = true;
  btn.innerHTML = '<span>Creating order…</span>';

  try {
    const res = await fetch('/create-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ report_id: reportId }),
    });
    const order = await res.json();
    if (!res.ok) throw new Error(order.detail || 'Order creation failed.');

    if (order.already_paid) {
      // Fetch paid report directly
      await fetchAndRenderPaid();
      return;
    }

    // Open Razorpay checkout
    const rzp = new Razorpay({
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      order_id: order.order_id,
      name: 'ResumeRoast',
      description: 'Full Resume Analysis',
      image: 'https://emoji.slack-edge.com/T0266FRGM/fire/bc98c8b0.png',
      theme: { color: '#ff6200' },
      handler: async function (response) {
        // Verify on server
        try {
          const vRes = await fetch('/verify-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              report_id: reportId,
            }),
          });
          const vData = await vRes.json();
          if (!vRes.ok) throw new Error(vData.detail || 'Payment verification failed.');
          await fetchAndRenderPaid();
        } catch (err) {
          showToast(err.message || 'Payment verification failed. Please contact support.', 'error');
          btn.disabled = false;
          btn.innerHTML = '<span>⚡ Unlock Full Report — ₹30</span>';
        }
      },
      modal: {
        ondismiss: () => {
          btn.disabled = false;
          btn.innerHTML = '<span>⚡ Unlock Full Report — ₹30</span>';
        },
      },
    });
    rzp.open();

  } catch (err) {
    showToast(err.message || 'Something went wrong.', 'error');
    btn.disabled = false;
    btn.innerHTML = '<span>⚡ Unlock Full Report — ₹30</span>';
  }
}

async function fetchAndRenderPaid() {
  showLoading('Unlocking your full report…');
  try {
    const res = await fetch(`/result/${reportId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not load paid report.');
    hideLoading();
    renderPaidReport(data);
  } catch (err) {
    hideLoading();
    showToast(err.message, 'error');
  }
}

function renderPaidReport(data) {
  // Hide unlock banner, show paid section
  unlockBanner.classList.add('hidden');
  paidReport.classList.remove('hidden');
  paidReport.scrollIntoView({ behavior: 'smooth' });

  // Bullet rewrites
  const bwrap = document.getElementById('bullet-rewrites');
  bwrap.innerHTML = '';
  (data.bullet_rewrites || []).forEach(({ original, improved }) => {
    const div = document.createElement('div');
    div.className = 'rewrite-item';
    div.innerHTML = `
      <div class="rewrite-original">${escHtml(original || '')}</div>
      <div class="rewrite-improved">${escHtml(improved || '')}</div>`;
    bwrap.appendChild(div);
  });

  // Keywords
  const kgrid = document.getElementById('missing-keywords');
  kgrid.innerHTML = '<div class="keywords-grid"></div>';
  const grid = kgrid.querySelector('.keywords-grid');
  (data.missing_keywords || []).forEach((kw) => {
    const tag = document.createElement('span');
    tag.className = 'keyword-tag';
    tag.textContent = kw;
    grid.appendChild(tag);
  });

  // Cold email
  document.getElementById('cold-email').textContent = data.cold_email || '';

  // Improved resume
  document.getElementById('improved-resume').textContent = data.improved_resume_text || '';
}

// ── Share / copy ──────────────────────────────────────
function shareScore() {
  const score = scoreNum.textContent;
  const verdict = scoreVerdict.textContent;
  const text = `I got ${score}/100 on ResumeRoast 🔥\n"${verdict}"\nGet yours roasted too: ${location.origin}`;
  if (navigator.share) {
    navigator.share({ title: 'ResumeRoast Score', text, url: location.origin }).catch(() => {});
    logEvent('score_card_shared');
  } else {
    copyToClipboard(text);
    showToast('Score copied to clipboard!', 'success');
  }
}

function copyLink() {
  copyToClipboard(location.origin);
  showToast('Link copied!', 'success');
}

function copyEmail() {
  const txt = document.getElementById('cold-email').textContent;
  copyToClipboard(txt);
  showToast('Email copied!', 'success');
}

function copyResume() {
  const txt = document.getElementById('improved-resume').textContent;
  copyToClipboard(txt);
  showToast('Resume text copied!', 'success');
}

function copyToClipboard(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).catch(() => {});
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

// ── Start over ────────────────────────────────────────
function startOver() {
  reportId = null;
  selectedFile = null;
  fileInput.value = '';
  jdInput.value = '';
  jdChars.textContent = '0';
  fileInfo.classList.add('hidden');
  dropZone.classList.remove('has-file', 'drag-over');
  submitBtn.disabled = true;
  ringProgress.style.strokeDashoffset = 327;
  roastList.innerHTML = '';
  paidReport.classList.add('hidden');
  unlockBanner.classList.remove('hidden');
  resultSection.classList.add('hidden');
  uploadSection.classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Loading ───────────────────────────────────────────
function showLoading(msg) {
  loadingMsg.textContent = msg || 'Loading…';
  loadingOverlay.classList.remove('hidden');
}
function setLoadingMsg(msg) {
  loadingMsg.textContent = msg;
}
function hideLoading() {
  loadingOverlay.classList.add('hidden');
}

// ── Toast ──────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type = '') {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = `toast${type ? ' ' + type : ''}`;
  toast.classList.add('show');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove('show'), 3500);
}

// ── Event logging ─────────────────────────────────────
function logEvent(name) {
  // Best-effort fire-and-forget
  fetch('/analyze', { method: 'HEAD' }).catch(() => {});
  // If PostHog is loaded
  if (window.posthog) {
    window.posthog.capture(name, { report_id: reportId });
  }
}

// ── Escape HTML ───────────────────────────────────────
function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

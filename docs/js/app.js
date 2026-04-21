/* ─── COUNTER ANIMATION ─────────────────────────────────────────────────── */
function animateCounters() {
  document.querySelectorAll('.stat-num[data-target]').forEach(el => {
    const target = parseInt(el.dataset.target, 10);
    const duration = 1200;
    const step = 16;
    const increment = target / (duration / step);
    let current = 0;

    const timer = setInterval(() => {
      current += increment;
      if (current >= target) {
        el.textContent = target;
        clearInterval(timer);
      } else {
        el.textContent = Math.floor(current);
      }
    }, step);
  });
}

/* ─── INTERSECTION OBSERVER ─────────────────────────────────────────────── */
const observerOptions = { threshold: 0.12, rootMargin: '0px 0px -40px 0px' };

const fadeObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      fadeObserver.unobserve(entry.target);
    }
  });
}, observerOptions);

const statsObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      animateCounters();
      statsObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.5 });

/* ─── TERMINAL TYPEWRITER ────────────────────────────────────────────────── */
function initTerminal() {
  const lines = document.querySelectorAll('.terminal-body .term-line');
  lines.forEach((line, i) => {
    line.style.opacity = '0';
    line.style.transform = 'translateX(-8px)';
    line.style.transition = `opacity 0.3s ease ${i * 0.22}s, transform 0.3s ease ${i * 0.22}s`;
  });

  const termObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        lines.forEach(line => {
          line.style.opacity = '1';
          line.style.transform = 'translateX(0)';
        });
        termObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });

  const terminal = document.querySelector('.terminal');
  if (terminal) termObserver.observe(terminal);
}

/* ─── ACTIVE NAV LINK ────────────────────────────────────────────────────── */
function initScrollSpy() {
  const sections = document.querySelectorAll('section[id]');
  const links = document.querySelectorAll('.nav-links a');

  const spy = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.id;
        links.forEach(link => {
          link.style.color = link.getAttribute('href') === `#${id}`
            ? 'var(--text)'
            : '';
        });
      }
    });
  }, { threshold: 0.4 });

  sections.forEach(s => spy.observe(s));
}

/* ─── NAV SCROLL SHADOW ──────────────────────────────────────────────────── */
function initNavShadow() {
  const nav = document.querySelector('.nav-wrapper');
  window.addEventListener('scroll', () => {
    nav.style.borderBottomColor = window.scrollY > 20
      ? 'rgba(255,255,255,0.1)'
      : 'rgba(255,255,255,0.08)';
  }, { passive: true });
}

/* ─── INIT ──────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Fade-in on scroll for cards and sections
  document.querySelectorAll(
    '.feature-card, .agent-card, .step, .model-card, .gate, .pipeline-stage'
  ).forEach(el => {
    el.classList.add('fade-in');
    fadeObserver.observe(el);
  });

  // Counter animation
  const statsEl = document.querySelector('.hero-stats');
  if (statsEl) statsObserver.observe(statsEl);

  initTerminal();
  initScrollSpy();
  initNavShadow();
});

/**
 * BFF UI Kit & Controller Library — |BF> Quantum Edition
 * Supports theme switching: OS 9 & OS X.
 * Zero external dependencies.
 */

const BffUI = {
  currentTheme: 'os9',

  setTheme(theme) {
    const validTheme = (theme === 'osx' || theme === 'os9') ? theme : 'os9';
    this.currentTheme = validTheme;
    document.documentElement.setAttribute('data-theme', validTheme);
    try {
      localStorage.setItem('bff-theme', validTheme);
    } catch (e) {}

    document.querySelectorAll('.bff-theme-select').forEach((sel) => {
      sel.value = validTheme;
    });

    const label = validTheme === 'osx' ? 'OS X' : 'OS 9';
    this.showToast(`Theme changed to: ${label}`);
  },

  getSavedTheme() {
    try {
      const saved = localStorage.getItem('bff-theme');
      return (saved === 'osx' || saved === 'os9') ? saved : 'os9';
    } catch (e) {
      return 'os9';
    }
  },

  initThemeSwitcher() {
    const saved = this.getSavedTheme();
    this.currentTheme = saved;
    document.documentElement.setAttribute('data-theme', saved);

    document.querySelectorAll('.bff-theme-select').forEach((sel) => {
      sel.value = saved;
      sel.addEventListener('change', (e) => {
        this.setTheme(e.target.value);
      });
    });

    const staticBadge = document.getElementById('bffStaticBadge');
    if (staticBadge) {
      staticBadge.addEventListener('click', () => {
        this.showToast('Running on standalone JavaScript |BF> Quantum Statevector VM (zero dependencies)');
      });
    }
  },

  openModal(modalId) {
    const el = document.getElementById(modalId);
    if (!el) return;
    el.classList.add('active');
    document.body.style.overflow = 'hidden';
  },

  closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (!el) return;
    el.classList.remove('active');
    document.body.style.overflow = '';
  },

  copyText(text, toastMsg = 'Copied to clipboard!') {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        this.showToast(toastMsg);
      }).catch(() => {
        this._fallbackCopy(text, toastMsg);
      });
    } else {
      this._fallbackCopy(text, toastMsg);
    }
  },

  _fallbackCopy(text, toastMsg) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      this.showToast(toastMsg);
    } catch (e) {
      alert(toastMsg);
    }
    document.body.removeChild(ta);
  },

  downloadTextFile(filename, content, mimeType = 'text/plain;charset=utf-8') {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    this.showToast(`Downloading ${filename}`);
  },

  showToast(message, duration = 2600) {
    const existing = document.querySelector('.bff-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'bff-toast';
    const checkSpan = document.createElement('span');
    checkSpan.textContent = '✓';
    const msgSpan = document.createElement('span');
    msgSpan.textContent = message;
    toast.appendChild(checkSpan);
    toast.appendChild(msgSpan);
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  },

  setupGlobalEvents() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-backdrop.active').forEach((modal) => {
          this.closeModal(modal.id);
        });
      }
    });

    document.addEventListener('click', (e) => {
      if (e.target && e.target.classList.contains('modal-backdrop')) {
        this.closeModal(e.target.id);
      }
    });
  }
};

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    BffUI.initThemeSwitcher();
    BffUI.setupGlobalEvents();
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = BffUI;
} else if (typeof window !== 'undefined') {
  window.BffUI = BffUI;
}

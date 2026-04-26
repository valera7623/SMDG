/**
 * SMDG — адаптивность: гамбургер-навигация, классы брейкпоинтов, события resize.
 * Без внешних зависимостей. Подключается на всех публичных HTML-страницах.
 */

const MQ = {
  mobile: 768,
  tabletMax: 1024,
};

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(null, args), ms);
  };
}

export const ResponsiveManager = {
  isMobile: () => window.innerWidth < MQ.mobile,
  isTablet: () => window.innerWidth >= MQ.mobile && window.innerWidth <= MQ.tabletMax,
  isDesktop: () => window.innerWidth > MQ.tabletMax,

  isPortrait: () => window.matchMedia('(orientation: portrait)').matches,
  isLandscape: () => window.matchMedia('(orientation: landscape)').matches,

  /**
   * Таблицы с классом .responsive-data-table и [data-label] на <td> стилизуются в CSS
   * как карточки на узких экранах. Здесь — только вспомогательный хук, если нужен JS.
   */
  initResponsiveTables: () => {
    document.querySelectorAll('table.responsive-data-table').forEach((table) => {
      table.setAttribute('data-smdg-responsive', '1');
    });
  },

  /**
   * Зарезервировано для DICOM/других экранов: внешние модули могут передать callbacks.
   * @param {HTMLElement} element
   * @param {{ onPinch?: (scale: number) => void, onPan?: (dx: number, dy: number) => void }} [_callbacks]
   */
  initTouchGestures(element, _callbacks) {
    if (!element) return;
    element.dataset.smdgTouchInit = '1';
  },
};

/**
 * @param {object} [opts]
 * @param {string} [opts.hamburgerId]
 * @param {string} [opts.navId]
 * @param {string} [opts.backdropId]
 */
export function initResponsiveUI(opts = {}) {
  const hamburger = document.getElementById(opts.hamburgerId || 'smdgMenuToggle');
  const nav = document.getElementById(opts.navId || 'smdgMainNav');
  const backdrop = document.getElementById(opts.backdropId || 'smdgNavBackdrop');

  function closeNav() {
    if (nav) nav.classList.remove('is-open');
    if (hamburger) {
      hamburger.setAttribute('aria-expanded', 'false');
      hamburger.classList.remove('is-active');
    }
    if (backdrop) backdrop.hidden = true;
    document.body.classList.remove('smdg-nav-open');
  }

  function openNav() {
    if (nav) nav.classList.add('is-open');
    if (hamburger) {
      hamburger.setAttribute('aria-expanded', 'true');
      hamburger.classList.add('is-active');
    }
    if (backdrop) backdrop.hidden = false;
    document.body.classList.add('smdg-nav-open');
  }

  function toggleNav() {
    if (nav?.classList.contains('is-open')) closeNav();
    else openNav();
  }

  if (hamburger && nav) {
    hamburger.addEventListener('click', (e) => {
      e.preventDefault();
      toggleNav();
    });
    nav.querySelectorAll('a[href]').forEach((a) => {
      a.addEventListener('click', () => {
        if (window.innerWidth < 1024) closeNav();
      });
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', closeNav);
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeNav();
  });

  const onResize = debounce(() => {
    if (window.innerWidth >= 1024) closeNav();
    document.body.dataset.smdgBreakpoint = ResponsiveManager.isMobile()
      ? 'mobile'
      : ResponsiveManager.isTablet()
        ? 'tablet'
        : 'desktop';
    document.dispatchEvent(new CustomEvent('smdg:resize'));
  }, 150);

  window.addEventListener('resize', onResize);
  onResize();

  ResponsiveManager.initResponsiveTables();
}

export default { ResponsiveManager, initResponsiveUI };

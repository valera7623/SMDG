(function () {
  var STORAGE_KEY = "smdg-docs-lang";
  var path = window.location.pathname;

  if (path.indexOf("/help") !== 0 && path.indexOf("/help/") !== 0) {
    return;
  }

  var isEn = /\/help\/en(\/|$)/.test(path);
  var isRuLanding = /\/help\/?$/.test(path);

  function saveLang(lang) {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      /* ignore */
    }
  }

  function readLang() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  var stored = readLang();
  if (stored === "en" && isRuLanding) {
    window.location.replace("/help/en/");
    return;
  }
  if (stored === "ru" && isEn && /\/help\/en\/?$/.test(path)) {
    window.location.replace("/help/");
    return;
  }

  if (!stored && isRuLanding) {
    var langs = navigator.languages || [navigator.language || "ru"];
    var prefersEn = langs.some(function (l) {
      return String(l).toLowerCase().indexOf("en") === 0;
    });
    if (prefersEn) {
      saveLang("en");
      window.location.replace("/help/en/");
      return;
    }
    saveLang("ru");
  }

  if (isEn) {
    saveLang("en");
  } else if (/\/help\//.test(path) && !isEn) {
    saveLang("ru");
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link) {
      return;
    }
    var href = link.getAttribute("href") || "";
    if (href.indexOf("/help/en") !== -1 || href.indexOf("/en/") !== -1) {
      saveLang("en");
    } else if (href === "/help/" || href === "/help" || href.indexOf("/help/") === 0) {
      saveLang("ru");
    }
  });
})();

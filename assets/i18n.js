/*
 * Andreas Krings — EN/DE language switcher
 * Shared by all 5 pages. German dictionary is defined per-page via window.AK_I18N.
 * English defaults are captured from the DOM on first load, so the en dict is implicit.
 */
(function () {
  'use strict';
  var KEY = 'ak-lang';

  // ---- Shared German dictionary (UI chrome + work titles used on multiple pages) ----
  var SHARED_DE = {
    // nav / menu
    'nav.works': 'Arbeiten',
    'nav.about': 'Über',
    'nav.contact': 'Kontakt',
    'menu.works': 'Arbeiten',
    'menu.about': 'Über',
    'menu.contact': 'Kontakt',
    'menu.close': 'Schließen',
    'menu.foot': 'Berlin, Deutschland · ',
    // footer
    'footer.top': 'Nach oben',
    'footer.meta': 'Berlin · Deutschland',
    // floating eye
    'orb.aria': 'Alle Arbeiten ansehen',
    'about-orb.aria': 'Ein weiteres Porträt zeigen',
    // work titles (12)
    'work.title.1': 'Das Gewicht des Schwebens',
    'work.title.2': 'Eine Tür für den Winter',
    'work.title.3': 'Erinnerung an eine blaue Stunde',
    'work.title.4': 'Der Garten, der fortzog',
    'work.title.5': 'Porträt einer Stunde',
    'work.title.6': 'Was der Mond vergaß',
    'work.title.7': 'Ein Raum ohne Ecken',
    'work.title.8': 'Die Uhr, die ihre Stunden verliert',
    'work.title.9': 'Die Schublade des Leuchtturms',
    'work.title.10': 'Der Regen, der nach oben fiel',
    'work.title.11': 'Die Treppe des Meeres',
    'work.title.12': 'Der Spiegel des Ozeans',

    // work titles 13+ (added via dashboard)
    'work.title.13': 'ABC',

    // exhibition names
    'ex.1': 'Das Gewicht des Schwebens',
    'ex.2': 'Räume ohne Ecken',
    'ex.3': 'Was der Mond vergaß',
    'ex.4': 'Der Garten, der fortzog',
    'ex.5': 'Blaue Stunden'
  };

  function getLang() {
    try { return localStorage.getItem(KEY) === 'de' ? 'de' : 'en'; } catch (e) { return 'en'; }
  }
  function setLang(l) {
    try { localStorage.setItem(KEY, l); } catch (e) { /* embedded preview may block storage */ }
  }

  function deDict() {
    var page = (window.AK_I18N && window.AK_I18N.de) || {};
    var d = {};
    Object.keys(SHARED_DE).forEach(function (k) { d[k] = SHARED_DE[k]; });
    Object.keys(page).forEach(function (k) { d[k] = page[k]; });
    return d;
  }

  // capture english defaults (first text node) on first pass
  var defaults = {};
  function capture() {
    var els = document.querySelectorAll('[data-i18n],[data-i18n-html],[data-i18n-ph],[data-i18n-aria]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var key = el.getAttribute('data-i18n');
      if (!key && !el.getAttribute('data-i18n-html') && !el.getAttribute('data-i18n-ph') && !el.getAttribute('data-i18n-aria')) continue;
      if (key && !(key in defaults)) {
        var tn = firstTextNode(el);
        defaults[key] = tn ? tn.nodeValue : el.textContent;
      }
      var htmlKey = el.getAttribute('data-i18n-html');
      if (htmlKey && !(htmlKey in defaults)) {
        defaults[htmlKey] = el.innerHTML;
      }
      var ariaKey = el.getAttribute('data-i18n-aria');
      if (ariaKey && !(ariaKey in defaults)) {
        defaults[ariaKey] = el.getAttribute('aria-label') || '';
      }
    }
  }

  function firstTextNode(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var n;
    while ((n = walker.nextNode())) {
      if (n.nodeValue.trim()) return n;
    }
    return null;
  }

  function setText(el, text) {
    var tn = firstTextNode(el);
    if (tn) { tn.nodeValue = text; }
    else { el.textContent = text; }
  }

  function apply() {
    var lang = getLang();
    document.documentElement.lang = lang === 'de' ? 'de' : 'en';
    var dict = lang === 'de' ? deDict() : {};
    var els = document.querySelectorAll('[data-i18n],[data-i18n-html],[data-i18n-ph],[data-i18n-aria]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var key = el.getAttribute('data-i18n');
      var val = dict[key];
      if (lang === 'de' && val !== undefined) setText(el, val);
      else if (defaults[key] !== undefined) setText(el, defaults[key]);
      var htmlKey = el.getAttribute('data-i18n-html');
      if (htmlKey) {
        var htmlVal = dict[htmlKey];
        if (lang === 'de' && htmlVal !== undefined) el.innerHTML = htmlVal;
        else if (defaults[htmlKey] !== undefined) el.innerHTML = defaults[htmlKey];
        continue;
      }
      var phKey = el.getAttribute('data-i18n-ph');
      if (phKey) {
        var phVal = dict[phKey];
        var phDefault = defaults[phKey];
        if (phDefault === undefined) { phDefault = el.getAttribute('placeholder') || ''; defaults[phKey] = phDefault; }
        el.setAttribute('placeholder', lang === 'de' && phVal !== undefined ? phVal : phDefault);
      }
      var ariaKey = el.getAttribute('data-i18n-aria');
      if (ariaKey) {
        var ariaVal = dict[ariaKey];
        el.setAttribute('aria-label', lang === 'de' && ariaVal !== undefined ? ariaVal : (defaults[ariaKey] || ''));
      }
    }
    // toggle buttons — show current + other language
    var toggles = document.querySelectorAll('.lang-toggle');
    for (var t = 0; t < toggles.length; t++) {
      toggles[t].setAttribute('aria-pressed', lang === 'de' ? 'true' : 'false');
      var cur = toggles[t].querySelector('.lang-toggle__cur');
      var alt = toggles[t].querySelector('.lang-toggle__alt');
      if (cur) cur.textContent = lang === 'de' ? 'DE' : 'EN';
      if (alt) alt.textContent = lang === 'de' ? 'EN' : 'DE';
    }
    // notify page scripts (work viewer re-renders titles/descriptions)
    document.dispatchEvent(new CustomEvent('ak:langchange', { detail: lang }));
  }

  function init() {
    capture();
    apply();
    var toggles = document.querySelectorAll('.lang-toggle');
    for (var i = 0; i < toggles.length; i++) {
      toggles[i].addEventListener('click', function () {
        setLang(getLang() === 'de' ? 'en' : 'de');
        apply();
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  // public accessor for page scripts (e.g. work viewer)
  window.AK_I18N_CURRENT = function () { return getLang(); };
})();

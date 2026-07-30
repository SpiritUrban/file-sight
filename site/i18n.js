/* Translations and the language switch.
 *
 * English lives in the markup as well as here, on purpose: the page is
 * readable before any script runs, and a crawler that ignores JavaScript still
 * gets real content. The dictionary below is what the switch applies.
 *
 * Choosing a language, in order:
 *   1. what the visitor last chose (localStorage) -- an explicit choice must
 *      never be overridden by a guess;
 *   2. the browser's languages -- Ukrainian if any of them is Ukrainian;
 *   3. English.
 *
 * Only `uk` maps to Ukrainian. Mapping other languages to it would be a guess
 * about who reads what, and guessing wrong is worse than defaulting.
 */

window.FileSightI18n = (function () {
  "use strict";

  var STORAGE_KEY = "filesight.site.lang";
  var SUPPORTED = ["en", "uk"];

  var STRINGS = {
    en: {
      "document.title":
        "FileSight — local image and video analysis that suggests readable file names",
      "lang.label": "Language",
      "features.label": "What it does",

      "hero.tagline":
        "Your photos and clips get names you can read — and it all happens on your own machine. On Windows, the installer contains everything.",
      "hero.download": "Download",
      "hero.source": "Source on GitHub",

      "feature.local.title": "Local, not uploaded",
      "feature.local.body":
        "A vision model runs on your machine and describes each file. Nothing leaves the computer, so private folders stay private.",
      "feature.confirm.title": "Nothing renames itself",
      "feature.confirm.body":
        "You see the suggested names, edit any of them, validate, and dry-run first. Files change only after you confirm the plan.",
      "feature.undo.title": "Every rename is reversible",
      "feature.undo.body":
        "Each operation is journalled, so one click undoes the last batch — including swaps, cycles and case-only changes.",
      "feature.media.title": "Images and short videos",
      "feature.media.body":
        "JPEG, PNG and WebP, plus MP4, MOV, MKV, WebM and AVI clips: frames are sampled and the clearest ones describe the file.",
      "feature.setup.title": "No setup on Windows",
      "feature.setup.body":
        "The analysis engine ships inside the installer. No Python, no PATH, no commands — and FFmpeg for video is one button in the app.",
      "feature.updates.title": "Keeps itself current",
      "feature.updates.body":
        "An installed copy notices a new release, shows a banner and installs it. Every update is signed, and only signed ones are accepted.",

      "downloads.title": "Downloads",
      "downloads.all": "All releases and checksums on GitHub",
      "card.win.exe": "Installer (.exe) · recommended",
      "card.win.msi": "MSI package · for deployment",
      "card.mac.arm": "Apple Silicon (.dmg)",
      "card.mac.intel": "Intel (.dmg)",
      "card.linux.appimage": "AppImage",
      "card.linux.deb": "Debian / Ubuntu (.deb)",
      "badge.complete": "Everything included",
      "badge.needs": "Needs Python 3.11+",

      "requirements.title": "Install and run — nothing else to set up",
      "requirements.windows":
        "<strong>On Windows the installer is self-contained.</strong> The analysis engine ships inside it, so there is no Python to install, no PATH to edit and no commands to run. Download, install, choose a folder. The first analysis downloads the vision model once (about 1&nbsp;GB) and caches it; everything after that works offline.",
      "requirements.ffmpeg":
        "Video support needs FFmpeg, and that is one click too: the app offers to fetch it into its own folder, without touching anything else on the system.",
      "requirements.updates":
        "Updates are built in — an installed copy notices a new release and offers to install it.",
      "requirements.caveat":
        '<strong>macOS and Linux builds are not self-contained yet.</strong> They still need <strong>Python 3.11+</strong> with the FileSight core installed — the <a href="https://github.com/SpiritUrban/file-sight" rel="noopener">README</a> has the two commands. Freezing the engine for those platforms is the next step. The macOS builds are also unsigned, so Gatekeeper asks for a right-click → Open the first time.',

      "footer.author":
        'Built by <a href="https://spiriturban.github.io/" rel="author noopener">Vitaliy Dyachuk</a> — more projects and services on the <a href="https://spiriturban.github.io/" rel="noopener">personal hub</a>.',
      "footer.legal":
        'MIT licensed. <a href="https://github.com/SpiritUrban/file-sight" rel="noopener">Source</a> · <a href="https://github.com/SpiritUrban/file-sight/issues" rel="noopener">Report a problem</a>',

      // Strings the script builds at run time.
      "version.loading": "Loading release information…",
      "version.released": "Version {version} · released {date}",
      "version.unpublished": "Version {version} · not published yet",
      "note.pick":
        "Pick the package for your system. Installers are built by GitHub Actions from the tagged source.",
      "note.noassets":
        "This release has no installers attached yet. The GitHub releases page has everything that is published.",
      "note.norelease":
        "No release is published yet. Watch the repository to hear about the first one.",
      "note.failed":
        "Release information could not be loaded ({error}). The GitHub releases page always works.",
      "button.download": "Download {version}",
      "button.missing": "Not in this release",
      "button.all": "See all releases",
    },

    uk: {
      "document.title":
        "FileSight — локальний аналіз фото й відео, що пропонує зрозумілі назви файлів",
      "lang.label": "Мова",
      "features.label": "Що вона робить",

      "hero.tagline":
        "Ваші фото й відео отримують назви, які можна прочитати — і все це відбувається на вашому комп'ютері. На Windows інсталятор містить усе потрібне.",
      "hero.download": "Завантажити",
      "hero.source": "Код на GitHub",

      "feature.local.title": "Локально, без завантаження в мережу",
      "feature.local.body":
        "Vision-модель працює на вашій машині й описує кожен файл. Ніщо не покидає комп'ютер, тому приватні теки лишаються приватними.",
      "feature.confirm.title": "Нічого не перейменовується саме",
      "feature.confirm.body":
        "Ви бачите запропоновані назви, можете виправити будь-яку, перевірити й прогнати без змін. Файли змінюються лише після вашого підтвердження.",
      "feature.undo.title": "Будь-яке перейменування можна скасувати",
      "feature.undo.body":
        "Кожна операція записується в журнал, тому один клік відкочує останню партію — включно з обмінами назв, циклами і зміною лише регістру.",
      "feature.media.title": "Зображення й короткі відео",
      "feature.media.body":
        "JPEG, PNG і WebP, а також MP4, MOV, MKV, WebM та AVI: з відео беруться кадри, і найчіткіші з них описують файл.",
      "feature.setup.title": "На Windows нічого не налаштовувати",
      "feature.setup.body":
        "Ядро аналізу лежить усередині інсталятора. Ні Python, ні PATH, ні жодної команди — а FFmpeg для відео завантажується однією кнопкою в застосунку.",
      "feature.updates.title": "Оновлюється саме",
      "feature.updates.body":
        "Встановлена копія помічає новий реліз, показує банер і встановлює його. Кожне оновлення підписане, і приймаються лише підписані.",

      "downloads.title": "Завантаження",
      "downloads.all": "Усі релізи й контрольні суми на GitHub",
      "card.win.exe": "Інсталятор (.exe) · рекомендовано",
      "card.win.msi": "Пакет MSI · для розгортання",
      "card.mac.arm": "Apple Silicon (.dmg)",
      "card.mac.intel": "Intel (.dmg)",
      "card.linux.appimage": "AppImage",
      "card.linux.deb": "Debian / Ubuntu (.deb)",
      "badge.complete": "Усе всередині",
      "badge.needs": "Потрібен Python 3.11+",

      "requirements.title": "Встановити й працювати — більше нічого налаштовувати",
      "requirements.windows":
        "<strong>На Windows інсталятор самодостатній.</strong> Ядро аналізу лежить усередині, тому не треба ні ставити Python, ні правити PATH, ні виконувати команди. Завантажте, встановіть, виберіть теку. Перший аналіз один раз завантажує vision-модель (близько 1&nbsp;ГБ) і кешує її; далі все працює офлайн.",
      "requirements.ffmpeg":
        "Для відео потрібен FFmpeg, і це теж один клік: застосунок сам завантажить його у власну теку, не торкаючись більше нічого в системі.",
      "requirements.updates":
        "Автооновлення вбудоване — встановлена копія помічає новий реліз і пропонує його встановити.",
      "requirements.caveat":
        '<strong>Збірки для macOS і Linux ще не самодостатні.</strong> Їм досі потрібен <strong>Python 3.11+</strong> зі встановленим ядром FileSight — у <a href="https://github.com/SpiritUrban/file-sight" rel="noopener">README</a> є дві команди. Заморожування ядра під ці платформи — наступний крок. Крім того, macOS-збірки не підписані, тому перший запуск потребує правої кнопки → Open.',

      "footer.author":
        'Зроблено <a href="https://spiriturban.github.io/" rel="author noopener">Віталієм Дячуком</a> — інші проєкти та послуги на <a href="https://spiriturban.github.io/" rel="noopener">особистій сторінці</a>.',
      "footer.legal":
        'Ліцензія MIT. <a href="https://github.com/SpiritUrban/file-sight" rel="noopener">Код</a> · <a href="https://github.com/SpiritUrban/file-sight/issues" rel="noopener">Повідомити про проблему</a>',

      "version.loading": "Завантаження інформації про реліз…",
      "version.released": "Версія {version} · випущено {date}",
      "version.unpublished": "Версія {version} · ще не опублікована",
      "note.pick":
        "Виберіть пакет для своєї системи. Інсталятори збирає GitHub Actions із коду, позначеного тегом.",
      "note.noassets":
        "До цього релізу ще не додані інсталятори. На сторінці релізів GitHub є все, що опубліковано.",
      "note.norelease":
        "Жодного релізу ще не опубліковано. Підпишіться на репозиторій, щоб дізнатися про перший.",
      "note.failed":
        "Не вдалося завантажити інформацію про реліз ({error}). Сторінка релізів на GitHub працює завжди.",
      "button.download": "Завантажити {version}",
      "button.missing": "Немає в цьому релізі",
      "button.all": "Усі релізи",
    },
  };

  /** Locale tag used for dates and number formatting. */
  var LOCALES = { en: "en-GB", uk: "uk-UA" };

  var current = "en";
  var listeners = [];

  function readStored() {
    try {
      var value = window.localStorage.getItem(STORAGE_KEY);
      return SUPPORTED.indexOf(value) !== -1 ? value : null;
    } catch (error) {
      // Storage can be blocked entirely (private mode, cookie settings). A
      // language switch must not be what breaks the page.
      return null;
    }
  }

  function store(lang) {
    try {
      window.localStorage.setItem(STORAGE_KEY, lang);
    } catch (error) {
      /* nothing to do: the choice simply will not persist */
    }
  }

  function detect() {
    var stored = readStored();
    if (stored) return stored;

    var tags = [];
    if (navigator.languages && navigator.languages.length) {
      tags = Array.prototype.slice.call(navigator.languages);
    } else if (navigator.language) {
      tags = [navigator.language];
    }
    for (var i = 0; i < tags.length; i += 1) {
      if (String(tags[i]).toLowerCase().indexOf("uk") === 0) return "uk";
    }
    return "en";
  }

  /** Look up a key, falling back to English and then to the key itself. */
  function t(key, values) {
    var table = STRINGS[current] || STRINGS.en;
    var text = table[key];
    if (text === undefined) text = STRINGS.en[key];
    if (text === undefined) return key;
    if (!values) return text;
    return text.replace(/\{(\w+)\}/g, function (whole, name) {
      return Object.prototype.hasOwnProperty.call(values, name)
        ? String(values[name])
        : whole;
    });
  }

  function apply(lang) {
    current = SUPPORTED.indexOf(lang) !== -1 ? lang : "en";
    document.documentElement.lang = current;
    document.title = t("document.title");

    // Plain text nodes.
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i += 1) {
      nodes[i].textContent = t(nodes[i].getAttribute("data-i18n"));
    }
    // Fragments that contain links or emphasis. Every value is a literal in
    // this file -- no visitor input ever reaches here.
    var rich = document.querySelectorAll("[data-i18n-html]");
    for (var j = 0; j < rich.length; j += 1) {
      rich[j].innerHTML = t(rich[j].getAttribute("data-i18n-html"));
    }

    // Labels a screen reader announces but nobody sees. Left untranslated
    // they are the one part of the page that stays in the wrong language for
    // exactly the visitors who cannot notice and correct for it.
    var labelled = document.querySelectorAll("[data-i18n-aria]");
    for (var m = 0; m < labelled.length; m += 1) {
      labelled[m].setAttribute(
        "aria-label",
        t(labelled[m].getAttribute("data-i18n-aria")),
      );
    }

    var buttons = document.querySelectorAll("[data-lang]");
    for (var k = 0; k < buttons.length; k += 1) {
      var isCurrent = buttons[k].getAttribute("data-lang") === current;
      buttons[k].setAttribute("aria-pressed", isCurrent ? "true" : "false");
      buttons[k].classList.toggle("langbar__button--active", isCurrent);
    }

    for (var n = 0; n < listeners.length; n += 1) listeners[n](current);
  }

  function select(lang) {
    store(lang);
    apply(lang);
  }

  function init() {
    var buttons = document.querySelectorAll("[data-lang]");
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener("click", function (event) {
        select(event.currentTarget.getAttribute("data-lang"));
      });
    }
    var lang = detect();
    // Remember the detected language too, not just a clicked one, so the
    // answer is stable from the second visit onwards.
    if (!readStored()) store(lang);
    apply(lang);
  }

  return {
    init: init,
    apply: apply,
    select: select,
    t: t,
    language: function () {
      return current;
    },
    locale: function () {
      return LOCALES[current] || "en-GB";
    },
    /** Register a callback to re-render script-generated text. */
    onChange: function (callback) {
      listeners.push(callback);
    },
  };
})();

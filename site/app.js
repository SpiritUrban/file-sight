/* Fill the download cards from the generated manifest.
 *
 * The manifest is written by scripts/generate-download-manifest.mjs during the
 * Pages deploy, straight from the GitHub release. Nothing here knows a file
 * name or a version: both are wrong the moment a release is cut (rules 15,18).
 *
 * If the manifest is missing or has no assets, every card falls back to the
 * releases page. A guessed file name would be a 404, which is worse than an
 * extra click.
 *
 * Every string the script produces goes through FileSightI18n, and the last
 * manifest is kept so a language change can repaint without refetching. */

(function () {
  "use strict";

  var RELEASES_URL = "https://github.com/SpiritUrban/file-sight/releases";
  var i18n = window.FileSightI18n;

  /** The last manifest (or the failure that replaced it). */
  var state = { manifest: null, error: null };

  function t(key, values) {
    return i18n ? i18n.t(key, values) : key;
  }

  function humanSize(bytes) {
    if (!bytes || bytes < 1024) return "";
    var mb = bytes / (1024 * 1024);
    return mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.round(mb) + " MB";
  }

  function formatDate(iso) {
    if (!iso) return null;
    var when = new Date(iso);
    if (isNaN(when.getTime())) return null;
    try {
      // An explicit locale, not the browser's: a visitor reading the
      // Ukrainian page got "30 июля 2026 г." because the OS locale decided.
      return when.toLocaleDateString(i18n ? i18n.locale() : "en-GB", {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch (error) {
      return when.toISOString().slice(0, 10);
    }
  }

  function setNote(text) {
    var note = document.getElementById("release-note");
    if (note) note.textContent = text;
  }

  function setVersionLine(text) {
    var line = document.getElementById("version-line");
    if (line) line.textContent = text;
  }

  /* A card matches an asset on all three of platform, architecture and file
     suffix. Two of the three are not enough: Windows publishes an .exe and an
     .msi with the same platform and architecture, so an "MSI" card matching on
     two keys would happily link to the installer. */
  function matches(asset, card) {
    return (
      asset.platform === card.dataset.platform &&
      asset.architecture === card.dataset.arch &&
      asset.extension === card.dataset.ext
    );
  }

  function renderFallback(noteKey, values) {
    var links = document.querySelectorAll("[data-download]");
    for (var i = 0; i < links.length; i += 1) {
      links[i].textContent = t("button.all");
      links[i].href = RELEASES_URL;
    }
    var cards = document.querySelectorAll(".card");
    for (var j = 0; j < cards.length; j += 1) {
      cards[j].classList.add("card--unavailable");
      var meta = cards[j].querySelector("[data-meta]");
      if (meta) meta.textContent = "";
    }
    setNote(t(noteKey, values));
  }

  function render() {
    if (state.error) {
      setVersionLine("");
      renderFallback("note.failed", { error: state.error });
      return;
    }

    var manifest = state.manifest;
    if (!manifest) {
      setVersionLine(t("version.loading"));
      return;
    }

    var date = formatDate(manifest.publishedAt);
    setVersionLine(
      manifest.hasRelease && date
        ? t("version.released", { version: manifest.version, date: date })
        : t("version.unpublished", { version: manifest.version }),
    );

    if (!manifest.assets || manifest.assets.length === 0) {
      renderFallback(manifest.hasRelease ? "note.noassets" : "note.norelease");
      return;
    }

    setNote(t("note.pick"));

    var cards = document.querySelectorAll(".card");
    for (var i = 0; i < cards.length; i += 1) {
      var card = cards[i];
      var link = card.querySelector("[data-download]");
      var meta = card.querySelector("[data-meta]");
      var found = null;
      for (var j = 0; j < manifest.assets.length; j += 1) {
        if (matches(manifest.assets[j], card)) {
          found = manifest.assets[j];
          break;
        }
      }

      if (!found) {
        card.classList.add("card--unavailable");
        link.textContent = t("button.missing");
        link.href = manifest.releaseUrl || RELEASES_URL;
        if (meta) meta.textContent = "";
        continue;
      }

      card.classList.remove("card--unavailable");
      link.textContent = t("button.download", { version: manifest.version });
      link.href = found.downloadUrl;
      if (meta) {
        var size = humanSize(found.size);
        meta.textContent = found.fileName + (size ? " · " + size : "");
      }
    }
  }

  if (i18n) {
    i18n.init();
    // Repaint the generated text too, not just the markup.
    i18n.onChange(render);
  }
  render();

  /* Relative URL on purpose: the site is served from a Pages subdirectory,
     and a leading slash would look in the domain root. */
  fetch("./download-manifest.json", { cache: "no-cache" })
    .then(function (response) {
      if (!response.ok) throw new Error("manifest HTTP " + response.status);
      return response.json();
    })
    .then(function (manifest) {
      state.manifest = manifest;
      state.error = null;
      render();
    })
    .catch(function (error) {
      state.error = error.message;
      render();
    });
})();

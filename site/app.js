/* Fill the download cards from the generated manifest.
 *
 * The manifest is written by scripts/generate-download-manifest.mjs during the
 * Pages deploy, straight from the GitHub release. Nothing here knows a file
 * name or a version: both are wrong the moment a release is cut (rules 15,18).
 *
 * If the manifest is missing or has no assets, every card falls back to the
 * releases page. A guessed file name would be a 404, which is worse than an
 * extra click. */

(function () {
  "use strict";

  var RELEASES_URL = "https://github.com/SpiritUrban/file-sight/releases";

  function humanSize(bytes) {
    if (!bytes || bytes < 1024) return "";
    var mb = bytes / (1024 * 1024);
    return mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.round(mb) + " MB";
  }

  function fallback(message) {
    document.querySelectorAll("[data-download]").forEach(function (link) {
      link.textContent = "See all releases";
      link.href = RELEASES_URL;
    });
    document.querySelectorAll(".card").forEach(function (card) {
      card.classList.add("card--unavailable");
    });
    var note = document.getElementById("release-note");
    if (note) note.textContent = message;
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

  function render(manifest) {
    var versionLine = document.getElementById("version-line");
    var note = document.getElementById("release-note");

    if (versionLine) {
      if (manifest.hasRelease) {
        var when = manifest.publishedAt
          ? new Date(manifest.publishedAt).toLocaleDateString(undefined, {
              year: "numeric",
              month: "long",
              day: "numeric",
            })
          : null;
        versionLine.textContent =
          "Version " + manifest.version + (when ? " · released " + when : "");
      } else {
        versionLine.textContent =
          "Version " + manifest.version + " · not published yet";
      }
    }

    if (!manifest.assets || manifest.assets.length === 0) {
      fallback(
        manifest.hasRelease
          ? "This release has no installers attached yet. The GitHub releases page has everything that is published."
          : "No release is published yet. Watch the repository to hear about the first one.",
      );
      return;
    }

    if (note) {
      note.textContent =
        "Pick the package for your system. Installers are built by GitHub Actions from the tagged source.";
    }

    document.querySelectorAll(".card").forEach(function (card) {
      var link = card.querySelector("[data-download]");
      var meta = card.querySelector("[data-meta]");
      var found = null;
      for (var i = 0; i < manifest.assets.length; i += 1) {
        if (matches(manifest.assets[i], card)) {
          found = manifest.assets[i];
          break;
        }
      }

      if (!found) {
        card.classList.add("card--unavailable");
        link.textContent = "Not in this release";
        link.href = manifest.releaseUrl || RELEASES_URL;
        if (meta) meta.textContent = "";
        return;
      }

      link.textContent = "Download " + manifest.version;
      link.href = found.downloadUrl;
      if (meta) {
        var size = humanSize(found.size);
        meta.textContent = found.fileName + (size ? " · " + size : "");
      }
    });
  }

  /* Relative URL on purpose: the site is served from a Pages subdirectory,
     and a leading slash would look in the domain root. */
  fetch("./download-manifest.json", { cache: "no-cache" })
    .then(function (response) {
      if (!response.ok) throw new Error("manifest HTTP " + response.status);
      return response.json();
    })
    .then(render)
    .catch(function (error) {
      fallback(
        "Release information could not be loaded (" +
          error.message +
          "). The GitHub releases page always works.",
      );
    });
})();

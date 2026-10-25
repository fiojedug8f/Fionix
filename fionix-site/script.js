/* ==========================================================================
   Fionix — landing page interactions
   Vanilla JS: GitHub release metadata, header, mobile menu, reveal, spotlight,
   tilt, gallery lightbox.
   ========================================================================== */
(() => {
  "use strict";

  document.documentElement.classList.add("js");

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");

  /* -----------------------------------------------------------------------
     Latest GitHub release: displayed version + direct installer URL
     -----------------------------------------------------------------------
     GitHub Pages is static, so there is no build step to update the version.
     The public GitHub API is fetched at runtime. If it is unavailable or
     rate-limited, the HTML keeps working with the latest/download fallback. */
  const RELEASE = {
    owner: "fiojedug8f",
    repo: "Fionix",
    assetName: "Fionix_Setup.exe",
    apiUrl: "https://api.github.com/repos/fiojedug8f/Fionix/releases/latest",
    fallbackUrl:
      "https://github.com/fiojedug8f/Fionix/releases/latest/download/Fionix_Setup.exe",
  };

  const RELEASE_CACHE_KEY = "fionix:latest-release:v1";
  // Short cache keeps repeat loads cheap while picking up a new release quickly.
  const RELEASE_CACHE_TTL = 60 * 1000;

  const releaseTagNodes = document.querySelectorAll("[data-release-tag]");
  const releaseVersionNodes = document.querySelectorAll("[data-release-version]");
  const downloadLinks = document.querySelectorAll("[data-download]");

  const getDisplayTag = (tag) => {
    const value = String(tag || "").trim();
    if (!value) return "";
    return /^v/i.test(value) ? value : `v${value}`;
  };

  const getPlainVersion = (tag) => String(tag || "").trim().replace(/^v/i, "");

  const applyRelease = (release) => {
    if (!release?.tag) return;

    const displayTag = getDisplayTag(release.tag);
    const version = getPlainVersion(release.tag);

    releaseTagNodes.forEach((node) => {
      node.textContent = displayTag;
    });

    releaseVersionNodes.forEach((node) => {
      node.textContent = version;
    });

    if (release.downloadUrl) {
      downloadLinks.forEach((link) => {
        link.href = release.downloadUrl;
      });
    }

    document.documentElement.dataset.fionixVersion = version;
  };

  const readCachedRelease = () => {
    try {
      const raw = window.sessionStorage.getItem(RELEASE_CACHE_KEY);
      if (!raw) return null;

      const cached = JSON.parse(raw);
      if (!cached?.tag || !cached?.savedAt) return null;
      if (Date.now() - cached.savedAt > RELEASE_CACHE_TTL) return null;

      return cached;
    } catch {
      return null;
    }
  };

  const cacheRelease = (release) => {
    try {
      window.sessionStorage.setItem(
        RELEASE_CACHE_KEY,
        JSON.stringify({ ...release, savedAt: Date.now() })
      );
    } catch {
      // Private mode / blocked storage: the page still gets the live data.
    }
  };

  const fetchLatestRelease = async () => {
    if (!window.fetch) return;

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);

    try {
      const response = await window.fetch(RELEASE.apiUrl, {
        cache: "no-store",
        credentials: "omit",
        headers: { Accept: "application/vnd.github+json" },
        signal: controller.signal,
      });

      if (!response.ok) return;

      const data = await response.json();
      if (!data?.tag_name) return;

      const assets = Array.isArray(data.assets) ? data.assets : [];
      const installer =
        assets.find(
          (asset) =>
            String(asset.name).toLowerCase() === RELEASE.assetName.toLowerCase()
        ) || assets.find((asset) => /\.exe$/i.test(String(asset.name)));

      // Prefer the URL GitHub returns for the asset. If the release has no
      // installer asset, build the same versioned URL from the tag.
      const directUrl =
        installer?.browser_download_url ||
        `https://github.com/${RELEASE.owner}/${RELEASE.repo}/releases/download/${encodeURIComponent(data.tag_name)}/${RELEASE.assetName}`;

      const release = { tag: data.tag_name, downloadUrl: directUrl };
      applyRelease(release);
      cacheRelease(release);
    } catch {
      // Network error, timeout or API rate limit: use the latest/download
      // redirect, which still downloads the newest installer.
      downloadLinks.forEach((link) => {
        link.href = RELEASE.fallbackUrl;
      });
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const cachedRelease = readCachedRelease();
  if (cachedRelease) {
    applyRelease(cachedRelease);
  } else {
    fetchLatestRelease();
  }

  /* -----------------------------------------------------------------------
     Header: compact state after scrolling
     ----------------------------------------------------------------------- */
  const header = document.getElementById("siteHeader");

  const updateHeader = () => {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 14);
  };

  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  /* -----------------------------------------------------------------------
     Mobile menu
     ----------------------------------------------------------------------- */
  const menuToggle = document.getElementById("menuToggle");
  const mobileMenu = document.getElementById("mobileMenu");
  const menuBackdrop = document.getElementById("menuBackdrop");
  const pageRegions = [
    header,
    document.getElementById("main"),
    document.querySelector(".site-footer"),
  ].filter(Boolean);

  const setMenu = (open, restoreFocus = false) => {
    if (!menuToggle || !mobileMenu) return;

    menuToggle.classList.toggle("is-open", open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Закрыть меню" : "Открыть меню");

    mobileMenu.classList.toggle("is-open", open);
    mobileMenu.setAttribute("aria-hidden", String(!open));
    menuBackdrop?.classList.toggle("is-open", open);

    if (open) {
      mobileMenu.removeAttribute("inert");
    } else {
      mobileMenu.setAttribute("inert", "");
      if (restoreFocus) menuToggle.focus();
    }
  };

  if (menuToggle && mobileMenu) {
    menuToggle.addEventListener("click", () => {
      setMenu(!mobileMenu.classList.contains("is-open"));
    });

    mobileMenu.querySelectorAll("a").forEach((link) => {
      // Let the browser follow the anchor first, then collapse the menu.
      link.addEventListener("click", () => window.setTimeout(() => setMenu(false), 0));
    });

    menuBackdrop?.addEventListener("click", () => setMenu(false));

    // The full-screen backdrop closes the menu on click. We deliberately
    // don't close on pointerdown: removing the backdrop mid-gesture could
    // let the subsequent click fall through to the page underneath.
    window.addEventListener("resize", () => {
      if (window.innerWidth > 1180 && mobileMenu.classList.contains("is-open")) {
        setMenu(false);
      }
    });
  }

  /* -----------------------------------------------------------------------
     Scroll reveal
     ----------------------------------------------------------------------- */
  const revealItems = Array.from(document.querySelectorAll("[data-reveal]"));

  if (reduceMotion.matches || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  } else {
    const revealObserver = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );

    revealItems.forEach((item) => revealObserver.observe(item));
  }

  /* -----------------------------------------------------------------------
     Pointer spotlight on bento cards
     ----------------------------------------------------------------------- */
  if (finePointer.matches && !reduceMotion.matches) {
    document.querySelectorAll(".feature-card").forEach((card) => {
      card.addEventListener(
        "pointermove",
        (event) => {
          const rect = card.getBoundingClientRect();
          const x = ((event.clientX - rect.left) / rect.width) * 100;
          const y = ((event.clientY - rect.top) / rect.height) * 100;
          card.style.setProperty("--mx", `${x.toFixed(1)}%`);
          card.style.setProperty("--my", `${y.toFixed(1)}%`);
        },
        { passive: true }
      );

      card.addEventListener("pointerleave", () => {
        card.style.setProperty("--mx", "50%");
        card.style.setProperty("--my", "0%");
      });
    });
  }

  /* -----------------------------------------------------------------------
     Subtle 3D tilt on the hero screenshot
     ----------------------------------------------------------------------- */
  const preview = document.querySelector(".app-preview");

  if (preview && finePointer.matches && !reduceMotion.matches) {
    preview.addEventListener(
      "pointermove",
      (event) => {
        const rect = preview.getBoundingClientRect();
        const px = (event.clientX - rect.left) / rect.width;
        const py = (event.clientY - rect.top) / rect.height;
        const rotateX = (0.5 - py) * 4 + 1.5;
        const rotateY = (px - 0.5) * 6 - 4;
        preview.style.setProperty("--rx", `${rotateX.toFixed(2)}deg`);
        preview.style.setProperty("--ry", `${rotateY.toFixed(2)}deg`);
      },
      { passive: true }
    );

    preview.addEventListener("pointerleave", () => {
      preview.style.setProperty("--rx", "1.5deg");
      preview.style.setProperty("--ry", "-4deg");
    });
  }

  /* -----------------------------------------------------------------------
     Accent colour demo (the same idea as the launcher's accent setting)
     ----------------------------------------------------------------------- */
  const accents = {
    violet: {
      accent: "#8b5cf6",
      rgb: "139, 92, 246",
      second: "#22d3ee",
      secondRgb: "34, 211, 238",
      label: "Fionix Violet",
    },
    blue: {
      accent: "#4f8cff",
      rgb: "79, 140, 255",
      second: "#22d3ee",
      secondRgb: "34, 211, 238",
      label: "Fionix Blue",
    },
    cyan: {
      accent: "#22d3ee",
      rgb: "34, 211, 238",
      second: "#8b5cf6",
      secondRgb: "139, 92, 246",
      label: "Fionix Cyan",
    },
  };

  const swatches = Array.from(document.querySelectorAll("[data-accent]"));
  const swatchLabel = document.getElementById("swatchLabel");
  const root = document.documentElement;

  const applyAccent = (name) => {
    const accent = accents[name];
    if (!accent) return;

    root.style.setProperty("--accent", accent.accent);
    root.style.setProperty("--accent-rgb", accent.rgb);
    root.style.setProperty("--accent-2", accent.second);
    root.style.setProperty("--accent-2-rgb", accent.secondRgb);
    root.style.setProperty("--accent-soft", `rgba(${accent.rgb}, 0.14)`);
    root.style.setProperty("--accent-glow", `rgba(${accent.rgb}, 0.34)`);

    swatches.forEach((swatch) => {
      const active = swatch.dataset.accent === name;
      swatch.classList.toggle("is-active", active);
      swatch.setAttribute("aria-pressed", String(active));
    });

    if (swatchLabel) swatchLabel.textContent = accent.label;
  };

  swatches.forEach((swatch) => {
    swatch.addEventListener("click", () => applyAccent(swatch.dataset.accent));
  });

  /* -----------------------------------------------------------------------
     Active navigation link
     ----------------------------------------------------------------------- */
  const navLinks = Array.from(document.querySelectorAll(".nav-link"));
  const observedSections = ["features", "screenshots", "download"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);

  const setActiveNav = (id) => {
    // Do not highlight a section while the hero is still on screen.
    const effectiveId = window.scrollY < 260 ? "" : id;

    navLinks.forEach((link) => {
      const active = link.getAttribute("href") === `#${effectiveId}`;
      link.classList.toggle("is-active", active);
      if (active) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  };

  if ("IntersectionObserver" in window && observedSections.length) {
    const navObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActiveNav(entry.target.id);
        });
      },
      { rootMargin: "-42% 0px -50% 0px", threshold: 0 }
    );

    observedSections.forEach((section) => navObserver.observe(section));

    // Above the first content section no nav item should stay highlighted.
    window.addEventListener(
      "scroll",
      () => {
        if (window.scrollY < 260) {
          navLinks.forEach((link) => {
            link.classList.remove("is-active");
            link.removeAttribute("aria-current");
          });
        }
      },
      { passive: true }
    );
  }

  /* -----------------------------------------------------------------------
     Gallery lightbox
     ----------------------------------------------------------------------- */
  const galleryCards = Array.from(document.querySelectorAll(".gallery-card[data-full]"));
  const lightbox = document.getElementById("lightbox");
  const lightboxImage = document.getElementById("lightboxImage");
  const lightboxTitle = document.getElementById("lightboxTitle");
  const lightboxDescription = document.getElementById("lightboxDescription");
  const lightboxIndex = document.getElementById("lightboxIndex");
  const lightboxTotal = document.getElementById("lightboxTotal");
  const lightboxClose = lightbox?.querySelector(".lightbox__top .icon-button");
  const lightboxDialog = lightbox?.querySelector(".lightbox__dialog");

  let currentSlide = 0;
  let lastFocusedElement = null;
  let touchStart = null;
  let toastTimer = 0;

  const pad = (number) => String(number).padStart(2, "0");

  const preloadSlide = (index) => {
    const card = galleryCards[index];
    if (!card) return;
    const image = new Image();
    image.src = card.dataset.full;
  };

  const renderSlide = (index) => {
    if (!galleryCards.length || !lightboxImage) return;

    currentSlide = (index + galleryCards.length) % galleryCards.length;
    const card = galleryCards[currentSlide];
    const title = card.dataset.title || "Fionix";
    const description = card.dataset.caption || "";

    lightboxImage.src = card.dataset.full;
    lightboxImage.alt = `${title}. ${description}`;
    if (lightboxTitle) lightboxTitle.textContent = title;
    if (lightboxDescription) lightboxDescription.textContent = description;
    if (lightboxIndex) lightboxIndex.textContent = pad(currentSlide + 1);
    if (lightboxTotal) lightboxTotal.textContent = pad(galleryCards.length);

    preloadSlide((currentSlide + 1) % galleryCards.length);
    preloadSlide((currentSlide - 1 + galleryCards.length) % galleryCards.length);
  };

  const openLightbox = (index) => {
    if (!lightbox) return;
    if (mobileMenu?.classList.contains("is-open")) setMenu(false);

    lastFocusedElement = document.activeElement;
    renderSlide(index);

    lightbox.classList.add("is-open");
    lightbox.removeAttribute("inert");
    lightbox.setAttribute("aria-hidden", "false");
    pageRegions.forEach((region) => region.setAttribute("inert", ""));
    document.body.classList.add("is-locked");

    window.setTimeout(() => lightboxClose?.focus({ preventScroll: true }), 60);
  };

  const closeLightbox = () => {
    if (!lightbox || !lightbox.classList.contains("is-open")) return;

    lightbox.classList.remove("is-open");
    pageRegions.forEach((region) => region.removeAttribute("inert"));
    document.body.classList.remove("is-locked");

    if (lastFocusedElement instanceof HTMLElement) {
      lastFocusedElement.focus();
    }

    lightbox.setAttribute("aria-hidden", "true");
    lightbox.setAttribute("inert", "");
  };

  const moveSlide = (direction) => {
    if (!lightbox?.classList.contains("is-open")) return;
    renderSlide(currentSlide + direction);
  };

  if (!reduceMotion.matches && galleryCards.length > 0) {
    preloadSlide(0);
  }

  galleryCards.forEach((card, index) => {
    card.addEventListener("click", () => openLightbox(index));
  });

  lightbox?.querySelectorAll("[data-lightbox-close]").forEach((control) => {
    control.addEventListener("click", closeLightbox);
  });

  lightbox?.querySelector("[data-lightbox-prev]")?.addEventListener("click", () => moveSlide(-1));
  lightbox?.querySelector("[data-lightbox-next]")?.addEventListener("click", () => moveSlide(1));

  document.addEventListener("keydown", (event) => {
    if (mobileMenu?.classList.contains("is-open") && event.key === "Escape") {
      event.preventDefault();
      setMenu(false, true);
      return;
    }

    if (!lightbox?.classList.contains("is-open")) return;

    if (event.key === "Escape") {
      event.preventDefault();
      closeLightbox();
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveSlide(-1);
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveSlide(1);
      return;
    }

    if (event.key === "Tab" && lightboxDialog) {
      const focusable = Array.from(
        lightboxDialog.querySelectorAll(
          'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => element.getClientRects().length > 0);

      if (!focusable.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  // Swipe through screenshots on touch devices.
  lightbox?.addEventListener(
    "pointerdown",
    (event) => {
      if (event.pointerType !== "touch") return;
      touchStart = { x: event.clientX, y: event.clientY };
    },
    { passive: true }
  );

  lightbox?.addEventListener(
    "pointerup",
    (event) => {
      if (!touchStart || event.pointerType !== "touch") return;

      const deltaX = event.clientX - touchStart.x;
      const deltaY = event.clientY - touchStart.y;
      touchStart = null;

      if (Math.abs(deltaX) > 45 && Math.abs(deltaX) > Math.abs(deltaY)) {
        moveSlide(deltaX < 0 ? 1 : -1);
      }
    },
    { passive: true }
  );

  /* -----------------------------------------------------------------------
     Placeholder social link -> toast
     ----------------------------------------------------------------------- */
  const toast = document.getElementById("toast");

  const showToast = (message) => {
    if (!toast) return;
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 4200);
  };

  document.querySelectorAll("[data-placeholder-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const network = link.dataset.placeholderLink || "Сообщество";
      showToast(`${network}-сообщество Fionix скоро появится. Ссылка уже готовится.`);
    });
  });

  /* -----------------------------------------------------------------------
     Footer year
     ----------------------------------------------------------------------- */
  const year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());
})();

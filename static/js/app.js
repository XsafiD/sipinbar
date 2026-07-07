/*
 * static/js/app.js — JavaScript client-side untuk SIPINBAR.
 *
 * Berisi:
 *   1. Sidebar toggle (mobile hamburger) — T-FE-03, Q-08 handoff
 *   2. Modal trigger & close — T-FE-03, Q-09 handoff
 *   3. Alert dismiss — T-FE-10
 *   4. Konfirmasi hapus (link ke modal) — T-FE-03
 *   5. Dynamic form (tambah barang di form pengajuan peminjaman) — T-FE-03
 *   6. Print button (untuk laporan) — Q-13 handoff
 *
 * Pattern: vanilla JS, tanpa framework. Event delegation via data-* attributes.
 * Refs: TODO T-FE-03, handoff-frontend Q-08 & Q-09, design-system §1
 */
(function () {
  "use strict";

  // ── 1. SIDEBAR TOGGLE (mobile) ──────────────────────────────
  // Pattern: sidebar punya id="sidebar" dengan class -translate-x-full (hidden).
  // Tombol [data-sidebar-toggle] → toggle class.
  // Overlay [data-sidebar-overlay] → klik untuk tutup.
  function initSidebarToggle() {
    var sidebar = document.getElementById("sidebar");
    var overlay = document.getElementById("sidebar-overlay");
    if (!sidebar) return;

    function openSidebar() {
      sidebar.classList.remove("-translate-x-full");
      sidebar.classList.add("translate-x-0", "is-open");
      if (overlay) {
        overlay.classList.remove("hidden");
        overlay.classList.add("is-visible");
      }
    }

    function closeSidebar() {
      sidebar.classList.add("-translate-x-full");
      sidebar.classList.remove("translate-x-0", "is-open");
      if (overlay) {
        overlay.classList.remove("is-visible");
        // Delay hide agar animasi selesai
        setTimeout(function () {
          overlay.classList.add("hidden");
        }, 200);
      }
    }

    // Toggle via hamburger
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (sidebar.classList.contains("is-open")) {
          closeSidebar();
        } else {
          openSidebar();
        }
      });
    });

    // Klik overlay → tutup
    if (overlay) {
      overlay.addEventListener("click", closeSidebar);
    }
  }

  // ── 2. MODAL TRIGGER & CLOSE ────────────────────────────────
  // Pattern:
  //   Trigger: <button data-modal-target="<id>"> → buka modal #<id>
  //   Close:   <button data-modal-close> atau klik [data-modal-overlay]
  //   Esc key: tutup modal aktif
  function initModal() {
    function openModal(modal) {
      modal.classList.remove("hidden");
      modal.classList.add("is-open");
      // Lock body scroll
      document.body.style.overflow = "hidden";
    }

    function closeModal(modal) {
      modal.classList.remove("is-open");
      // Delay hide agar animasi scale selesai
      setTimeout(function () {
        modal.classList.add("hidden");
      }, 200);
      // Unlock body scroll jika tidak ada modal lain terbuka
      var anyOpen = document.querySelector("[data-modal].is-open");
      if (!anyOpen) {
        document.body.style.overflow = "";
      }
    }

    // Trigger buka
    document.querySelectorAll("[data-modal-target]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var targetId = btn.getAttribute("data-modal-target");
        var modal = document.getElementById(targetId);
        if (modal) openModal(modal);
      });
    });

    // Trigger tutup (tombol close & klik overlay)
    document.querySelectorAll("[data-modal]").forEach(function (modal) {
      modal.querySelectorAll("[data-modal-close]").forEach(function (closeBtn) {
        closeBtn.addEventListener("click", function () {
          closeModal(modal);
        });
      });
      var overlay = modal.querySelector("[data-modal-overlay]");
      if (overlay) {
        overlay.addEventListener("click", function (e) {
          if (e.target === overlay) closeModal(modal);
        });
      }
    });

    // Esc key tutup modal & sidebar
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        // Tutup modal aktif
        var openModalEl = document.querySelector("[data-modal].is-open");
        if (openModalEl) {
          closeModal(openModalEl);
          return;
        }
        // Tutup sidebar mobile
        var sidebar = document.getElementById("sidebar");
        if (sidebar && sidebar.classList.contains("is-open")) {
          sidebar.classList.add("-translate-x-full");
          sidebar.classList.remove("translate-x-0", "is-open");
          var overlay = document.getElementById("sidebar-overlay");
          if (overlay) {
            overlay.classList.remove("is-visible");
            setTimeout(function () {
              overlay.classList.add("hidden");
            }, 200);
          }
        }
      }
    });
  }

  // ── 3. ALERT DISMISS ────────────────────────────────────────
  // Tombol [data-dismiss-alert] → sembunyikan alert parent.
  function initAlertDismiss() {
    document.querySelectorAll("[data-dismiss-alert]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var alert = btn.closest("[data-alert]");
        if (alert) {
          alert.style.transition = "opacity 0.2s, transform 0.2s";
          alert.style.opacity = "0";
          alert.style.transform = "translateY(-8px)";
          setTimeout(function () {
            alert.remove();
          }, 200);
        }
      });
    });
  }

  // ── 4. DYNAMIC FORM (tambah baris barang di pengajuan peminjaman) ─
  // Pattern: container [data-dynamic-form-list] berisi baris-baris.
  // Tombol [data-dynamic-form-add] → kloning template [data-dynamic-form-template].
  // Tombol [data-dynamic-form-remove] di tiap baris → hapus baris.
  function initDynamicForm() {
    var addBtn = document.querySelector("[data-dynamic-form-add]");
    if (!addBtn) return;

    addBtn.addEventListener("click", function () {
      var template = document.querySelector("[data-dynamic-form-template]");
      var list = document.querySelector("[data-dynamic-form-list]");
      if (!template || !list) return;

      var clone = template.content
        ? template.content.cloneNode(true)
        : template.cloneNode(true);
      // Update index unik untuk name attribute
      var index = list.children.length;
      clone.querySelectorAll("[name]").forEach(function (input) {
        var name = input.getAttribute("name");
        input.setAttribute("name", name.replace("__index__", index));
      });
      list.appendChild(clone);

      // Bind remove button pada baris baru
      bindRemoveButton(list.lastElementChild);
    });

    function bindRemoveButton(row) {
      if (!row) return;
      var removeBtn = row.querySelector("[data-dynamic-form-remove]");
      if (removeBtn) {
        removeBtn.addEventListener("click", function () {
          row.remove();
        });
      }
    }

    // Bind semua remove button yang sudah ada
    document
      .querySelectorAll("[data-dynamic-form-list] > *")
      .forEach(bindRemoveButton);
  }

  // ── 5. PRINT BUTTON (untuk laporan) ─────────────────────────
  // Tombol [data-print] → window.print()
  function initPrintButton() {
    document.querySelectorAll("[data-print]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        window.print();
      });
    });
  }

  // ── 6. AUTO-HIDE FLASH MESSAGE (opsional, 5 detik) ──────────
  function initAutoHideAlert() {
    document.querySelectorAll("[data-alert]:not([data-alert-persistent])")
      .forEach(function (alert) {
        setTimeout(function () {
          if (alert && alert.parentNode) {
            alert.style.transition = "opacity 0.3s, transform 0.3s";
            alert.style.opacity = "0";
            alert.style.transform = "translateY(-8px)";
            setTimeout(function () {
              if (alert.parentNode) alert.remove();
            }, 300);
          }
        }, 5000);
      });
  }

  // ── INIT SEMUA SAAT DOM READY ───────────────────────────────
  function init() {
    initSidebarToggle();
    initModal();
    initAlertDismiss();
    initDynamicForm();
    initPrintButton();
    initAutoHideAlert();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

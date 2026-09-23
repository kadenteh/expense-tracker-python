(function () {
  "use strict";

  // ---- Flash messages: auto-dismiss ----
  document.querySelectorAll(".flash").forEach(function (el, i) {
    window.setTimeout(function () {
      el.classList.add("is-dismissed");
      window.setTimeout(function () {
        el.remove();
      }, 220);
    }, 3200 + i * 120);
  });

  // ---- Filter form: auto-submit on select/date change ----
  document.querySelectorAll("[data-auto-submit]").forEach(function (el) {
    el.addEventListener("change", function () {
      el.closest("form").submit();
    });
  });

  // ---- Inline delete confirmation ----
  document.addEventListener("click", function (e) {
    const confirmBtn = e.target.closest('[data-action="confirm-delete"]');
    const cancelBtn = e.target.closest('[data-action="cancel-delete"]');

    if (confirmBtn) {
      const wrap = confirmBtn.closest(".row-actions-wrap");
      if (wrap) {
        wrap.querySelector(".row-actions-default").style.display = "none";
        wrap.querySelector('[data-role="confirm"]').classList.add("is-open");
      }
    }

    if (cancelBtn) {
      const wrap = cancelBtn.closest(".row-actions-wrap");
      if (wrap) {
        wrap.querySelector(".row-actions-default").style.display = "";
        wrap.querySelector('[data-role="confirm"]').classList.remove("is-open");
      }
    }
  });

  // ---- Donut chart hover / focus ----
  const donutTotalValue = document.getElementById("donut-center-value");
  const donutTotalLabel = document.getElementById("donut-center-label");
  const donutTotalPercent = document.getElementById("donut-center-percent");
  const donutSegments = document.querySelectorAll(".donut-segment");
  const legendRows = document.querySelectorAll(".legend-row");

  if (donutTotalValue && donutSegments.length) {
    const baseTotal = donutTotalValue.textContent;
    const baseLabel = donutTotalLabel.textContent;

    function activate(category) {
      const seg = Array.from(donutSegments).find((s) => s.dataset.category === category);
      donutSegments.forEach((s) => s.setAttribute("stroke-width", s === seg ? "32" : "28"));
      legendRows.forEach((row) => row.classList.toggle("is-active", row.dataset.category === category));
      if (seg) {
        donutTotalLabel.textContent = category;
        donutTotalValue.textContent = seg.dataset.amount;
        donutTotalPercent.textContent = seg.dataset.percent + "%";
      }
    }

    function reset() {
      donutSegments.forEach((s) => s.setAttribute("stroke-width", "28"));
      legendRows.forEach((row) => row.classList.remove("is-active"));
      donutTotalLabel.textContent = baseLabel;
      donutTotalValue.textContent = baseTotal;
      donutTotalPercent.textContent = "";
    }

    donutSegments.forEach((seg) => {
      seg.addEventListener("mouseenter", () => activate(seg.dataset.category));
      seg.addEventListener("mouseleave", reset);
      seg.addEventListener("focus", () => activate(seg.dataset.category));
      seg.addEventListener("blur", reset);
    });

    legendRows.forEach((row) => {
      row.addEventListener("mouseenter", () => activate(row.dataset.category));
      row.addEventListener("mouseleave", reset);
    });
  }
})();

/**
 * Capacitaciones: focus DNI; copiar enlace público; asistencia pública.
 */
(function () {
  const form = document.getElementById("capAsistenciaForm");
  if (form) {
    const dni = form.querySelector('input[name="dni"]');
    if (dni) dni.focus();
  }
  const publicForm = document.getElementById("capAsistenciaPublicaForm");
  if (publicForm) {
    const dni = publicForm.querySelector('input[name="dni"]');
    if (dni) dni.focus();
  }
})();

(function () {
  document.querySelectorAll("[data-cap-copy-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sel = btn.getAttribute("data-cap-copy-target");
      const el = sel ? document.querySelector(sel) : null;
      if (!el) return;
      el.removeAttribute("readonly");
      el.select();
      el.setSelectionRange(0, 99999);
      el.setAttribute("readonly", "readonly");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(el.value).catch(function () {});
      }
    });
  });
})();

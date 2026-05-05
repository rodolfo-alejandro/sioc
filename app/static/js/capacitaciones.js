/**
 * Capacitaciones: scripts mínimos (p. ej. focus en DNI al cargar asistencia).
 */
(function () {
  const form = document.getElementById("capAsistenciaForm");
  if (!form) return;
  const dni = form.querySelector('input[name="dni"]');
  if (dni) {
    dni.focus();
  }
})();

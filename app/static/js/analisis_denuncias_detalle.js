(function () {
    'use strict';

    function buildDocumentHtml(contentHtml) {
        return [
            '<!doctype html><html><head><meta charset="utf-8"><title>Informe Denuncia Web</title>',
            '<style>',
            '@page{size:A4;margin:18mm;}',
            'body{font-family:Arial,sans-serif;color:#1f2937;font-size:12px;}',
            '.head{border-bottom:2px solid #1d4ed8;padding-bottom:8px;margin-bottom:12px;}',
            '.title{font-size:18px;font-weight:700;color:#1d4ed8;}',
            '.sub{font-size:11px;color:#4b5563;}',
            '.box{border:1px solid #d1d5db;border-radius:6px;padding:10px;margin-bottom:10px;}',
            'h4{font-size:13px;margin:0 0 6px 0;}',
            'p{margin:0 0 5px 0;}',
            '.pre{white-space:pre-wrap;}',
            '</style></head><body>',
            contentHtml,
            '</body></html>'
        ].join('');
    }

    function downloadFile(filename, content, mimeType) {
        var blob = new Blob([content], { type: mimeType });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function init() {
        var root = document.getElementById('ad-detalle-export');
        if (!root) return;
        var dateEl = document.getElementById('ad-det-export-date');
        if (dateEl) dateEl.textContent = new Date().toLocaleString('es-AR');

        var pdfBtn = document.getElementById('ad-det-export-pdf');
        if (pdfBtn) {
            pdfBtn.addEventListener('click', function () {
                if (dateEl) dateEl.textContent = new Date().toLocaleString('es-AR');
                var w = window.open('', '_blank');
                if (!w) return;
                w.document.open();
                w.document.write(buildDocumentHtml(root.innerHTML));
                w.document.close();
                w.focus();
                setTimeout(function () { w.print(); }, 250);
            });
        }

        var wordBtn = document.getElementById('ad-det-export-word');
        if (wordBtn) {
            wordBtn.addEventListener('click', function () {
                if (dateEl) dateEl.textContent = new Date().toLocaleString('es-AR');
                var html = buildDocumentHtml(root.innerHTML);
                var fname = 'denuncia_web_' + new Date().toISOString().slice(0, 10) + '.doc';
                downloadFile(fname, html, 'application/msword;charset=utf-8');
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

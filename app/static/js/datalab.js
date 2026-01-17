// DataLab - JavaScript específico

document.addEventListener('DOMContentLoaded', function() {
    initUploadForm();
});

// Formulario de subida
function initUploadForm() {
    const uploadForm = document.getElementById('uploadForm');
    const uploadProgress = document.getElementById('uploadProgress');
    const submitBtn = document.getElementById('submitBtn');
    
    if (!uploadForm) return;
    
    uploadForm.addEventListener('submit', function(e) {
        // Validar archivo
        const fileInput = uploadForm.querySelector('input[type="file"]');
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            e.preventDefault();
            alert('Por favor seleccione un archivo');
            return;
        }
        
        // Mostrar progreso
        if (uploadProgress) {
            uploadProgress.classList.remove('d-none');
        }
        
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Procesando...';
        }
        
        // El formulario se enviará normalmente
    });
    
    // Validar tamaño de archivo
    const fileInput = uploadForm.querySelector('input[type="file"]');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            const file = this.files[0];
            if (file) {
                const maxSize = 20 * 1024 * 1024; // 20MB
                if (file.size > maxSize) {
                    alert('El archivo es demasiado grande. Máximo: 20MB');
                    this.value = '';
                }
            }
        });
    }
}


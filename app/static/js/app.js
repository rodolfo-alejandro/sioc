// SIOC - JavaScript principal

document.addEventListener('DOMContentLoaded', function() {
    initSidebar();
    initGlobalSearch();
    highlightActiveRoute();
});

// Sidebar
function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggleMobile');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    
    if (!sidebar) return;
    
    // Toggle en desktop (colapsar/expandir)
    if (window.innerWidth > 991) {
        // Por ahora, siempre visible en desktop
        // Se puede agregar un botón para colapsar si se desea
    }
    
    // Toggle en mobile (offcanvas)
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
            sidebarOverlay.classList.toggle('show');
        });
    }
    
    // Cerrar sidebar al hacer click en overlay
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', function() {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
        });
    }
    
    // Cerrar sidebar al redimensionar a desktop
    window.addEventListener('resize', function() {
        if (window.innerWidth > 991) {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
        }
    });
    
    // Manejar submenús
    const submenuToggles = sidebar.querySelectorAll('[data-bs-toggle="collapse"]');
    submenuToggles.forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('data-bs-target'));
            if (target) {
                const bsCollapse = new bootstrap.Collapse(target, {
                    toggle: true
                });
            }
        });
    });
}

// Buscador global
function initGlobalSearch() {
    const searchInput = document.getElementById('globalSearch');
    const searchResults = document.getElementById('searchResults');
    
    if (!searchInput || !searchResults) return;
    
    // Obtener todos los items del menú
    const menuItems = [];
    document.querySelectorAll('.sidebar-nav .nav-link').forEach(link => {
        const text = link.textContent.trim();
        const href = link.getAttribute('href');
        if (href && href !== '#' && text) {
            menuItems.push({ text, href });
        }
    });
    
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase().trim();
        
        if (query.length < 2) {
            searchResults.classList.remove('show');
            return;
        }
        
        // Filtrar items
        const filtered = menuItems.filter(item => 
            item.text.toLowerCase().includes(query)
        );
        
        if (filtered.length > 0) {
            searchResults.innerHTML = filtered.slice(0, 10).map(item => 
                `<div class="search-item" data-href="${item.href}">
                    <i class="bi bi-arrow-right"></i> ${item.text}
                </div>`
            ).join('');
            
            // Agregar event listeners
            searchResults.querySelectorAll('.search-item').forEach(item => {
                item.addEventListener('click', function() {
                    const href = this.dataset.href;
                    if (href) {
                        window.location.href = href;
                    }
                });
            });
            
            searchResults.classList.add('show');
        } else {
            searchResults.classList.remove('show');
        }
    });
    
    // Cerrar resultados al hacer click fuera
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.classList.remove('show');
        }
    });
}

// Resaltar ruta activa
function highlightActiveRoute() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.sidebar-nav .nav-link');
    
    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href && href !== '#') {
            // Comparar rutas
            if (currentPath === href || currentPath.startsWith(href + '/')) {
                link.classList.add('active');
                
                // Expandir submenú padre si existe
                const parentCollapse = link.closest('.collapse');
                if (parentCollapse) {
                    const toggle = document.querySelector(`[data-bs-target="#${parentCollapse.id}"]`);
                    if (toggle) {
                        const bsCollapse = new bootstrap.Collapse(parentCollapse, {
                            show: true
                        });
                    }
                }
            }
        }
    });
}

// Utilidad: formatear números
function formatNumber(num) {
    return new Intl.NumberFormat('es-ES').format(num);
}


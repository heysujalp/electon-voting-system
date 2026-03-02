/**
 * ElectON V2 — Manage My Elections
 * Search, sort, and scroll-in animation logic.
 */
document.addEventListener('DOMContentLoaded', () => {

    /* ─── DOM References ─── */
    const grid        = document.getElementById('electionsGrid');
    const noResults   = document.getElementById('noResults');
    const searchWrap  = document.getElementById('dashSearch');
    const searchBtn   = document.getElementById('searchToggle');
    const searchInput = document.getElementById('searchInput');
    const sortWrap    = document.getElementById('dashSort');
    const sortBtn     = document.getElementById('sortToggle');
    const sortDrop    = document.getElementById('sortDropdown');

    /* ═══════════════════════════════════════════
       Scroll-in Animations (IntersectionObserver)
       ═══════════════════════════════════════════ */
    const animTargets = document.querySelectorAll(
        '.dash-header, .dash-stat, .dash-election-card, .dash-empty, .dash-toolbar'
    );
    animTargets.forEach(el => el.classList.add('anim'));

    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('in');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08 });
        animTargets.forEach(el => observer.observe(el));
    } else {
        /* Fallback: show everything immediately */
        animTargets.forEach(el => el.classList.add('in'));
    }

    /* ═══════════════════════════════════════════
       Search & Status Filter
       ═══════════════════════════════════════════ */
    let activeStatusFilter = null;   /* null = show all */

    function openSearch() {
        if (!searchWrap) return;
        searchWrap.classList.add('open');
        if (searchInput) searchInput.focus();
    }

    function closeSearch() {
        if (!searchWrap) return;
        searchWrap.classList.remove('open');
        if (searchInput) searchInput.value = '';
        applyFilters();
    }

    function applyFilters() {
        if (!grid) return;
        const q = (searchInput ? searchInput.value.trim().toLowerCase() : '');
        const cards = grid.querySelectorAll('.dash-election-card');
        let visible = 0;

        cards.forEach(card => {
            const name = (card.dataset.name || '').toLowerCase();  // FE-16: case-insensitive search
            const eid  = (card.dataset.eid  || '').toLowerCase();
            const status = (card.dataset.status || '');

            const matchesSearch = !q || name.includes(q) || eid.includes(q);
            const matchesStatus = !activeStatusFilter || status === activeStatusFilter;
            const show = matchesSearch && matchesStatus;

            card.style.display = show ? '' : 'none';
            if (show) visible++;
        });

        if (noResults) {
            noResults.classList.toggle('show', visible === 0 && (q.length > 0 || activeStatusFilter));
        }
    }

    if (searchBtn) {
        searchBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (searchWrap && searchWrap.classList.contains('open')) {
                closeSearch();
            } else {
                openSearch();
            }
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', () => applyFilters());
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeSearch();
        });
    }

    /* ═══════════════════════════════════════════
       Sort
       ═══════════════════════════════════════════ */
    function openSort()  { if (sortDrop) sortDrop.classList.add('open'); }
    function closeSort() { if (sortDrop) sortDrop.classList.remove('open'); }

    if (sortBtn) {
        sortBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (sortDrop && sortDrop.classList.contains('open')) {
                closeSort();
            } else {
                openSort();
            }
        });
    }

    if (sortDrop) {
        sortDrop.querySelectorAll('.dash-sort-option').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                sortDrop.querySelectorAll('.dash-sort-option').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                closeSort();
                sortCards(btn.dataset.sort);
            });
        });
    }

    function sortCards(mode) {
        if (!grid) return;
        const cards = Array.from(grid.querySelectorAll('.dash-election-card'));

        /* Status filter modes — filter + sort alphabetically */
        const statusMap = {
            'status-active':     'active',
            'status-pre-launch': 'pre-launch',
            'status-inactive':   'inactive',
            'status-concluded':  'concluded',
        };
        const target = statusMap[mode];

        if (target) {
            activeStatusFilter = target;
            /* Sort matching cards alphabetically by name */
            cards.sort((a, b) => a.dataset.name.localeCompare(b.dataset.name));
            cards.forEach(card => grid.appendChild(card));
            applyFilters();
            return;
        }

        if (mode === 'all') {
            activeStatusFilter = null;
            cards.sort((a, b) => b.dataset.created.localeCompare(a.dataset.created));
            cards.forEach(card => grid.appendChild(card));
            applyFilters();
            return;
        }

        /* Regular sort modes — clear any status filter first */
        activeStatusFilter = null;

        cards.sort((a, b) => {
            switch (mode) {
                case 'date-desc': return b.dataset.created.localeCompare(a.dataset.created);
                case 'date-asc':  return a.dataset.created.localeCompare(b.dataset.created);
                case 'name-asc':  return a.dataset.name.localeCompare(b.dataset.name);
                case 'name-desc': return b.dataset.name.localeCompare(a.dataset.name);
            }
            return 0;
        });

        cards.forEach(card => grid.appendChild(card));
        applyFilters();
    }

    /* ═══════════════════════════════════════════
       Click Outside — close search & sort
       ═══════════════════════════════════════════ */
    document.addEventListener('click', (e) => {
        if (searchWrap && !searchWrap.contains(e.target)) closeSearch();
        if (sortWrap  && !sortWrap.contains(e.target))  closeSort();
    });

    /* ═══════════════════════════════════════════
       Turnout Bars — apply width from data-pct
       ═══════════════════════════════════════════ */
    document.querySelectorAll('.dash-turnout-fill[data-pct]').forEach(el => {
        el.style.width = el.dataset.pct + '%';
    });

    /* ═══════════════════════════════════════════
       Card Click — navigate to dashboard
       ═══════════════════════════════════════════ */
    if (grid) {
        grid.addEventListener('click', (e) => {
            /* Don't hijack clicks on the Manage button */
            if (e.target.closest('.dash-card-manage')) return;
            const card = e.target.closest('.dash-election-card');
            if (card && card.dataset.href) {
                window.location.href = card.dataset.href;
            }
        });
    }

});

// Tab switching — reads URL hash, shows matching panel, updates nav styles.
function initTabs() {
    const links = document.querySelectorAll('[data-tab]');
    const panels = document.querySelectorAll('[data-panel]');
    if (!links.length) return;

    function activate(name) {
        links.forEach(link => {
            const active = link.dataset.tab === name;
            link.classList.toggle('border-indigo-600', active);
            link.classList.toggle('text-indigo-600', active);
            link.classList.toggle('border-transparent', !active);
            link.classList.toggle('text-gray-500', !active);
        });
        panels.forEach(panel => {
            panel.classList.toggle('hidden', panel.dataset.panel !== name);
        });
    }

    const initial = window.location.hash.replace('#', '') || 'overview';
    activate(initial);

    links.forEach(link => {
        link.addEventListener('click', () => activate(link.dataset.tab));
    });

    window.addEventListener('hashchange', () => {
        activate(window.location.hash.replace('#', '') || 'overview');
    });
}

document.addEventListener('DOMContentLoaded', initTabs);

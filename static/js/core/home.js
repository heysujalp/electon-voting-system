/**
 * Home page animations & smooth-scroll.
 */
import { onDOMReady } from '../modules/index.js';

onDOMReady(() => {
    const targets = document.querySelectorAll(
        '.home-role-card, .home-feature-card, .home-step, .home-cta-inner, ' +
        '.home-blockchain-card, .home-usecase-card, .home-security-inner, .home-stat'
    );
    targets.forEach(el => el.classList.add('anim'));
    const io = new IntersectionObserver((entries) => {
        entries.forEach(e => {
            if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
        });
    }, { threshold: 0.1 });
    targets.forEach(el => io.observe(el));

    /* smooth-scroll for anchor links */
    document.querySelectorAll('a[href^="#"]').forEach(a => {
        a.addEventListener('click', e => {
            const target = document.querySelector(a.getAttribute('href'));
            if (target) { e.preventDefault(); target.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
        });
    });
});

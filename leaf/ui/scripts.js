// Scroll log to bottom
function scrollLogToBottom() {
    setTimeout(() => {
        const logElement = document.querySelector('.q-virtual-scroll__content');
        if (logElement) {
            logElement.parentElement.scrollTop = logElement.parentElement.scrollHeight;
        }
    }, 100);
}

// Force tab bar and card dark mode styling
function updateDarkModeStyles() {
    const isDark = document.documentElement.classList.contains('dark');

    // Tab bar styling
    const darkGradient = 'linear-gradient(to right, #1f2937, #111827)';
    const lightGradient = 'linear-gradient(to right, #f9fafb, #ffffff)';
    const darkBg = '#1f2937';
    const lightBg = '#f9fafb';

    // Target all possible tab bar elements
    const tabSelectors = [
        '.leaf-tabs-container',
        '.leaf-tabs-container .q-tabs',
        '.leaf-tabs-container .q-tabs__content',
        '.q-tabs',
        '.q-tabs__content',
        'div[role="tablist"]',
        '.q-tabs--horizontal',
        '.q-tabs.leaf-tabs-container'
    ];

    tabSelectors.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
            el.style.setProperty('background', isDark ? darkGradient : lightGradient, 'important');
            el.style.setProperty('background-color', isDark ? darkBg : lightBg, 'important');
        });
    });

    // Card styling
    const cardDarkBg = 'rgba(31, 41, 55, 0.95)';
    const cardLightBg = 'rgba(255, 255, 255, 0.95)';

    const cardElements = document.querySelectorAll('.leaf-card, .q-card.leaf-card, .nicegui-card.leaf-card');
    cardElements.forEach(el => {
        el.style.setProperty('background', isDark ? cardDarkBg : cardLightBg, 'important');
        el.style.setProperty('background-color', isDark ? darkBg : lightBg, 'important');
    });

    // Card sections - make transparent
    const cardSections = document.querySelectorAll('.q-card__section');
    cardSections.forEach(el => {
        el.style.setProperty('background-color', 'transparent', 'important');
    });
}

// Run immediately and repeatedly for initial page load
updateDarkModeStyles();
setTimeout(updateDarkModeStyles, 50);
setTimeout(updateDarkModeStyles, 200);
setTimeout(updateDarkModeStyles, 500);

// Watch for dark mode changes
if (typeof MutationObserver !== 'undefined') {
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'class') {
                updateDarkModeStyles();
            }
        });
    });

    // Start observing when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.documentElement, { attributes: true });
            // Initial update
            setTimeout(updateDarkModeStyles, 100);
        });
    } else {
        observer.observe(document.documentElement, { attributes: true });
        // Initial update
        setTimeout(updateDarkModeStyles, 100);
    }
}

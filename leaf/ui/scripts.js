// Scroll log to bottom
function scrollLogToBottom() {
    setTimeout(() => {
        const logElement = document.querySelector('.q-virtual-scroll__content');
        if (logElement) {
            logElement.parentElement.scrollTop = logElement.parentElement.scrollHeight;
        }
    }, 100);
}

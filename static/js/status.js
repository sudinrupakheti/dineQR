// static/js/status.js

function startStatusPolling(orderId) {
    const statusText = document.getElementById('status-title');
    const statusDesc = document.getElementById('status-desc');
    const statusBg = document.getElementById('status-bg');
    const mainIcon = document.getElementById('main-icon');

    async function checkStatus() {
    try {
        const response = await fetch(`/api/order-status/${orderId}/`);
        const data = await response.json();

        // Convert to lowercase to avoid "Preparing" vs "preparing" errors
        const status = data.status.toLowerCase();

        // 1. If it's READY or COMPLETED -> Go to Review
        if (status === 'ready' || status === 'completed') {
            window.location.href = `/order/review/${orderId}/`;
            return;
        }

        // 2. If it's PREPARING
        if (status === 'preparing') {
            const statusText = document.getElementById('status-title');
            if (statusText) statusText.innerText = "Cooking Now";

            const stepPrep = document.getElementById('step-preparing');
            if (stepPrep) stepPrep.style.opacity = "1";

            const circle2 = document.getElementById('circle-2');
            if (circle2) {
                circle2.className = "w-10 h-10 rounded-full flex items-center justify-center bg-blue-600 text-white font-bold";
            }

            const bg = document.getElementById('status-bg');
            if (bg) bg.className = "w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 bg-blue-100 text-blue-600";
        }

        lucide.createIcons();
    } catch (e) {
        console.error("Polling error:", e);
    }
}
}

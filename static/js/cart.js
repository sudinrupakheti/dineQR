function getActiveTable() {
    const urlParams = new URLSearchParams(window.location.search);
    let table = urlParams.get('table');

    if (table && table !== "null" && table !== "") {
        localStorage.setItem('dineqr_table', table);
    } else {
        table = localStorage.getItem('dineqr_table');
    }

    if (table) {
        const logoLink = document.getElementById('logo-link');
        if (logoLink) {
            logoLink.href = `/?table=${table}`;
        }
    }
    return table;
}

let tableNumber = getActiveTable();
const cartKey = (tableNumber && tableNumber !== "null") ? `cart_table_${tableNumber}` : 'cart_guest';
let cart = JSON.parse(localStorage.getItem(cartKey)) || {};
let lastCartSync = null;

function getCsrfToken() {
    const el = document.querySelector('input[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
}

// =======================================================
// NEGOTIATE TABLE SESSION TOKEN & PASSCODE REDIRECT
// =======================================================
async function initializeTableSession() {
    if (!tableNumber || tableNumber === "null" || tableNumber === "") {
        return;
    }

    const sessionKey = `dineqr_session_table_${tableNumber}`;
    let sessionToken = localStorage.getItem(sessionKey);

    if (!sessionToken && !window.location.pathname.includes('/welcome')) {
        window.location.href = `/welcome/?table=${tableNumber}`;
        return;
    }

    try {
        const headers = {};
        if (sessionToken) {
            headers['X-Session-Token'] = sessionToken;
        }

        const response = await fetch(`/api/verify-session/?table=${tableNumber}`, {
            method: 'GET',
            headers: headers
        });

        const data = await response.json();
        if (data.status === 'success' && data.token) {
            localStorage.setItem(sessionKey, data.token);
        } else if (data.status === 'password_required') {
            if (!window.location.pathname.includes('/welcome')) {
                window.location.href = `/welcome/?table=${tableNumber}`;
            }
        } else {
            console.warn("Could not authenticate table session:", data.message);
        }
    } catch (error) {
        console.error("Error establishing table session:", error);
    }
}

function getSessionToken() {
    if (!tableNumber) return null;
    return localStorage.getItem(`dineqr_session_table_${tableNumber}`);
}
// =======================================================

// =======================================================
// SHARED CART SYNC (POLLING)
// =======================================================
async function pushCartToServer() {
    if (!tableNumber || tableNumber === "null" || tableNumber === "") return;

    try {
        const response = await fetch("/api/table-cart/update/", {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
                'X-Session-Token': getSessionToken()
            },
            body: JSON.stringify({ table_number: tableNumber, cart: cart })
        });
        const data = await response.json();
        if (data.status === 'success') {
            lastCartSync = data.updated_at;
        }
    } catch (e) {
        console.error("Cart sync push failed:", e);
    }
}

async function pullCartFromServer() {
    if (!tableNumber || tableNumber === "null" || tableNumber === "") return;

    try {
        const response = await fetch(`/api/table-cart/get/?table=${tableNumber}`, {
            headers: { 'X-Session-Token': getSessionToken() }
        });
        const data = await response.json();
        if (data.status === 'success' && data.updated_at && data.updated_at !== lastCartSync) {
            lastCartSync = data.updated_at;
            cart = data.cart || {};
            saveCart();
            updateCartUI();
            if (typeof renderCart === "function") renderCart();
            if (typeof renderCartPage === "function") renderCartPage();
        }
    } catch (e) {
        console.error("Cart sync pull failed:", e);
    }
}

function startCartPolling() {
    if (!tableNumber || tableNumber === "null" || tableNumber === "") return;
    setInterval(pullCartFromServer, 5000);
}
// =======================================================

function addToCart(id, name, price, quantity = 1) {
    if (!tableNumber || tableNumber === "null" || tableNumber === "") {
        alert("Please scan a valid table QR code first.");
        return;
    }

    if (cart[id]) {
        cart[id].quantity += quantity;
    } else {
        cart[id] = {
            name: name,
            price: parseFloat(price),
            quantity: quantity,
            notes: ""
        };
    }

    saveCart();
    updateCartUI();
    pushCartToServer();
}

function saveCart() {
    localStorage.setItem(cartKey, JSON.stringify(cart));
}

function updateCartUI() {
    const badge = document.getElementById('cart-count');
    const floatingCartText = document.getElementById('cart-cta-text');

    if (badge) {
        const totalItems = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
        badge.innerText = totalItems;

        badge.classList.remove('scale-100');
        badge.classList.add('scale-125', 'bg-orange-500', 'animate-bounce');
        setTimeout(() => {
            badge.classList.remove('scale-125', 'animate-bounce');
            badge.classList.add('scale-100');
        }, 600);
    }

    if (floatingCartText) {
        floatingCartText.innerText = "View Your Order/Cart";
    }
}

function updateQuantity(id, delta) {
    if (cart[id]) {
        cart[id].quantity += delta;
        if (cart[id].quantity <= 0) {
            delete cart[id];
        }
        saveCart();
        updateCartUI();
        pushCartToServer();
        if (typeof renderCart === "function") renderCart();
        if (typeof renderCartPage === "function") renderCartPage();
    }
}

function removeFromCart(id) {
    if (cart[id]) {
        delete cart[id];
        saveCart();
        updateCartUI();
        pushCartToServer();
        if (typeof renderCart === "function") renderCart();
        if (typeof renderCartPage === "function") renderCartPage();
    }
}

function updateNote(id, note) {
    if (cart[id]) {
        cart[id].notes = note;
        saveCart();
        pushCartToServer();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateCartUI();
    initializeTableSession();
    pullCartFromServer();
    startCartPolling();
});

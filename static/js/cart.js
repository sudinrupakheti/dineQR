// static/js/cart.js

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

// =======================================================
// NEW: NEGOTIATE TABLE SESSION TOKEN
// =======================================================
async function initializeTableSession() {
    if (!tableNumber || tableNumber === "null" || tableNumber === "") {
        return;
    }

    const sessionKey = `dineqr_session_table_${tableNumber}`;
    let sessionToken = localStorage.getItem(sessionKey);

    // Call the verification API with our existing token (if we have one)
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
            // Save the verified or newly issued token
            localStorage.setItem(sessionKey, data.token);
            console.log("Table session authenticated:", data.token);
        } else {
            console.warn("Could not authenticate table session:", data.message);
        }
    } catch (error) {
        console.error("Error establishing table session:", error);
    }
}

// Retrieve the session token from local storage when making requests
function getSessionToken() {
    if (!tableNumber) return null;
    return localStorage.getItem(`dineqr_session_table_${tableNumber}`);
}
// =======================================================

function addToCart(id, name, price, quantity = 1) { // Added quantity parameter
    console.log("Attempting to add:", name, "Table is:", tableNumber);

    if (!tableNumber || tableNumber === "null" || tableNumber === "") {
        // ... (keep table prompt logic) ...
        return;
    }

    if (cart[id]) {
        cart[id].quantity += quantity; // Increment by requested quantity
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
        if (typeof renderCart === "function") renderCart();
        if (typeof renderCartPage === "function") renderCartPage();
    }
}

function removeFromCart(id) {
    if (cart[id]) {
        delete cart[id];
        saveCart();
        updateCartUI();
        if (typeof renderCart === "function") renderCart();
        if (typeof renderCartPage === "function") renderCartPage();
    }
}

function updateNote(id, note) {
    if (cart[id]) {
        cart[id].notes = note;
        saveCart();
    }
}

// Initialize session and UI on page load
document.addEventListener('DOMContentLoaded', () => {
    updateCartUI();
    initializeTableSession();
});

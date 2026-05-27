// static/js/cart.js

// 1. Get table from URL immediately
function getTableFromURL() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('table');
}

let tableNumber = getTableFromURL();
const cartKey = tableNumber ? `cart_table_${tableNumber}` : 'cart_guest';
let cart = JSON.parse(localStorage.getItem(cartKey)) || {};

function addToCart(id, name, price) {
    console.log("Attempting to add:", name, "Table is:", tableNumber);

    // If no table is found in the URL
    if (!tableNumber || tableNumber === "null" || tableNumber === "") {
        console.log("No table detected. Triggering prompt...");
        const userTable = prompt("Please enter your table number to start ordering:");

        if (userTable && userTable.trim() !== "") {
            // Redirect to the URL with the table number
            const currentUrl = window.location.pathname;
            window.location.href = `${currentUrl}?table=${userTable.trim()}`;
        }
        return; // Stop the function until the page reloads with a table
    }

    // Normal add to cart logic
    if (cart[id]) {
        cart[id].quantity += 1;
    } else {
        cart[id] = {
            name: name,
            price: parseFloat(price),
            quantity: 1,
            notes: ""
        };
    }

    saveCart();
    updateCartUI();
    console.log("Cart updated:", cart);
}

function saveCart() {
    localStorage.setItem(cartKey, JSON.stringify(cart));
}

function updateCartUI() {
    const badge = document.getElementById('cart-count');
    if (badge) {
        const totalItems = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
        badge.innerText = totalItems;
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

document.addEventListener('DOMContentLoaded', updateCartUI);

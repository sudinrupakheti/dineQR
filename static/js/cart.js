// static/js/cart.js

// 1. Detect table from URL
const urlParams = new URLSearchParams(window.location.search);
let tableNumber = urlParams.get('table');

// 2. Create a unique key for this table (or 'guest' if no table)
const cartKey = tableNumber ? `cart_table_${tableNumber}` : 'cart_guest';

// 3. Load the specific cart
let cart = JSON.parse(localStorage.getItem(cartKey)) || {};

function addToCart(id, name, price) {
    // If no table is found, ask for it
    if (!tableNumber || tableNumber === "0") {
        const userTable = prompt("Please enter your table number to start ordering:");
        if (userTable) {
            // Redirect to the same page but WITH the table number in the URL
            window.location.href = `?table=${userTable}`;
        }
        return; // Stop the function here
    }

    // Normal add to cart logic
    if (cart[id]) {
        cart[id].quantity += 1;
    } else {
        cart[id] = {
            name: name,
            price: parseFloat(price),
            quantity: 1
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
    if (badge) {
        const totalItems = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
        badge.innerText = totalItems;
    }
}

document.addEventListener('DOMContentLoaded', updateCartUI);
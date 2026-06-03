function getActiveTable() {
    const urlParams = new URLSearchParams(window.location.search);
    let table = urlParams.get('table');

    if (table && table !== "null" && table !== "") {
        localStorage.setItem('dineqr_table', table);
    } else {
        table = localStorage.getItem('dineqr_table');
    }

    // FIX: Dynamically adapt the main logo anchor link to keep the table context alive
    if (table) {
        const logoLink = document.getElementById('logo-link');
        if (logoLink) {
            logoLink.href = `/?table=${table}`;
        }
    }
    return table;
}

let tableNumber = getActiveTable();
// Use the table number to find the right cart, or 'cart_guest' if truly unknown
const cartKey = (tableNumber && tableNumber !== "null") ? `cart_table_${tableNumber}` : 'cart_guest';
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
    const floatingCartText = document.getElementById('cart-cta-text');

    if (badge) {
        const totalItems = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
        badge.innerText = totalItems;

        // UX Enhancement: Add pulse animation loops on modification
        badge.classList.remove('scale-100');
        badge.classList.add('scale-125', 'bg-orange-500', 'animate-bounce');
        setTimeout(() => {
            badge.classList.remove('scale-125', 'animate-bounce');
            badge.classList.add('scale-100');
        }, 600);
    }

    // Explicitly update text instructions near floating action triggers if present
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

document.addEventListener('DOMContentLoaded', updateCartUI);

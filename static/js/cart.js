// static/js/cart.js

function getTableNumber() {
    const params = new URLSearchParams(window.location.search);
    return params.get('table') || localStorage.getItem('dineqr_table');
}

let tableNumber = getTableNumber();
const cartKey = tableNumber ? `cart_table_${tableNumber}` : 'cart_guest';
let cart = JSON.parse(localStorage.getItem(cartKey)) || {};

// Native-feeling Toast Notification
function showToast(message) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = "bg-gray-900 text-white px-6 py-3 rounded-2xl shadow-2xl flex items-center gap-3 transform translate-y-10 opacity-0 transition-all duration-300 font-bold text-sm";
    toast.innerHTML = `
        <div class="bg-green-500 rounded-full p-1">
            <i data-lucide="check" class="w-3 h-3 text-white"></i>
        </div>
        ${message}
    `;

    container.appendChild(toast);
    lucide.createIcons();

    setTimeout(() => { toast.classList.remove('translate-y-10', 'opacity-0'); }, 10);

    setTimeout(() => {
        toast.classList.add('translate-y-10', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}

// Visual Add To Cart Handler
function handleAddToCart(event, id, name, price) {
    const btn = event.currentTarget;
    const textSpan = btn.querySelector('.btn-text');
    const iconNormal = btn.querySelector('.icon-normal');
    const iconSuccess = btn.querySelector('.icon-success');

    addToCart(id, name, price);

    // Visual feedback
    btn.classList.add('bg-green-600', 'scale-95');
    btn.classList.remove('bg-gray-900', 'hover:bg-orange-600');
    if(textSpan) textSpan.innerText = "Added";
    if(iconNormal) iconNormal.classList.add('hidden');
    if(iconSuccess) iconSuccess.classList.remove('hidden');

    showToast(`${name} added to cart`);

    setTimeout(() => {
        btn.classList.remove('bg-green-600', 'scale-95');
        btn.classList.add('bg-gray-900', 'hover:bg-orange-600');
        if(textSpan) textSpan.innerText = "Add to Cart";
        if(iconNormal) iconNormal.classList.remove('hidden');
        if(iconSuccess) iconSuccess.classList.add('hidden');
    }, 1500);
}

function addToCart(id, name, price) {
    if (!tableNumber || tableNumber === "null") {
        const userTable = prompt("Please enter your table number to start ordering:");
        if (userTable && userTable.trim() !== "") {
            localStorage.setItem('dineqr_table', userTable.trim());
            const url = new URL(window.location.href);
            url.searchParams.set('table', userTable.trim());
            window.location.href = url.toString();
        }
        return;
    }

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
}

function saveCart() {
    localStorage.setItem(cartKey, JSON.stringify(cart));
}

function updateCartUI() {
    const badge = document.getElementById('cart-count');
    if (badge) {
        const totalItems = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
        badge.innerText = totalItems;

        // Bounce animation
        badge.classList.add('scale-150');
        setTimeout(() => badge.classList.remove('scale-150'), 200);
    }
}

// We need these for the Cart Page!
function updateQuantity(id, delta) {
    if (cart[id]) {
        cart[id].quantity += delta;
        if (cart[id].quantity <= 0) {
            delete cart[id];
        }
        saveCart();
        updateCartUI();
        if (typeof renderCart === "function") renderCart();
    }
}

function removeFromCart(id) {
    delete cart[id];
    saveCart();
    updateCartUI();
    if (typeof renderCart === "function") renderCart();
}

function updateNote(id, note) {
    if (cart[id]) {
        cart[id].notes = note;
        saveCart();
    }
}

document.addEventListener('DOMContentLoaded', updateCartUI);

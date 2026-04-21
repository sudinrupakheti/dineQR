let cart = JSON.parse(localStorage.getItem('cart')) || {};

const urlParams = new URLSearchParams(window.location.search);
const tableNumber = urlParams.get('table') || "0";

function addToCart(id, name, price) {
    console.log("Adding to cart:", name);

    if (cart[id]) {
        cart[id].quantity += 1;
    } else {
        cart[id] = {
            name: name,
            price: parseFloat(price),
            quantity: 1,
            table: tableNumber
        };
    }

    saveCart();
    updateCartUI();
}

function saveCart() {
    localStorage.setItem('cart', JSON.stringify(cart));
}

function updateCartUI() {
    const badge = document.getElementById('cart-count');
    if (badge) {
        const totalItems = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
        badge.innerText = totalItems;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateCartUI();

    if (tableNumber !== "0") {
        console.log("Ordering from Table:", tableNumber);
    }
});

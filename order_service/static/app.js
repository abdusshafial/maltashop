const featuredProducts = [
  { sku: "HEADPHONES-01", name: "Everyday headphones", category: "Tech", price: 64, tag: "ISLAND FAVOURITE", emoji: "🎧", bg: "#d8d0bb", image: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=700&q=80", description: "Settle into your own soundtrack with an everyday essential, chosen for unhurried moments at home or on the go." },
  { sku: "VASE-01", name: "Sorrento ceramic vase", category: "Home", price: 32, tag: "MADE TO KEEP", emoji: "🏺", bg: "#e7d2bd", image: "https://images.unsplash.com/photo-1578500494198-246f612d3b3d?auto=format&fit=crop&w=700&q=80", description: "A quietly beautiful accent for a favourite corner, whether it holds fresh stems or simply catches the afternoon light." },
  { sku: "WATCH-01", name: "Sunday wristwatch", category: "Wear", price: 89, tag: "A GOOD GIFT", emoji: "⌚", bg: "#e5d7c6", image: "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=700&q=80", description: "A simple finishing touch for everyday plans and slow Sundays alike." },
  { sku: "SPEAKER-01", name: "Golden hour speaker", category: "Tech", price: 48, tag: "NEW ARRIVAL", emoji: "🔊", bg: "#ced2c4", image: "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?auto=format&fit=crop&w=700&q=80", description: "Bring a little soundtrack to your space with this fresh pick from the MaltaShop edit." },
  { sku: "CHAIR-01", name: "The slow-morning chair", category: "Home", price: 145, tag: "MADE TO KEEP", emoji: "🪑", bg: "#d6cbb7", image: "https://images.unsplash.com/photo-1503602642458-232111445657?auto=format&fit=crop&w=700&q=80", description: "Make room for a slower start and a comfortable spot to pause in your home." },
  { sku: "CAMERA-01", name: "Little moments camera", category: "Tech", price: 119, tag: "ISLAND FAVOURITE", emoji: "📷", bg: "#d1d1c5", image: "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=700&q=80", description: "Keep a camera close for the everyday scenes and little details worth remembering." },
  { sku: "SNEAKERS-01", name: "All-day canvas sneakers", category: "Wear", price: 72, tag: "GOOD ON THE GO", emoji: "👟", bg: "#e5c4ad", image: "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=700&q=80", description: "An easygoing everyday pick for days that take you from one place to the next." },
  { sku: "LAMP-01", name: "Soft-light table lamp", category: "Home", price: 58, tag: "A LITTLE GLOW", emoji: "💡", bg: "#d8d2bb", image: "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?auto=format&fit=crop&w=700&q=80", description: "Add a softer note to a bedside table, reading nook, or favourite corner." }
];

const products = [...featuredProducts, ...additionalProducts];
const money = new Intl.NumberFormat("en-MT", { style: "currency", currency: "EUR" });
const productBySku = new Map(products.map((product) => [product.sku, product]));
const productGrid = document.querySelector("#productGrid");
const emptySearch = document.querySelector("#emptySearch");
const searchInput = document.querySelector("#searchInput");
const sortSelect = document.querySelector("#sortSelect");
const priceRange = document.querySelector("#priceRange");
const favoritesOnlyButton = document.querySelector("#favoritesOnly");
const motionToggle = document.querySelector("#motionToggle");
const productGridView = document.querySelector("#gridView");
const productListView = document.querySelector("#listView");
const cartDrawer = document.querySelector("#cartDrawer");
const drawerBackdrop = document.querySelector("#drawerBackdrop");
const toast = document.querySelector("#toast");
let activeCategory = "All";
let cart = loadCart();
let favorites = loadFavorites();
let favoritesOnly = false;
let motionEnabled = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let activeProductSku = null;
let toastTimer;
let lastOrderIds = [];
let lastCustomerDetails = null;
let activeMyOrdersCredentials = null;
let pendingCancellation = null;

function loadCart() {
  try {
    const saved = JSON.parse(localStorage.getItem("maltashop-cart") || "[]");
    if (!Array.isArray(saved)) throw new TypeError("Saved cart must be a list");
    return saved.filter((line) => productBySku.has(line.sku) && Number.isInteger(line.quantity) && line.quantity > 0 && line.quantity <= 100);
  } catch (error) {
    console.error("Could not restore the saved shopping bag:", error);
    return [];
  }
}

function saveCart() {
  try {
    localStorage.setItem("maltashop-cart", JSON.stringify(cart));
  } catch (error) {
    console.error("Could not save the shopping bag:", error);
    showToast("Your browser couldn’t save this bag. Keep this tab open while you shop.");
  }
}

function loadFavorites() {
  try {
    const saved = JSON.parse(localStorage.getItem("maltashop-favorites") || "[]");
    if (!Array.isArray(saved)) throw new TypeError("Saved favourites must be a list");
    return [...new Set(saved.filter((sku) => productBySku.has(sku)))];
  } catch (error) {
    console.error("Could not restore saved favourites:", error);
    return [];
  }
}

function saveFavorites() {
  try {
    localStorage.setItem("maltashop-favorites", JSON.stringify(favorites));
  } catch (error) {
    console.error("Could not save favourites:", error);
    showToast("Your browser couldn’t save favourites. Keep this tab open.");
  }
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2600);
}

function renderProducts() {
  const search = searchInput.value.trim().toLocaleLowerCase();
  const maximumPrice = Number(priceRange.value);
  let visible = products.filter((product) => {
    const matchesCategory = activeCategory === "All" || product.category === activeCategory;
    const matchesSearch = `${product.name} ${product.category} ${product.tag}`.toLocaleLowerCase().includes(search);
    const matchesPrice = product.price <= maximumPrice;
    const matchesFavorites = !favoritesOnly || favorites.includes(product.sku);
    return matchesCategory && matchesSearch && matchesPrice && matchesFavorites;
  });

  if (sortSelect.value === "price-low") visible = [...visible].sort((a, b) => a.price - b.price);
  if (sortSelect.value === "price-high") visible = [...visible].sort((a, b) => b.price - a.price);
  if (sortSelect.value === "name") visible = [...visible].sort((a, b) => a.name.localeCompare(b.name));
  if (sortSelect.value === "newest") visible = [...visible].sort((a, b) => Number(b.tag === "NEW ARRIVAL") - Number(a.tag === "NEW ARRIVAL"));

  productGrid.innerHTML = visible.map((product) => `
    <article class="product-card">
      <div class="product-visual" style="--product-bg:${product.bg}">
        <img src="${product.image}" alt="" loading="lazy">
        <span class="product-tag">${product.tag}</span>
        <button class="favorite-button${favorites.includes(product.sku) ? " is-saved" : ""}" type="button" data-favorite="${product.sku}" aria-label="${favorites.includes(product.sku) ? "Remove" : "Save"} ${product.name} ${favorites.includes(product.sku) ? "from" : "to"} favourites" aria-pressed="${favorites.includes(product.sku)}">${favorites.includes(product.sku) ? "♥" : "♡"}</button>
        <button class="quick-view" type="button" data-view="${product.sku}">Quick view</button>
        <button class="quick-add" type="button" data-add="${product.sku}" aria-label="Add ${product.name} to bag">+</button>
      </div>
      <div class="product-meta">
        <div><h3>${product.name}</h3><p class="product-category">${product.category} · ${product.sku}</p><p class="product-delivery">Estimated delivery: 2–5 working days</p></div>
        <span class="product-price">${money.format(product.price)}</span>
      </div>
    </article>
  `).join("");
  productGrid.hidden = visible.length === 0;
  emptySearch.hidden = visible.length !== 0;
  document.querySelector("#productTotal").textContent = `${visible.length} good things${favorites.length ? ` · ${favorites.length} saved` : ""}`;
  document.querySelector("#favoriteCount").textContent = favorites.length;
  favoritesOnlyButton.classList.toggle("is-active", favoritesOnly);
  favoritesOnlyButton.setAttribute("aria-pressed", String(favoritesOnly));
  productGrid.querySelectorAll("img").forEach((image) => {
    image.addEventListener("error", () => image.remove(), { once: true });
  });
}

function toggleFavorite(sku) {
  if (favorites.includes(sku)) {
    favorites = favorites.filter((favorite) => favorite !== sku);
    showToast(`${productBySku.get(sku).name} removed from saved items.`);
  } else {
    favorites.push(sku);
    showToast(`${productBySku.get(sku).name} saved for later.`);
  }
  saveFavorites();
  renderProducts();
}

function openProductDialog(sku) {
  const product = productBySku.get(sku);
  if (!product) return;
  activeProductSku = sku;
  const image = document.querySelector("#productDialogImg");
  image.hidden = false;
  image.src = product.image;
  image.alt = product.name;
  image.onerror = () => { image.hidden = true; };
  document.querySelector("#productDialogImage").style.setProperty("--product-bg", product.bg);
  document.querySelector("#productDialogCategory").textContent = `${product.category} · ${product.tag}`;
  document.querySelector("#productDialogTitle").textContent = product.name;
  document.querySelector("#productDialogPrice").textContent = money.format(product.price);
  document.querySelector("#productDialogDescription").textContent = product.description;
  document.querySelector("#productDialogDetails").innerHTML = `
    <div><span>Product code</span><strong>${product.sku}</strong></div>
    <div><span>Category</span><strong>${product.category}</strong></div>
    <div><span>Delivery estimate</span><strong>2–5 working days</strong></div>
    <p>Estimated after checkout, Monday to Friday, across Malta and Gozo. Actual delivery time may vary.</p>
  `;
  const favoriteButton = document.querySelector("#productDialogFavorite");
  const isSaved = favorites.includes(sku);
  favoriteButton.textContent = isSaved ? "♥ Saved" : "♡ Save";
  favoriteButton.classList.toggle("is-saved", isSaved);
  favoriteButton.setAttribute("aria-pressed", String(isSaved));
  document.querySelector("#productDialog").showModal();
}

function cartQuantity() {
  return cart.reduce((total, line) => total + line.quantity, 0);
}

function cartTotal() {
  return cart.reduce((total, line) => total + productBySku.get(line.sku).price * line.quantity, 0);
}

function renderCart() {
  const quantity = cartQuantity();
  document.querySelector("#cartCount").textContent = quantity;
  document.querySelector("#drawerCount").textContent = quantity ? `(${quantity})` : "";
  document.querySelector("#cartSubtotal").textContent = money.format(cartTotal());
  document.querySelector("#cartEmpty").hidden = quantity > 0;
  document.querySelector("#cartSummary").hidden = quantity === 0;
  document.querySelector("#cartItems").innerHTML = cart.map((line) => {
    const product = productBySku.get(line.sku);
    return `
      <article class="cart-line">
        <div class="cart-line-image" style="--product-bg:${product.bg}">
          <img src="${product.image}" alt="" loading="lazy">
        </div>
        <div class="cart-line-main">
          <h3>${product.name}</h3>
          <p>${money.format(product.price)} each</p>
          <div class="quantity-control" aria-label="Quantity for ${product.name}">
            <button type="button" data-quantity="-1" data-sku="${product.sku}" aria-label="Remove one ${product.name}">−</button>
            <span>${line.quantity}</span>
            <button type="button" data-quantity="1" data-sku="${product.sku}" aria-label="Add one ${product.name}">+</button>
          </div>
        </div>
        <div class="cart-line-end">
          <strong>${money.format(product.price * line.quantity)}</strong>
          <button class="remove-item" type="button" data-remove="${product.sku}">Remove</button>
        </div>
      </article>
    `;
  }).join("");
  document.querySelectorAll(".cart-line-image img").forEach((image) => {
    image.addEventListener("error", () => image.remove(), { once: true });
  });
}

function addToCart(sku) {
  const line = cart.find((item) => item.sku === sku);
  if (line) {
    if (line.quantity >= 100) {
      showToast("That’s the maximum quantity for one item.");
      return;
    }
    line.quantity += 1;
  } else {
    cart.push({ sku, quantity: 1 });
  }
  saveCart();
  renderCart();
  showToast(`${productBySku.get(sku).name} added to your bag.`);
}

function setDrawerOpen(open) {
  cartDrawer.classList.toggle("is-open", open);
  cartDrawer.setAttribute("aria-hidden", String(!open));
  cartDrawer.inert = !open;
  drawerBackdrop.hidden = !open;
  document.body.classList.toggle("no-scroll", open);
  if (open) document.querySelector("#closeCart").focus();
  else document.querySelector("#openCart").focus();
}

function createCorrelationId() {
  return globalThis.crypto?.randomUUID?.() || `corr-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function syncPaymentSelection() {
  document.querySelectorAll(".payment-option").forEach((option) => {
    const input = option.querySelector('input[name="paymentMethod"]');
    option.classList.toggle("is-selected", input?.checked === true);
  });
}

function renderReview() {
  const paymentMethod = document.querySelector('input[name="paymentMethod"]:checked');
  const paymentLabel = paymentMethod?.closest(".payment-option").querySelector(".payment-option-copy strong").textContent;
  document.querySelector("#checkoutReview").innerHTML = `
    ${cart.map((line) => {
      const product = productBySku.get(line.sku);
      return `<div class="review-row"><span>${product.name} × ${line.quantity}</span><strong>${money.format(product.price * line.quantity)}</strong></div>`;
    }).join("")}
    <div class="review-row review-total"><span>Total</span><strong>${money.format(cartTotal())}</strong></div>
    <div class="review-method">Demo preference <strong>${paymentLabel || "Choose a method"}</strong></div>
  `;
}

function openTrackDialog(orderId = "") {
  const input = document.querySelector("#trackOrderId");
  input.value = orderId;
  document.querySelector("#trackResult").hidden = true;
  document.querySelector("#trackError").hidden = true;
  document.querySelector("#trackDialog").showModal();
  if (!orderId) input.focus();
}

function formatDeliveryRange(order) {
  const minimumDays = order.delivery_min_days || 2;
  const maximumDays = order.delivery_max_days || 5;
  if (!order.earliest_delivery || !order.latest_delivery) {
    return `${minimumDays}–${maximumDays} working days`;
  }
  const dateOptions = { day: "numeric", month: "short", year: "numeric" };
  const earliest = new Intl.DateTimeFormat("en-MT", dateOptions)
    .format(new Date(`${order.earliest_delivery}T12:00:00`));
  const latest = new Intl.DateTimeFormat("en-MT", dateOptions)
    .format(new Date(`${order.latest_delivery}T12:00:00`));
  return `${minimumDays}–${maximumDays} working days · ${earliest}–${latest}`;
}

async function lookupOrder(orderId) {
  const errorBox = document.querySelector("#trackError");
  const result = document.querySelector("#trackResult");
  errorBox.hidden = true;
  result.hidden = true;
  try {
    const response = await fetch(`/orders/${encodeURIComponent(orderId.trim())}`);
    const order = await response.json();
    if (!response.ok) throw new Error(response.status === 404 ? "We couldn’t find that order. Check the ID and try again." : (order.detail || "Order lookup failed."));

    const heading = document.createElement("h3");
    heading.textContent = order.status === "PENDING" ? "Your order is in the works." : `Order status: ${order.status}`;
    const id = document.createElement("p");
    id.innerHTML = "<strong>Order ID</strong>";
    const idValue = document.createElement("p");
    idValue.textContent = order.order_id;
    const item = document.createElement("p");
    item.innerHTML = "<strong>Item</strong>";
    const itemValue = document.createElement("p");
    itemValue.textContent = `${productBySku.get(order.sku)?.name || order.sku} × ${order.quantity}`;
    const delivery = document.createElement("p");
    delivery.innerHTML = "<strong>Delivery estimate</strong>";
    const deliveryValue = document.createElement("p");
    deliveryValue.textContent = formatDeliveryRange(order);
    result.replaceChildren(heading, id, idValue, item, itemValue, delivery, deliveryValue);
    result.hidden = false;
  } catch (error) {
    errorBox.textContent = error.message || "We couldn’t look up that order. Please try again.";
    errorBox.hidden = false;
  }
}

function renderConfirmation(orders, details) {
  lastCustomerDetails = details;
  lastOrderIds = orders.map((order) => order.order_id);
  const paymentLabels = { card: "Credit or debit card (demo)", paypal: "PayPal (demo)", cash: "Cash on delivery (demo)" };
  const savedDetails = document.querySelector("#confirmationDetails");
  savedDetails.replaceChildren();
  [
    `Delivery to: ${details.full_name}`,
    `${details.address}, ${details.city}, ${details.postal_code}`,
    `Contact: ${details.email} · ${details.phone}`,
    `Payment preference: ${paymentLabels[details.payment_method] || details.payment_method}`,
    "Estimated delivery: 2–5 working days (Monday–Friday)"
  ].forEach((text) => {
    const line = document.createElement("p");
    line.textContent = text;
    savedDetails.append(line);
  });
  const container = document.querySelector("#confirmationOrders");
  container.replaceChildren(...orders.map((order) => {
    const wrapper = document.createElement("div");
    wrapper.className = "confirmation-order";
    const product = productBySku.get(order.sku);
    const paragraph = document.createElement("p");
    paragraph.textContent = product ? `${product.name} × ${order.quantity} · ${order.status}` : `Order · ${order.status}`;
    const code = document.createElement("code");
    code.textContent = order.order_id;
    const delivery = document.createElement("p");
    delivery.textContent = `Estimated delivery: ${formatDeliveryRange(order)}`;
    wrapper.append(paragraph, code, delivery);
    return wrapper;
  }));
  document.querySelector("#confirmationDialog").showModal();
}

function formatOrderDate(value) {
  if (!value) return "Date unavailable";
  return new Intl.DateTimeFormat("en-MT", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function renderMyOrders(orders) {
  const list = document.querySelector("#myOrdersList");
  list.replaceChildren();
  if (!orders.length) {
    const empty = document.createElement("p");
    empty.className = "my-orders-empty";
    empty.textContent = "No orders were found for that email and phone number.";
    list.append(empty);
    list.hidden = false;
    return;
  }

  orders.forEach((order) => {
    const card = document.createElement("article");
    card.className = "my-order-card";
    const header = document.createElement("div");
    header.className = "my-order-header";
    const title = document.createElement("h3");
    title.textContent = `Order placed ${formatOrderDate(order.created_at)}`;
    const status = document.createElement("span");
    status.className = `my-order-status${order.status === "CANCELLED" ? " is-cancelled" : ""}`;
    status.textContent = order.status === "CANCELLED" ? "Cancelled" : order.status === "PENDING" ? "Confirmed" : order.status;
    header.append(title, status);

    const items = document.createElement("ul");
    items.className = "my-order-items";
    order.items.forEach((item) => {
      const line = document.createElement("li");
      const product = productBySku.get(item.sku);
      line.textContent = `${product?.name || item.sku} × ${item.quantity}`;
      items.append(line);
    });

    const delivery = document.createElement("p");
    delivery.className = "my-order-delivery";
    delivery.textContent = `Estimated delivery: ${order.delivery_min_days}–${order.delivery_max_days} working days`;
    card.append(header, items, delivery);
    const complaintButton = document.createElement("button");
    complaintButton.className = "button button-outline my-order-cancel";
    complaintButton.type = "button";
    complaintButton.textContent = "Report a problem";
    complaintButton.addEventListener("click", () => openComplaint(order));
    card.append(complaintButton);

    if (order.status === "CANCELLED") {
      const cancelled = document.createElement("p");
      cancelled.className = "my-order-window";
      cancelled.textContent = "This order has been cancelled.";
      card.append(cancelled);
    } else if (order.can_cancel) {
      const deadline = document.createElement("p");
      deadline.className = "my-order-window";
      deadline.textContent = `You can cancel before ${formatOrderDate(order.cancellation_deadline)}.`;
      const cancelButton = document.createElement("button");
      cancelButton.className = "button button-outline my-order-cancel";
      cancelButton.type = "button";
      cancelButton.textContent = "Cancel order";
      cancelButton.addEventListener("click", () => openCancelOrder(order));
      card.append(deadline, cancelButton);
    } else if (order.status === "PENDING") {
      const closed = document.createElement("p");
      closed.className = "my-order-window";
      closed.textContent = "The 12-hour cancellation window has closed.";
      card.append(closed);
    }

    list.append(card);
  });
  list.hidden = false;
}

function openComplaint(order) {
  if (!activeMyOrdersCredentials) {
    showToast("Find your order before sending a complaint.");
    return;
  }
  const form = document.querySelector("#complaintForm");
  const productSelect = document.querySelector("#complaintProduct");
  productSelect.replaceChildren(...order.items.map((item) => {
    const option = document.createElement("option");
    option.value = item.sku;
    option.textContent = `${productBySku.get(item.sku)?.name || item.sku} × ${item.quantity}`;
    return option;
  }));
  document.querySelector("#complaintOrderSummary").textContent =
    `Order placed ${formatOrderDate(order.created_at)} · ${order.items.map((item) => productBySku.get(item.sku)?.name || item.sku).join(", ")}`;
  document.querySelector("#complaintError").hidden = true;
  document.querySelector("#complaintSuccess").hidden = true;
  form.reset();
  document.querySelector("#complaintProductField").hidden = false;
  document.querySelector("#complaintProduct").required = true;
  document.querySelector("#myOrdersDialog").close();
  const dialog = document.querySelector("#complaintDialog");
  dialog.dataset.correlationId = order.correlation_id;
  dialog.showModal();
}

function syncComplaintType() {
  const isProductComplaint = document.querySelector("#complaintType").value === "product";
  document.querySelector("#complaintProductField").hidden = !isProductComplaint;
  document.querySelector("#complaintProduct").required = isProductComplaint;
}

async function submitComplaint(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#submitComplaint");
  const errorBox = document.querySelector("#complaintError");
  const successBox = document.querySelector("#complaintSuccess");
  const dialog = document.querySelector("#complaintDialog");
  if (!activeMyOrdersCredentials || !dialog.dataset.correlationId) {
    errorBox.textContent = "Find your order again before submitting a complaint.";
    errorBox.hidden = false;
    return;
  }
  const formData = new FormData(form);
  const complaintType = formData.get("complaintType").toString();
  const payload = {
    ...activeMyOrdersCredentials,
    correlation_id: dialog.dataset.correlationId,
    complaint_type: complaintType,
    product_sku: complaintType === "product" ? formData.get("productSku").toString() : null,
    message: formData.get("message").toString().trim()
  };
  errorBox.hidden = true;
  successBox.hidden = true;
  button.disabled = true;
  button.classList.add("is-busy");
  try {
    const response = await fetch("/orders/complaints", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "We couldn’t send your complaint. Please try again.");
    successBox.textContent = "Your complaint has been received. MaltaShop support will review it.";
    successBox.hidden = false;
    form.reset();
    document.querySelector("#complaintType").value = "product";
    syncComplaintType();
    button.textContent = "Complaint sent";
    setTimeout(() => {
      if (dialog.open) dialog.close();
    }, 1400);
  } catch (error) {
    errorBox.textContent = error.message || "We couldn’t reach support. Please try again.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
    button.classList.remove("is-busy");
    if (button.textContent === "Complaint sent") {
      setTimeout(() => { button.innerHTML = 'Send complaint <span aria-hidden="true">→</span>'; }, 1500);
    } else {
      button.innerHTML = 'Send complaint <span aria-hidden="true">→</span>';
    }
  }
}

function openMyOrders(email = "", phone = "") {
  const dialog = document.querySelector("#myOrdersDialog");
  const form = document.querySelector("#myOrdersForm");
  form.elements.email.value = email;
  form.elements.phone.value = phone;
  document.querySelector("#myOrdersError").hidden = true;
  document.querySelector("#myOrdersList").hidden = true;
  if (!dialog.open) dialog.showModal();
  if (email && phone) loadMyOrders(email, phone);
  else form.elements.email.focus();
}

async function loadMyOrders(email, phone) {
  const errorBox = document.querySelector("#myOrdersError");
  const button = document.querySelector("#findMyOrders");
  errorBox.hidden = true;
  document.querySelector("#myOrdersList").hidden = true;
  button.disabled = true;
  button.classList.add("is-busy");
  button.textContent = "Looking for your orders…";
  activeMyOrdersCredentials = { email, phone };
  try {
    const response = await fetch("/orders/my", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, phone })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "We couldn’t find your orders. Please try again.");
    if (!Array.isArray(result.orders)) throw new Error("The order service returned an unexpected response.");
    renderMyOrders(result.orders);
  } catch (error) {
    errorBox.textContent = error.message || "We couldn’t reach the order service. Please try again.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
    button.classList.remove("is-busy");
    button.innerHTML = 'Find my orders <span aria-hidden="true">→</span>';
  }
}

function openCancelOrder(order) {
  pendingCancellation = order;
  document.querySelector("#cancelOrderError").hidden = true;
  const names = order.items.map((item) => {
    const product = productBySku.get(item.sku);
    return `${product?.name || item.sku} × ${item.quantity}`;
  });
  document.querySelector("#cancelOrderDescription").textContent =
    `Cancel ${names.join(", ")}? This cannot be undone. You can cancel this order within 12 hours of placing it, until ${formatOrderDate(order.cancellation_deadline)}.`;
  document.querySelector("#cancelOrderDialog").showModal();
}

async function confirmCancelOrder() {
  if (!pendingCancellation || !activeMyOrdersCredentials) return;
  const button = document.querySelector("#confirmCancelOrder");
  const errorBox = document.querySelector("#cancelOrderError");
  errorBox.hidden = true;
  button.disabled = true;
  button.classList.add("is-busy");
  try {
    const response = await fetch("/orders/my/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...activeMyOrdersCredentials,
        correlation_id: pendingCancellation.correlation_id
      })
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.detail || "We couldn’t cancel this order. Please try again.");
      error.status = response.status;
      throw error;
    }
    document.querySelector("#cancelOrderDialog").close();
    showToast(result.already_cancelled ? "This order was already cancelled." : "Your order has been cancelled.");
    await loadMyOrders(activeMyOrdersCredentials.email, activeMyOrdersCredentials.phone);
  } catch (error) {
    errorBox.textContent = error.message || "We couldn’t reach the order service. Please try again.";
    errorBox.hidden = false;
    if (error.status === 409) {
      await loadMyOrders(activeMyOrdersCredentials.email, activeMyOrdersCredentials.phone);
    }
  } finally {
    button.disabled = false;
    button.classList.remove("is-busy");
    button.textContent = "Yes, cancel this order";
  }
}

document.querySelectorAll("[data-category]").forEach((button) => {
  button.addEventListener("click", () => {
    activeCategory = button.dataset.category;
    document.querySelectorAll("[data-category]").forEach((chip) => chip.classList.toggle("is-active", chip === button));
    renderProducts();
  });
});

document.querySelectorAll("[data-nav-category]").forEach((link) => {
  link.addEventListener("click", () => {
    activeCategory = link.dataset.navCategory;
    document.querySelectorAll("[data-category]").forEach((chip) => chip.classList.toggle("is-active", chip.dataset.category === activeCategory));
    renderProducts();
  });
});

searchInput.addEventListener("input", renderProducts);
sortSelect.addEventListener("change", renderProducts);
document.querySelector("#clearSearch").addEventListener("click", () => {
  searchInput.value = "";
  activeCategory = "All";
  priceRange.value = priceRange.max;
  document.querySelector("#priceValue").value = `€${priceRange.value}`;
  favoritesOnly = false;
  sortSelect.value = "featured";
  document.querySelectorAll("[data-category]").forEach((chip) => chip.classList.toggle("is-active", chip.dataset.category === "All"));
  renderProducts();
});
favoritesOnlyButton.addEventListener("click", () => {
  favoritesOnly = !favoritesOnly;
  renderProducts();
});
function setProductLayout(layout) {
  const isList = layout === "list";
  productGrid.classList.toggle("is-list-view", isList);
  productListView.classList.toggle("is-active", isList);
  productListView.setAttribute("aria-pressed", String(isList));
  productGridView.classList.toggle("is-active", !isList);
  productGridView.setAttribute("aria-pressed", String(!isList));
}
productGridView.addEventListener("click", () => setProductLayout("grid"));
productListView.addEventListener("click", () => setProductLayout("list"));
function setMotionEnabled(enabled) {
  motionEnabled = enabled;
  document.body.classList.toggle("motion-paused", !enabled);
  motionToggle.setAttribute("aria-pressed", String(enabled));
  motionToggle.querySelector("span:last-child").textContent = enabled ? "3D on" : "3D off";
}
setMotionEnabled(motionEnabled);
motionToggle.addEventListener("click", () => setMotionEnabled(!motionEnabled));
priceRange.addEventListener("input", () => {
  document.querySelector("#priceValue").value = `€${priceRange.value}`;
  renderProducts();
});
document.querySelector("#productDialogAdd").addEventListener("click", () => {
  if (!activeProductSku) return;
  addToCart(activeProductSku);
  document.querySelector("#productDialog").close();
});
document.querySelector("#productDialogFavorite").addEventListener("click", () => {
  if (!activeProductSku) return;
  toggleFavorite(activeProductSku);
  const isSaved = favorites.includes(activeProductSku);
  const button = document.querySelector("#productDialogFavorite");
  button.textContent = isSaved ? "♥ Saved" : "♡ Save";
  button.classList.toggle("is-saved", isSaved);
  button.setAttribute("aria-pressed", String(isSaved));
});

productGrid.addEventListener("click", (event) => {
  const button = event.target.closest("[data-add]");
  const favoriteButton = event.target.closest("[data-favorite]");
  const viewButton = event.target.closest("[data-view]");
  if (button) addToCart(button.dataset.add);
  else if (favoriteButton) toggleFavorite(favoriteButton.dataset.favorite);
  else if (viewButton) openProductDialog(viewButton.dataset.view);
});

productGrid.addEventListener("pointermove", (event) => {
  if (!motionEnabled || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
  const visual = event.target.closest(".product-visual");
  if (!visual) return;
  const bounds = visual.getBoundingClientRect();
  const horizontal = (event.clientX - bounds.left) / bounds.width - 0.5;
  const vertical = (event.clientY - bounds.top) / bounds.height - 0.5;
  visual.style.setProperty("--tilt-x", `${(horizontal * 8).toFixed(2)}deg`);
  visual.style.setProperty("--tilt-y", `${(-vertical * 8).toFixed(2)}deg`);
});
productGrid.addEventListener("pointerout", (event) => {
  const visual = event.target.closest(".product-visual");
  if (!visual || (event.relatedTarget instanceof Node && visual.contains(event.relatedTarget))) return;
  visual.style.removeProperty("--tilt-x");
  visual.style.removeProperty("--tilt-y");
});
const heroArt = document.querySelector(".hero-art");
heroArt.addEventListener("pointermove", (event) => {
  if (!motionEnabled || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
  const bounds = heroArt.getBoundingClientRect();
  const horizontal = (event.clientX - bounds.left) / bounds.width - 0.5;
  const vertical = (event.clientY - bounds.top) / bounds.height - 0.5;
  heroArt.style.setProperty("--hero-rotate-x", `${(horizontal * 9).toFixed(2)}deg`);
  heroArt.style.setProperty("--hero-rotate-y", `${(-vertical * 7).toFixed(2)}deg`);
});
heroArt.addEventListener("pointerleave", () => {
  heroArt.style.removeProperty("--hero-rotate-x");
  heroArt.style.removeProperty("--hero-rotate-y");
});

document.querySelector("#openCart").addEventListener("click", () => setDrawerOpen(true));
document.querySelector("#closeCart").addEventListener("click", () => setDrawerOpen(false));
document.querySelector("#continueShopping").addEventListener("click", () => setDrawerOpen(false));
drawerBackdrop.addEventListener("click", () => setDrawerOpen(false));
document.querySelector("#cartItems").addEventListener("click", (event) => {
  const quantityButton = event.target.closest("[data-quantity]");
  const removeButton = event.target.closest("[data-remove]");
  if (removeButton) {
    cart = cart.filter((line) => line.sku !== removeButton.dataset.remove);
  } else if (quantityButton) {
    const line = cart.find((item) => item.sku === quantityButton.dataset.sku);
    if (line) line.quantity += Number(quantityButton.dataset.quantity);
    cart = cart.filter((item) => item.quantity > 0);
  } else {
    return;
  }
  saveCart();
  renderCart();
});

document.querySelector("#startCheckout").addEventListener("click", () => {
  if (!cart.length) return;
  renderReview();
  document.querySelector("#checkoutError").hidden = true;
  setDrawerOpen(false);
  document.querySelector("#checkoutDialog").showModal();
});

document.querySelector("#checkoutForm").addEventListener("change", (event) => {
  if (event.target.name !== "paymentMethod") return;
  syncPaymentSelection();
  renderReview();
});

syncPaymentSelection();
renderReview();

document.querySelector("#checkoutForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!cart.length) return;
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.querySelector("#placeOrder");
  const errorBox = document.querySelector("#checkoutError");
  const email = formData.get("email").toString().trim();
  const signature = JSON.stringify([...cart].sort((a, b) => a.sku.localeCompare(b.sku)));
  const keyName = `maltashop-checkout:${email}:${signature}`;
  let idempotencyKey = sessionStorage.getItem(keyName);
  if (!idempotencyKey) {
    idempotencyKey = globalThis.crypto?.randomUUID?.() || `cart-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    sessionStorage.setItem(keyName, idempotencyKey);
  }
  button.disabled = true;
  button.classList.add("is-busy");
  button.textContent = "Saving your order…";
  errorBox.hidden = true;

  try {
    const response = await fetch("/orders/batch", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Correlation-ID": createCorrelationId()
      },
      body: JSON.stringify({
        customer_id: email,
        full_name: formData.get("fullName").toString().trim(),
        phone: formData.get("phone").toString().trim(),
        address: formData.get("address").toString().trim(),
        city: formData.get("city").toString().trim(),
        postal_code: formData.get("postalCode").toString().trim(),
        payment_method: formData.get("paymentMethod").toString(),
        items: cart.map((line) => ({ sku: line.sku, quantity: line.quantity }))
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "We couldn’t place that order. Please try again.");
    if (!Array.isArray(result.orders) || result.orders.length !== cart.length) {
      throw new Error("The service returned an unexpected order confirmation. Your bag is still saved; please contact the shop before retrying.");
    }

    sessionStorage.removeItem(keyName);
    cart = [];
    saveCart();
    renderCart();
    document.querySelector("#checkoutDialog").close();
    renderConfirmation(result.orders, {
      full_name: formData.get("fullName").toString().trim(),
      address: formData.get("address").toString().trim(),
      city: formData.get("city").toString().trim(),
      postal_code: formData.get("postalCode").toString().trim(),
      email,
      phone: formData.get("phone").toString().trim(),
      payment_method: formData.get("paymentMethod").toString()
    });
  } catch (error) {
    errorBox.textContent = error.message || "We couldn’t reach the order service. Your bag is saved so you can safely try again.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
    button.classList.remove("is-busy");
    button.innerHTML = 'Place demo order <span aria-hidden="true">→</span>';
  }
});

document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close());
});
document.querySelectorAll("dialog").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});

const welcomeDialog = document.querySelector("#welcomeDialog");
function closeWelcomeDialog() {
  welcomeDialog.close();
}

document.querySelector("#welcomeShopNow").addEventListener("click", () => {
  closeWelcomeDialog();
  document.querySelector("#shop").scrollIntoView({ behavior: "smooth" });
});
document.querySelector("#welcomeNeverShow").addEventListener("click", () => {
  try {
    localStorage.setItem("maltashop-welcome-dismissed", "true");
  } catch (error) {
    console.error("Could not save the welcome preference:", error);
    showToast("Your browser couldn’t save this preference. The welcome message may appear next time.");
  }
  closeWelcomeDialog();
});

document.querySelector("#trackForm").addEventListener("submit", (event) => {
  event.preventDefault();
  lookupOrder(new FormData(event.currentTarget).get("orderId").toString());
});
document.querySelector("#myOrdersForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  loadMyOrders(data.get("email").toString().trim(), data.get("phone").toString().trim());
});
document.querySelector("#complaintForm").addEventListener("submit", submitComplaint);
document.querySelector("#complaintType").addEventListener("change", syncComplaintType);
document.querySelector("#openMyOrders").addEventListener("click", () => openMyOrders());
document.querySelector("#openMyOrdersFooter").addEventListener("click", () => openMyOrders());
document.querySelector("#openComplaints").addEventListener("click", () => openMyOrders());
document.querySelector("#confirmCancelOrder").addEventListener("click", confirmCancelOrder);
document.querySelector("#openTrack").addEventListener("click", () => openTrackDialog());
document.querySelector("#deliveryTrack").addEventListener("click", () => openTrackDialog());
document.querySelector("#viewMyOrdersAfterCheckout").addEventListener("click", () => {
  document.querySelector("#confirmationDialog").close();
  openMyOrders(lastCustomerDetails?.email || "", lastCustomerDetails?.phone || "");
});
document.querySelector("#trackNewOrder").addEventListener("click", () => {
  document.querySelector("#confirmationDialog").close();
  openTrackDialog(lastOrderIds[0] || "");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && cartDrawer.classList.contains("is-open")) setDrawerOpen(false);
  if (event.key === "Tab" && cartDrawer.classList.contains("is-open")) {
    const focusable = [...cartDrawer.querySelectorAll("button:not(:disabled), input, select, a[href]")];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});

renderProducts();
renderCart();
try {
  if (localStorage.getItem("maltashop-welcome-dismissed") !== "true") {
    welcomeDialog.showModal();
  }
} catch (error) {
  console.error("Could not read the welcome preference:", error);
  welcomeDialog.showModal();
}

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

const STAFF_ROLES = [
  "admin",
  "product_management_officer",
  "inventory_manager",
  "order_fulfillment_officer",
  "finance_officer"
];
const ROLE_LABELS = {
  admin: "administrator",
  product_management_officer: "product management officer",
  inventory_manager: "inventory manager",
  order_fulfillment_officer: "order fulfillment officer",
  finance_officer: "finance officer"
};

let products = [...featuredProducts, ...additionalProducts];
const money = new Intl.NumberFormat("en-MT", { style: "currency", currency: "EUR" });
let productBySku = new Map(products.map((product) => [product.sku, product]));
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
let authenticatedUser = null;
let cart = loadCart();
let favorites = loadFavorites();
let favoritesOnly = false;
let motionEnabled = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let activeProductSku = null;
let reviewAfterLoginSku = null;
let toastTimer;
let lastOrderIds = [];
let lastCustomerDetails = null;
let activeMyOrdersCredentials = null;
let pendingCancellation = null;
let inventory = [];
let managementUsers = [];
let checkoutAfterLogin = false;
let accountFlow = "account";
let pendingResetToken = new URLSearchParams(window.location.hash.slice(1)).get("reset-token");
const deliveryLocationWatches = new Map();
let trackLocationPollTimer = null;
let myOrdersLocationPollTimer = null;
let trackedOrderId = null;

function loadCart() {
  try {
    const key = authenticatedUser ? `maltashop-cart:${authenticatedUser.id}` : "maltashop-cart";
    const saved = JSON.parse(localStorage.getItem(key) || "[]");
    if (!Array.isArray(saved)) throw new TypeError("Saved cart must be a list");
    return saved.filter((line) => productBySku.has(line.sku) && Number.isInteger(line.quantity) && line.quantity > 0 && line.quantity <= 100);
  } catch (error) {
    console.error("Could not restore the saved shopping bag:", error);
    return [];
  }
}

function saveCart() {
  try {
    const key = authenticatedUser ? `maltashop-cart:${authenticatedUser.id}` : "maltashop-cart";
    localStorage.setItem(key, JSON.stringify(cart));
  } catch (error) {
    console.error("Could not save the shopping bag:", error);
    showToast("Your browser couldn’t save this bag. Keep this tab open while you shop.");
  }
}

function switchCartToAuthenticatedUser(previousCart) {
  const accountCart = loadCart();
  const quantities = new Map(accountCart.map((line) => [line.sku, line.quantity]));
  for (const line of previousCart) {
    const product = productBySku.get(line.sku);
    if (!product || product.active === false) continue;
    const stockLimit = Number.isInteger(product.stock) ? product.stock : 100;
    if (stockLimit <= 0) continue;
    const quantity = Math.min(100, stockLimit, (quantities.get(line.sku) || 0) + line.quantity);
    quantities.set(line.sku, quantity);
  }
  cart = [...quantities].map(([sku, quantity]) => ({ sku, quantity }));
  saveCart();
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

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  })[character]);
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
      <div class="product-visual" style="--product-bg:${product.bg || "#e5d7c6"}">
        <img src="${escapeHtml(product.image)}" alt="" loading="lazy">
        <span class="product-tag">${escapeHtml(product.tag)}</span>
        <button class="favorite-button${favorites.includes(product.sku) ? " is-saved" : ""}" type="button" data-favorite="${escapeHtml(product.sku)}" aria-label="${favorites.includes(product.sku) ? "Remove" : "Save"} ${escapeHtml(product.name)} ${favorites.includes(product.sku) ? "from" : "to"} favourites" aria-pressed="${favorites.includes(product.sku)}">${favorites.includes(product.sku) ? "♥" : "♡"}</button>
        <button class="quick-view" type="button" data-view="${escapeHtml(product.sku)}">Quick view</button>
        <button class="quick-add" type="button" data-add="${escapeHtml(product.sku)}" aria-label="Add ${escapeHtml(product.name)} to bag" ${product.stock <= 0 ? "disabled" : ""}>+</button>
      </div>
      <div class="product-meta">
        <div>
          <h3>${escapeHtml(product.name)}</h3>
          <p class="product-category">${escapeHtml(product.category)} · ${escapeHtml(product.sku)}</p>
          ${product.review_count
            ? `<p class="product-rating" aria-label="${Number(product.average_rating).toFixed(1)} out of 5 from ${product.review_count} reviews"><span aria-hidden="true">★</span> ${Number(product.average_rating).toFixed(1)} <span>(${product.review_count})</span></p>`
            : '<p class="product-rating is-unrated">Be the first to review</p>'}
          ${product.stock > 0
            ? `<p class="product-stock" aria-label="Available stock: ${product.stock}"><span class="stock-indicator" aria-hidden="true"></span>Available: ${product.stock}</p>`
            : '<p class="product-stock is-out-of-stock"><span class="stock-indicator" aria-hidden="true"></span>Out of stock</p>'}
          <p class="product-delivery">Estimated delivery: 2–5 working days</p>
        </div>
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
    <div><span>Product code</span><strong>${escapeHtml(product.sku)}</strong></div>
    <div><span>Category</span><strong>${escapeHtml(product.category)}</strong></div>
    <div><span>Available stock</span><strong>${product.stock > 0 ? product.stock : "Out of stock"}</strong></div>
    <div><span>Delivery estimate</span><strong>2–5 working days</strong></div>
    <p>Estimated after checkout, Monday to Friday, across Malta and Gozo. Actual delivery time may vary.</p>
  `;
  document.querySelector("#productReviewSummary").textContent = "";
  document.querySelector("#productReviewList").replaceChildren();
  document.querySelector("#productReviewNotice").textContent = "Loading reviews…";
  document.querySelector("#productReviewNotice").hidden = false;
  document.querySelector("#productReviewForm").hidden = true;
  document.querySelector("#reviewSignIn").hidden = true;
  document.querySelector("#productReviewError").hidden = true;
  const favoriteButton = document.querySelector("#productDialogFavorite");
  const isSaved = favorites.includes(sku);
  favoriteButton.textContent = isSaved ? "♥ Saved" : "♡ Save";
  favoriteButton.classList.toggle("is-saved", isSaved);
  favoriteButton.setAttribute("aria-pressed", String(isSaved));
  document.querySelector("#productDialog").showModal();
  loadProductReviews(sku);
}

async function loadProductReviews(sku) {
  const notice = document.querySelector("#productReviewNotice");
  const list = document.querySelector("#productReviewList");
  const summary = document.querySelector("#productReviewSummary");
  const form = document.querySelector("#productReviewForm");
  const signInButton = document.querySelector("#reviewSignIn");
  const errorBox = document.querySelector("#productReviewError");
  try {
    const result = await sendJson(`/products/${encodeURIComponent(sku)}/reviews`, null, "GET");
    if (activeProductSku !== sku) return;
    summary.textContent = result.review_count
      ? `★ ${Number(result.average_rating).toFixed(1)} · ${result.review_count} ${result.review_count === 1 ? "review" : "reviews"}`
      : "No reviews yet";
    list.replaceChildren(...result.reviews.map((review) => {
      const article = document.createElement("article");
      article.className = "product-review";
      const heading = document.createElement("div");
      heading.className = "product-review-heading";
      const author = document.createElement("strong");
      author.textContent = review.reviewer;
      const stars = document.createElement("span");
      stars.className = "review-stars";
      stars.setAttribute("aria-label", `${review.rating} out of 5 stars`);
      stars.textContent = `${"★".repeat(review.rating)}${"☆".repeat(5 - review.rating)}`;
      const comment = document.createElement("p");
      comment.textContent = review.comment;
      heading.append(author, stars);
      article.append(heading, comment);
      return article;
    }));
    notice.hidden = result.review_count !== 0;
    notice.textContent = "No reviews yet. Your experience can be the first.";
    if (!authenticatedUser) {
      signInButton.hidden = false;
      notice.hidden = false;
      notice.textContent = result.review_count
        ? "Bought and received this item? Log in to share your review."
        : "Bought and received this item? Log in to leave the first review.";
      return;
    }
    if (authenticatedUser.role !== "customer") {
      notice.hidden = false;
      notice.textContent = "Product reviews are available to customer accounts.";
      return;
    }
    const eligibility = await sendJson(
      `/products/${encodeURIComponent(sku)}/review-eligibility`,
      null,
      "GET"
    );
    if (activeProductSku !== sku) return;
    if (eligibility.review) {
      notice.hidden = false;
      notice.textContent = `Your review: ${"★".repeat(eligibility.review.rating)}${"☆".repeat(5 - eligibility.review.rating)} — ${eligibility.review.comment}`;
    } else if (eligibility.eligible) {
      notice.hidden = true;
      form.hidden = false;
    } else {
      notice.hidden = false;
      notice.textContent = eligibility.delivered
        ? "You have already reviewed this item."
        : "You can leave a review after this product has been delivered to you.";
    }
  } catch (error) {
    if (activeProductSku !== sku) return;
    errorBox.textContent = error.message || "Could not load product reviews.";
    errorBox.hidden = false;
    notice.textContent = "Reviews could not be loaded. Please try again.";
  }
}

async function submitProductReview(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.querySelector("#submitProductReview");
  const errorBox = document.querySelector("#productReviewError");
  errorBox.hidden = true;
  button.disabled = true;
  try {
    await sendJson(`/products/${encodeURIComponent(activeProductSku)}/reviews`, {
      rating: Number(formData.get("rating")),
      comment: formData.get("comment").toString().trim()
    });
    form.reset();
    showToast("Thanks for sharing your product review.");
    await loadProductReviews(activeProductSku);
  } catch (error) {
    errorBox.textContent = error.message || "Your review could not be saved.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
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
  document.querySelector("#openCart").setAttribute("aria-label", quantity ? `Open cart, ${quantity} ${quantity === 1 ? "item" : "items"}` : "Open cart");
  document.querySelector("#drawerCount").textContent = quantity ? `(${quantity})` : "";
  document.querySelector("#cartSubtotal").textContent = money.format(cartTotal());
  document.querySelector("#cartEmpty").hidden = quantity > 0;
  document.querySelector("#cartSummary").hidden = quantity === 0;
  document.querySelector("#cartItems").innerHTML = cart.map((line) => {
    const product = productBySku.get(line.sku);
    return `
      <article class="cart-line">
        <div class="cart-line-image" style="--product-bg:${product.bg || "#e5d7c6"}">
          <img src="${escapeHtml(product.image)}" alt="" loading="lazy">
        </div>
        <div class="cart-line-main">
          <h3>${escapeHtml(product.name)}</h3>
          <p>${money.format(product.price)} each</p>
          <div class="quantity-control" aria-label="Quantity for ${escapeHtml(product.name)}">
            <button type="button" data-quantity="-1" data-sku="${escapeHtml(product.sku)}" aria-label="Remove one ${escapeHtml(product.name)}">−</button>
            <span>${line.quantity}</span>
            <button type="button" data-quantity="1" data-sku="${escapeHtml(product.sku)}" aria-label="Add one ${escapeHtml(product.name)}">+</button>
          </div>
        </div>
        <div class="cart-line-end">
          <strong>${money.format(product.price * line.quantity)}</strong>
          <button class="remove-item" type="button" data-remove="${escapeHtml(product.sku)}">Remove</button>
        </div>
      </article>
    `;
  }).join("");
  document.querySelectorAll(".cart-line-image img").forEach((image) => {
    image.addEventListener("error", () => image.remove(), { once: true });
  });
}

function addToCart(sku) {
  const product = productBySku.get(sku);
  if (!product || !product.active || product.stock <= 0) {
    showToast("This product is no longer available.");
    return;
  }
  const line = cart.find((item) => item.sku === sku);
  if (line) {
    if (line.quantity >= Math.min(100, product.stock)) {
      showToast("There is not enough stock for that quantity.");
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

function setPasswordVisibility(button, visible) {
  const input = document.getElementById(button.dataset.passwordTarget);
  input.type = visible ? "text" : "password";
  button.classList.toggle("is-visible", visible);
  button.setAttribute("aria-pressed", String(visible));
  button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
}
function openAccountDialog({ afterLogin = false } = {}) {
  checkoutAfterLogin = afterLogin;
  accountFlow = "account";
  setPasswordVisibility(document.querySelector('[data-password-target="accountPassword"]'), false);
  document.querySelector("#accountError").hidden = true;
  document.querySelector("#accountMessage").hidden = true;
  document.querySelector("#accountEmail").value = authenticatedUser?.email || "";
  syncAccountMode();
  document.querySelector("#accountDialog").showModal();
}

function renderAccountState() {
  const loggedIn = Boolean(authenticatedUser);
  const isStaff = loggedIn && STAFF_ROLES.includes(authenticatedUser.role);
  document.querySelector("#accountButton").hidden = loggedIn;
  document.querySelector("#accountButton").textContent = "Log in";
  document.querySelector("#logoutButton").hidden = !loggedIn;
  document.querySelector("#myOrdersButton").hidden = !loggedIn;
  document.querySelector("#managementButton").hidden = !isStaff;
  if (loggedIn) {
    document.querySelector("#accountButton").textContent = authenticatedUser.full_name;
    document.querySelector("#logoutButton").textContent = "Log out";
  }
}

async function loadStorefrontProducts() {
  const response = await fetch("/products");
  const result = await response.json();
  if (!response.ok || !Array.isArray(result.products)) {
    throw new Error(result.detail || "The product catalog could not be loaded.");
  }
  const oldProducts = productBySku;
  products = result.products.map((product) => ({
    ...product,
    bg: oldProducts.get(product.sku)?.bg || "#e5d7c6"
  }));
  productBySku = new Map(products.map((product) => [product.sku, product]));
  cart = loadCart();
  favorites = [...new Set(favorites.filter((sku) => productBySku.has(sku)))];
  updateCategoryFilters();
  renderProducts();
  renderCart();
}

function updateCategoryFilters() {
  const group = document.querySelector(".category-filters");
  const current = activeCategory;
  const categories = [...new Set(products.map((product) => product.category))].sort();
  const options = ["All", ...categories];
  if (!options.includes(current)) activeCategory = "All";
  group.replaceChildren(...options.map((category) => {
    const button = document.createElement("button");
    button.className = `filter-chip${activeCategory === category ? " is-active" : ""}`;
    button.type = "button";
    button.dataset.category = category;
    button.textContent = category === "All" ? "Everything" : category;
    button.addEventListener("click", () => {
      activeCategory = category;
      group.querySelectorAll("[data-category]").forEach((item) => item.classList.toggle("is-active", item === button));
      renderProducts();
    });
    return button;
  }));
}

async function loadAuthenticatedUser() {
  const response = await fetch("/auth/me");
  if (response.status === 401) {
    authenticatedUser = null;
    renderAccountState();
    return;
  }
  const user = await response.json();
  if (!response.ok) throw new Error(user.detail || "Could not load the signed-in account.");
  authenticatedUser = user;
  renderAccountState();
}

async function sendJson(url, body, method = "POST") {
  const options = { method };
  if (method !== "GET") {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const result = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new Error(result.detail || "The request could not be completed.");
  return result;
}

function syncAccountMode() {
  const accountForm = document.querySelector("#accountForm");
  const forgotPasswordForm = document.querySelector("#forgotPasswordForm");
  const resetPasswordForm = document.querySelector("#resetPasswordForm");
  accountForm.hidden = accountFlow !== "account";
  forgotPasswordForm.hidden = accountFlow !== "forgot";
  resetPasswordForm.hidden = accountFlow !== "reset";
  const title = document.querySelector("#accountTitle");
  const intro = document.querySelector("#accountIntro");
  if (accountFlow === "forgot") {
    title.textContent = "Forgot your password?";
    intro.textContent = "Enter your account email and we’ll send a one-time reset link if it matches an active account.";
    return;
  }
  if (accountFlow === "reset") {
    title.textContent = "Choose a new password";
    intro.textContent = "Set a new password for your account.";
    return;
  }
  const registering = document.querySelector("#accountMode").value === "register";
  const nameField = document.querySelector("#accountNameField");
  nameField.hidden = !registering;
  document.querySelector("#accountName").required = registering;
  document.querySelector("#accountPassword").autocomplete = registering ? "new-password" : "current-password";
  document.querySelector("#forgotPasswordLink").hidden = registering;
  document.querySelector("#accountSubmit").innerHTML =
    `${registering ? "Create account" : "Log in"} <span aria-hidden="true">→</span>`;
  title.innerHTML = registering ? "Join the <em>islands.</em>" : "Welcome <em>in.</em>";
  intro.textContent = "Log in or create an account to place an order and see your orders.";
}
function showForgotPassword() {
  accountFlow = "forgot";
  document.querySelector("#resetRequestEmail").value = document.querySelector("#accountEmail").value.trim();
  document.querySelector("#forgotPasswordError").hidden = true;
  document.querySelector("#forgotPasswordMessage").hidden = true;
  syncAccountMode();
  document.querySelector("#resetRequestEmail").focus();
}

async function submitPasswordResetRequest(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#forgotPasswordSubmit");
  const errorBox = document.querySelector("#forgotPasswordError");
  const message = document.querySelector("#forgotPasswordMessage");
  errorBox.hidden = true;
  message.hidden = true;
  button.disabled = true;
  try {
    const email = new FormData(form).get("email").toString().trim();
    await sendJson("/auth/password-reset/request", { email });
    message.textContent = "If an active account exists for that email, a reset link will be sent. Check your inbox.";
    message.hidden = false;
  } catch (error) {
    errorBox.textContent = error.message || "Could not request a reset link. Please try again.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function submitPasswordReset(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.querySelector("#resetPasswordSubmit");
  const errorBox = document.querySelector("#resetPasswordError");
  errorBox.hidden = true;
  if (formData.get("password") !== formData.get("confirmPassword")) {
    errorBox.textContent = "The passwords do not match.";
    errorBox.hidden = false;
    return;
  }
  button.disabled = true;
  try {
    await sendJson("/auth/password-reset/confirm", {
      token: pendingResetToken,
      password: formData.get("password").toString()
    });
    pendingResetToken = null;
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    accountFlow = "account";
    document.querySelector("#accountMode").value = "login";
    document.querySelector("#accountForm").reset();
    document.querySelector("#accountMessage").textContent = "Your password has been updated. Please log in.";
    document.querySelector("#accountMessage").hidden = false;
    syncAccountMode();
  } catch (error) {
    errorBox.textContent = error.message || "Could not update your password. Request a new reset link.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function submitAccount(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.querySelector("#accountSubmit");
  const errorBox = document.querySelector("#accountError");
  const registering = formData.get("mode") === "register";
  const body = {
    email: formData.get("email").toString().trim(),
    password: formData.get("password").toString()
  };
  if (registering) body.full_name = formData.get("fullName").toString().trim();
  errorBox.hidden = true;
  button.disabled = true;
  try {
    const previousCart = cart;
    authenticatedUser = await sendJson(registering ? "/auth/register" : "/auth/login", body);
    switchCartToAuthenticatedUser(previousCart);
    renderCart();
    renderAccountState();
    document.querySelector("#accountDialog").close();
    showToast(`Welcome, ${authenticatedUser.full_name}.`);
    const reviewSku = reviewAfterLoginSku;
    reviewAfterLoginSku = null;
    if (reviewSku) openProductDialog(reviewSku);
    const continueToCheckout = checkoutAfterLogin;
    checkoutAfterLogin = false;
    if (continueToCheckout) document.querySelector("#startCheckout").click();
  } catch (error) {
    errorBox.textContent = error.message || "Account sign-in failed.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function logout() {
  try {
    await sendJson("/auth/logout", {});
    authenticatedUser = null;
    cart = [];
    saveCart();
    renderCart();
    renderAccountState();
    document.querySelector("#managementDialog").close();
    document.querySelector("#myOrdersDialog").close();
    showToast("You have logged out.");
  } catch (error) {
    showToast(error.message || "Could not log out. Please try again.");
  }
}

function addManagementUserRow(user) {
  const row = document.createElement("article");
  row.className = "management-row";
  const details = document.createElement("span");
  details.textContent = `${user.full_name} · ${user.email}${user.is_active ? "" : " · inactive"}`;
  const role = document.createElement("select");
  role.className = "form-input";
  role.setAttribute("aria-label", `Role for ${user.email}`);
  for (const [value, label] of [
    ["customer", "Customer"],
    ["product_management_officer", "Product officer"],
    ["inventory_manager", "Inventory manager"],
    ["order_fulfillment_officer", "Order fulfillment"],
    ["finance_officer", "Finance officer"],
    ["admin", "Admin"]
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = user.role === value;
    role.append(option);
  }
  const active = document.createElement("select");
  active.className = "form-input";
  active.setAttribute("aria-label", `Status for ${user.email}`);
  for (const [value, label] of [["true", "Active"], ["false", "Inactive"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = user.is_active === (value === "true");
    active.append(option);
  }
  const save = document.createElement("button");
  save.className = "button button-outline";
  save.type = "button";
  save.textContent = "Save";
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await sendJson(`/admin/users/${encodeURIComponent(user.id)}`, {
        role: role.value, is_active: active.value === "true"
      }, "PATCH");
      showToast("User access updated.");
      await loadManagementUsers();
    } catch (error) {
      showToast(error.message || "Could not update user access.");
    } finally {
      save.disabled = false;
    }
  });
  row.append(details, role, active, save);
  return row;
}

async function loadManagementUsers() {
  const result = await sendJson("/admin/users", null, "GET");
  managementUsers = result.users;
  const container = document.querySelector("#adminUsersList");
  container.replaceChildren(...managementUsers.map(addManagementUserRow));
}

function renderAdminOrders(orders) {
  const container = document.querySelector("#adminOrdersList");
  container.replaceChildren();
  if (!orders.length) {
    container.textContent = "No orders have been placed.";
    return;
  }
  for (const order of orders) {
    const row = document.createElement("article");
    row.className = "management-row";
    row.textContent =
      `${order.created_at || "Date unavailable"} · ${order.full_name || order.customer_email} · ` +
      `${order.product_name} × ${order.quantity} · €${Number(order.unit_price).toFixed(2)} · ${order.status}`;
    container.append(row);
  }
}

function renderStaffComplaints(complaints) {
  const container = document.querySelector("#staffComplaints");
  container.replaceChildren();
  if (!complaints.length) {
    container.textContent = "No customer reports yet. New reports will appear here.";
    return;
  }
  for (const complaint of complaints) {
    const card = document.createElement("article");
    card.className = "management-task-card complaint-card";
    const title = document.createElement("h4");
    const statusLabel = ({ OPEN: "Open", IN_PROGRESS: "In progress", RESOLVED: "Resolved" })[complaint.status] || complaint.status;
    title.textContent = `${complaint.complaint_type === "product" ? "Product" : "Delivery"} report · ${statusLabel}`;
    const details = document.createElement("p");
    details.textContent = `${complaint.customer_name || complaint.customer_email || "Customer"} · ${complaint.customer_email || ""} · ${new Date(complaint.created_at).toLocaleString()}`;
    const order = document.createElement("p");
    order.textContent = `Order ${complaint.correlation_id}${complaint.product_sku ? ` · Item ${complaint.product_sku}` : ""}`;
    const message = document.createElement("p");
    message.className = "complaint-message-text";
    message.textContent = complaint.message;
    const controls = document.createElement("div");
    controls.className = "fulfillment-controls";
    const status = document.createElement("select");
    status.className = "form-input";
    status.setAttribute("aria-label", "Complaint status");
    for (const [value, label] of [["OPEN", "Open"], ["IN_PROGRESS", "In progress"], ["RESOLVED", "Resolved"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = complaint.status === value;
      status.append(option);
    }
    const note = document.createElement("input");
    note.className = "form-input";
    note.maxLength = 2000;
    note.value = complaint.staff_note || "";
    note.placeholder = "Internal resolution note (optional)";
    note.setAttribute("aria-label", "Internal resolution note");
    const save = document.createElement("button");
    save.className = "button button-outline";
    save.type = "button";
    save.textContent = "Save update";
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        await sendJson(`/staff/complaints/${encodeURIComponent(complaint.id)}`, {
          status: status.value, staff_note: note.value
        }, "PATCH");
        showToast("Customer report updated.");
        await loadStaffComplaints();
      } catch (error) {
        showToast(error.message || "Could not update this report.");
      } finally {
        save.disabled = false;
      }
    });
    controls.append(status, note, save);
    card.append(title, details, order, message, controls);
    container.append(card);
  }
}

async function loadStaffComplaints() {
  const result = await sendJson("/staff/complaints", null, "GET");
  renderStaffComplaints(result.complaints);
}

function populateManagedProduct(product) {
  if (!product) return;
  document.querySelector("#manageProductCategory").value = product.category;
  document.querySelector("#manageProductPrice").value = product.price.toFixed(2);
  document.querySelector("#manageProductStock").value = product.stock;
  document.querySelector("#manageProductActive").value = String(product.active);
}

async function loadManagementProducts() {
  const result = await sendJson("/admin/products", null, "GET");
  inventory = result.products;
  const select = document.querySelector("#managementProductSelect");
  select.replaceChildren(...inventory.map((product) => {
    const option = document.createElement("option");
    option.value = product.sku;
    option.textContent = `${product.name} · ${product.sku} · ${product.stock} in stock`;
    return option;
  }));
  populateManagedProduct(inventory[0]);
}

function statusLabel(status) {
  return ({
    PENDING: "Order received",
    RECEIVED: "Accepted for fulfillment",
    DISPATCHED: "Sent to delivery facility",
    DELIVERED: "Delivered",
    CANCELLED: "Cancelled"
  })[status] || status;
}

function renderFulfillmentOrders(orders) {
  const container = document.querySelector("#fulfillmentOrders");
  container.replaceChildren();
  if (!orders.length) {
    container.textContent = "No active orders are waiting for fulfillment.";
    return;
  }
  for (const order of orders) {
    const row = document.createElement("article");
    row.className = "management-task-card";
    const heading = document.createElement("h4");
    heading.textContent = `${order.full_name || order.customer_email} · ${statusLabel(order.status)}`;
    const details = document.createElement("p");
    details.textContent =
      `${order.items.map((item) => `${item.name} × ${item.quantity}`).join(", ")} · ` +
      `${order.address}, ${order.city} ${order.postal_code} · ${order.phone}`;
    row.append(heading, details);
    if (order.facility || order.tracking_reference) {
      const tracking = document.createElement("p");
      tracking.textContent = `Facility: ${order.facility || "—"} · Tracking: ${order.tracking_reference || "—"}`;
      row.append(tracking);
    }
    if (order.status === "DISPATCHED") {
      renderDeliveryLocationControls(order, row);
    }

    const next = {
      PENDING: "RECEIVED",
      RECEIVED: "DISPATCHED",
      DISPATCHED: "DELIVERED"
    }[order.status];
    if (next) {
      const controls = document.createElement("div");
      controls.className = "fulfillment-controls";
      let facilityInput;
      let trackingInput;
      if (next === "DISPATCHED") {
        facilityInput = document.createElement("input");
        facilityInput.className = "form-input";
        facilityInput.placeholder = "Delivery facility";
        facilityInput.setAttribute("aria-label", "Delivery facility");
        facilityInput.required = true;
        trackingInput = document.createElement("input");
        trackingInput.className = "form-input";
        trackingInput.placeholder = "Tracking reference";
        trackingInput.setAttribute("aria-label", "Tracking reference");
        trackingInput.required = true;
        controls.append(facilityInput, trackingInput);
      }
      const action = document.createElement("button");
      action.className = "button button-outline";
      action.type = "button";
      action.textContent = ({
        RECEIVED: "Accept order",
        DISPATCHED: "Send to delivery facility",
        DELIVERED: "Confirm delivery"
      })[next];
      action.addEventListener("click", async () => {
        if (next === "DISPATCHED" && (!facilityInput.value.trim() || !trackingInput.value.trim())) {
          showToast("Enter the delivery facility and tracking reference.");
          return;
        }
        action.disabled = true;
        try {
          await sendJson(`/staff/fulfillment/orders/${encodeURIComponent(order.correlation_id)}`, {
            status: next,
            facility: facilityInput?.value.trim() || null,
            tracking_reference: trackingInput?.value.trim() || null
          }, "PATCH");
          if (next === "DELIVERED") {
            const watch = deliveryLocationWatches.get(order.correlation_id);
            if (watch) navigator.geolocation.clearWatch(watch.watchId);
            deliveryLocationWatches.delete(order.correlation_id);
          }
          await loadFulfillmentOrders();
          await loadStorefrontProducts();
          showToast(`Order updated: ${statusLabel(next)}.`);
        } catch (error) {
          showToast(error.message || "Could not update this delivery.");
          action.disabled = false;
        }
      });
      controls.append(action);
      row.append(controls);
    }
    container.append(row);
  }
}

function renderDeliveryLocationControls(order, row) {
  const controls = document.createElement("div");
  controls.className = "delivery-sharing-controls";
  const message = document.createElement("p");
  message.className = "delivery-sharing-note";
  const ownsShare = order.location_shared_by === authenticatedUser?.id;
  const isLive = order.location_status === "live";
  if (isLive && !ownsShare) {
    message.textContent = "Another staff member is currently sharing GPS with this customer.";
  } else if (isLive) {
    message.textContent = `Your device GPS is visible to this customer. Last update: ${formatOrderDate(order.location_updated_at)}.`;
  } else if (order.location_status === "stale") {
    message.textContent = "The last GPS signal expired. The customer cannot see its old coordinates.";
  } else {
    message.textContent = "Share this device’s GPS with the customer only while delivering this order.";
  }
  const action = document.createElement("button");
  action.type = "button";
  action.className = "button button-outline delivery-sharing-action";
  action.textContent = ownsShare && isLive ? "Stop GPS sharing" : "Share my live GPS";
  action.disabled = isLive && !ownsShare;
  action.addEventListener("click", () => {
    if (ownsShare && isLive) {
      stopDeliveryLocationSharing(order, action);
    } else {
      startDeliveryLocationSharing(order, action);
    }
  });
  controls.append(message, action);
  row.append(controls);
}

function locationShareUrl(correlationId) {
  return `/staff/fulfillment/orders/${encodeURIComponent(correlationId)}/location`;
}

function getLocationPermissionError(error) {
  if (error.code === error.PERMISSION_DENIED) {
    return "GPS permission was denied. Allow location access in your browser to share delivery GPS.";
  }
  if (error.code === error.POSITION_UNAVAILABLE) {
    return "Your device could not determine its GPS position. Please try again outdoors.";
  }
  if (error.code === error.TIMEOUT) {
    return "GPS took too long to respond. Please try sharing again.";
  }
  return "Could not read the GPS position from this device.";
}

function readCurrentDeviceLocation() {
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      maximumAge: 0,
      timeout: 20000
    });
  });
}

function locationPayload(position) {
  return {
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    accuracy: position.coords.accuracy
  };
}

async function startDeliveryLocationSharing(order, button) {
  if (!window.isSecureContext || !navigator.geolocation) {
    showToast("Live GPS needs HTTPS and a device/browser that supports location.");
    return;
  }
  button.disabled = true;
  try {
    const position = await readCurrentDeviceLocation();
    await sendJson(locationShareUrl(order.correlation_id), locationPayload(position), "PUT");
    const watchId = navigator.geolocation.watchPosition(
      (nextPosition) => {
        const watch = deliveryLocationWatches.get(order.correlation_id);
        if (!watch || watch.sending || Date.now() - watch.lastSentAt < 15000) return;
        watch.sending = true;
        sendJson(locationShareUrl(order.correlation_id), locationPayload(nextPosition), "PUT")
          .then(() => { watch.lastSentAt = Date.now(); })
          .catch((error) => {
            console.error("Could not update the shared delivery GPS:", error);
            showToast(error.message || "GPS update failed. The location will stop showing as live if updates do not resume.");
          })
          .finally(() => { watch.sending = false; });
      },
      (error) => {
        const watch = deliveryLocationWatches.get(order.correlation_id);
        if (!watch) return;
        showToast(getLocationPermissionError(error));
        stopDeliveryLocationSharing(order, null);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 }
    );
    deliveryLocationWatches.set(order.correlation_id, { watchId, lastSentAt: Date.now(), sending: false });
    showToast("Live GPS sharing started. The customer can see this device’s location.");
    await loadFulfillmentOrders().catch((error) => {
      console.error("Could not refresh the fulfillment list after GPS sharing started:", error);
      showToast("GPS sharing is active, but the staff order list could not refresh.");
    });
  } catch (error) {
    showToast(error.message || "Could not start live GPS sharing.");
    button.disabled = false;
  }
}

async function stopDeliveryLocationSharing(order, button) {
  const watch = deliveryLocationWatches.get(order.correlation_id);
  if (watch) navigator.geolocation.clearWatch(watch.watchId);
  deliveryLocationWatches.delete(order.correlation_id);
  if (button) button.disabled = true;
  try {
    await sendJson(locationShareUrl(order.correlation_id), undefined, "DELETE");
    showToast("Live GPS sharing stopped.");
    await loadFulfillmentOrders().catch((error) => {
      console.error("Could not refresh the fulfillment list after GPS sharing stopped:", error);
      showToast("GPS sharing stopped, but the staff order list could not refresh.");
    });
  } catch (error) {
    console.error("Could not stop the server-side delivery GPS share:", error);
    showToast(`GPS stopped on this device, but the server could not clear the last location: ${error.message || "please retry"}. It will expire automatically.`);
    if (button) button.disabled = false;
  }
}

async function loadFulfillmentOrders() {
  const result = await sendJson("/staff/fulfillment/orders", null, "GET");
  renderFulfillmentOrders(result.orders);
}

function renderFinanceSummary(result) {
  document.querySelector("#financeRecordedRevenue").textContent = money.format(result.summary.recorded_revenue);
  document.querySelector("#financeOutstanding").textContent = money.format(result.summary.outstanding);
  document.querySelector("#financeRefunded").textContent = money.format(result.summary.refunded);
  const container = document.querySelector("#financeOrders");
  container.replaceChildren();
  if (!result.orders.length) {
    container.textContent = "No orders to reconcile.";
    return;
  }
  for (const order of result.orders) {
    const row = document.createElement("article");
    row.className = "management-task-card";
    const heading = document.createElement("h4");
    heading.textContent = `${order.product_name} × ${order.quantity} · ${money.format(order.total)}`;
    const details = document.createElement("p");
    details.textContent =
      `${order.customer_email} · ${order.payment_method} · ${statusLabel(order.status)} · ` +
      `Payment: ${order.payment_status}`;
    row.append(heading, details);
    if (order.payment_status === "UNPAID" && order.status !== "CANCELLED") {
      const paid = document.createElement("button");
      paid.className = "button button-outline";
      paid.type = "button";
      paid.textContent = "Record payment received";
      paid.addEventListener("click", () => updateFinancePayment(order.order_id, "PAID", paid));
      row.append(paid);
    } else if (order.payment_status === "PAID" && order.status === "CANCELLED") {
      const refunded = document.createElement("button");
      refunded.className = "button button-outline";
      refunded.type = "button";
      refunded.textContent = "Record refund issued";
      refunded.addEventListener("click", () => updateFinancePayment(order.order_id, "REFUNDED", refunded));
      row.append(refunded);
    }
    container.append(row);
  }
}

async function updateFinancePayment(orderId, paymentStatus, button) {
  button.disabled = true;
  try {
    await sendJson(`/staff/finance/orders/${encodeURIComponent(orderId)}/payment`, {
      payment_status: paymentStatus
    }, "PATCH");
    const summary = await sendJson("/staff/finance/summary", null, "GET");
    renderFinanceSummary(summary);
    showToast(`Payment marked ${paymentStatus.toLowerCase()}.`);
  } catch (error) {
    button.disabled = false;
    showToast(error.message || "Could not update the payment record.");
  }
}

async function openManagement() {
  if (!authenticatedUser || !STAFF_ROLES.includes(authenticatedUser.role)) {
    showToast("You do not have permission to access management.");
    return;
  }
  const role = authenticatedUser.role;
  const isAdmin = role === "admin";
  const canManageProducts = isAdmin || role === "product_management_officer" || role === "inventory_manager";
  document.querySelector("#managementRole").textContent = `Signed in as ${ROLE_LABELS[role]}.`;
  document.querySelector("#adminUsersSection").hidden = !isAdmin;
  document.querySelector("#productManagementSection").hidden = !canManageProducts;
  document.querySelector("#fulfillmentSection").hidden =
    !isAdmin && role !== "order_fulfillment_officer";
  document.querySelector("#complaintsSection").hidden =
    !isAdmin && role !== "order_fulfillment_officer";
  document.querySelector("#financeSection").hidden = !isAdmin && role !== "finance_officer";
  document.querySelector("#manageProductMetadata").hidden = role === "inventory_manager";
  document.querySelectorAll("#manageProductMetadata input, #manageProductMetadata select").forEach((input) => {
    input.disabled = role === "inventory_manager";
  });
  document.querySelector("#manageProductStockField").hidden =
    role === "product_management_officer";
  document.querySelector("#manageProductStock").disabled = role === "product_management_officer";
  document.querySelector("#productCreateDetails").hidden = role === "inventory_manager";
  try {
    if (canManageProducts) await loadManagementProducts();
    if (role === "inventory_manager") {
      document.querySelector("#productUpdateTitle").textContent = "Update stock quantity";
      document.querySelector("#manageProductStock").required = true;
    } else {
      document.querySelector("#productUpdateTitle").textContent = "Update product details";
      document.querySelector("#manageProductStock").required = role === "admin";
    }
    if (role === "order_fulfillment_officer" || isAdmin) await loadFulfillmentOrders();
    if (role === "order_fulfillment_officer" || isAdmin) await loadStaffComplaints();
    if (role === "finance_officer" || isAdmin) {
      renderFinanceSummary(await sendJson("/staff/finance/summary", null, "GET"));
    }
    if (isAdmin) {
      await loadManagementUsers();
      const orders = await sendJson("/admin/orders", null, "GET");
      renderAdminOrders(orders.orders);
    }
    document.querySelector("#managementDialog").showModal();
  } catch (error) {
    showToast(error.message || "Could not load management tools.");
  }
}

async function refreshProducts() {
  await loadStorefrontProducts();
  await loadManagementProducts();
}

async function updateManagedProduct(event) {
  event.preventDefault();
  const sku = document.querySelector("#managementProductSelect").value;
  const errorBox = document.querySelector("#productManagementError");
  errorBox.hidden = true;
  const role = authenticatedUser.role;
  const body = role === "inventory_manager"
    ? { stock: Number(document.querySelector("#manageProductStock").value) }
    : {
      category: document.querySelector("#manageProductCategory").value.trim(),
      price: Number(document.querySelector("#manageProductPrice").value),
      active: document.querySelector("#manageProductActive").value === "true"
    };
  if (role === "admin") body.stock = Number(document.querySelector("#manageProductStock").value);
  try {
    await sendJson(`/admin/products/${encodeURIComponent(sku)}`, body, "PATCH");
    await refreshProducts();
    showToast(role === "inventory_manager" ? "Stock quantity updated." : "Product details updated.");
  } catch (error) {
    errorBox.textContent = error.message || "Could not update the product.";
    errorBox.hidden = false;
  }
}

async function createManagedProduct(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const errorBox = document.querySelector("#productCreateError");
  errorBox.hidden = true;
  const body = Object.fromEntries(formData.entries());
  body.price = Number(body.price);
  body.stock = 0;
  try {
    await sendJson("/admin/products", body);
    form.reset();
    await refreshProducts();
    document.querySelector("#managementProductSelect").value = body.sku;
    populateManagedProduct(inventory.find((product) => product.sku === body.sku));
    showToast("Product created and added to inventory.");
  } catch (error) {
    errorBox.textContent = error.message || "Could not create the product.";
    errorBox.hidden = false;
  }
}

async function createManagedUser(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  const errorBox = document.querySelector("#managedUserError");
  errorBox.hidden = true;
  try {
    await sendJson("/admin/users", body);
    form.reset();
    await loadManagementUsers();
    showToast("User account created.");
  } catch (error) {
    errorBox.textContent = error.message || "Could not create the user.";
    errorBox.hidden = false;
  }
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
      return `<div class="review-row"><span>${escapeHtml(product.name)} × ${line.quantity}</span><strong>${money.format(product.price * line.quantity)}</strong></div>`;
    }).join("")}
    <div class="review-row review-total"><span>Total</span><strong>${money.format(cartTotal())}</strong></div>
    <div class="review-method">Demo preference <strong>${paymentLabel || "Choose a method"}</strong></div>
  `;
}

function openTrackDialog(orderId = "") {
  if (!authenticatedUser) {
    openAccountDialog();
    showToast("Log in to track your orders.");
    return;
  }
  const input = document.querySelector("#trackOrderId");
  clearInterval(trackLocationPollTimer);
  trackLocationPollTimer = null;
  trackedOrderId = null;
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
  clearInterval(trackLocationPollTimer);
  trackLocationPollTimer = null;
  trackedOrderId = null;
  errorBox.hidden = true;
  result.hidden = true;
  try {
    const response = await fetch(`/orders/${encodeURIComponent(orderId.trim())}`);
    const order = await response.json();
    if (!response.ok) throw new Error(response.status === 404 ? "We couldn’t find that order. Check the ID and try again." : (order.detail || "Order lookup failed."));

    const heading = document.createElement("h3");
    heading.textContent = `Order status: ${statusLabel(order.status)}`;
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
    const tracker = createDeliveryTracker(order.status, order.delivery_facility, order.live_location);
    tracker.dataset.trackOrderId = order.order_id;
    result.append(tracker);
    if (order.delivery_facility || order.delivery_tracking_id) {
      const facility = document.createElement("p");
      facility.innerHTML = "<strong>Delivery facility</strong>";
      const facilityValue = document.createElement("p");
      facilityValue.textContent = order.delivery_facility || "Not assigned";
      const tracking = document.createElement("p");
      tracking.innerHTML = "<strong>Delivery tracking reference</strong>";
      const trackingValue = document.createElement("p");
      trackingValue.textContent = order.delivery_tracking_id || "Not assigned";
      result.append(facility, facilityValue, tracking, trackingValue);
    }
    result.hidden = false;
    trackedOrderId = order.order_id;
    trackLocationPollTimer = setInterval(refreshTrackedOrderLocation, 15000);
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
  const summary = document.querySelector("#myOrdersSummary");
  list.replaceChildren();
  summary.hidden = false;
  const activeOrders = orders.filter(
    (order) => order.status !== "DELIVERED" && order.status !== "CANCELLED"
  ).length;
  const deliveredOrders = orders.filter((order) => order.status === "DELIVERED").length;
  summary.replaceChildren(
    createMyOrderStat("Total orders", orders.length),
    createMyOrderStat("In progress", activeOrders),
    createMyOrderStat("Delivered", deliveredOrders)
  );
  if (!orders.length) {
    const empty = document.createElement("p");
    empty.className = "my-orders-empty";
    empty.textContent = "No orders just yet. Your next good find will show up here.";
    list.append(empty);
    list.hidden = false;
    return;
  }

  orders.forEach((order) => {
    const card = document.createElement("article");
    card.className = "my-order-card";
    card.dataset.correlationId = order.correlation_id;
    const header = document.createElement("div");
    header.className = "my-order-header";
    const title = document.createElement("h3");
    title.textContent = `Order placed ${formatOrderDate(order.created_at)}`;
    const status = document.createElement("span");
    status.className = `my-order-status${order.status === "CANCELLED" ? " is-cancelled" : order.status === "DELIVERED" ? " is-delivered" : order.status === "DISPATCHED" ? " is-dispatched" : ""}`;
    status.textContent = statusLabel(order.status);
    header.append(title, status);

    const identifiers = document.createElement("div");
    identifiers.className = "my-order-identifiers";
    const uniqueOrderIds = [...new Set(order.items.map((item) => item.order_id).filter(Boolean))];
    const uniqueTrackingIds = [...new Set(
      order.items.map((item) => item.delivery_tracking_id).filter(Boolean)
    )];
    uniqueOrderIds.forEach((value) => identifiers.append(createMyOrderReference("Order ID", value)));
    uniqueTrackingIds.forEach((value) => identifiers.append(createMyOrderReference("Tracking ID", value)));
    if (!uniqueTrackingIds.length) {
      identifiers.append(createMyOrderReference("Tracking ID", "Not assigned"));
    }

    const items = document.createElement("ul");
    items.className = "my-order-items";
    order.items.forEach((item) => {
      const line = document.createElement("li");
      const product = productBySku.get(item.sku);
      const name = document.createElement("span");
      name.textContent = item.name || product?.name || item.sku;
      const quantity = document.createElement("small");
      quantity.textContent = `× ${item.quantity}`;
      line.append(name, quantity);
      items.append(line);
    });

    const delivery = document.createElement("div");
    delivery.className = "my-order-delivery";
    const estimate = document.createElement("div");
    estimate.className = "my-order-delivery-detail";
    const estimateLabel = document.createElement("span");
    estimateLabel.textContent = "Delivery estimate";
    const estimateValue = document.createElement("strong");
    estimateValue.textContent = `${order.delivery_min_days}–${order.delivery_max_days} working days`;
    estimate.append(estimateLabel, estimateValue);
    const facility = document.createElement("div");
    facility.className = "my-order-delivery-detail";
    const facilityLabel = document.createElement("span");
    facilityLabel.textContent = "Delivery facility";
    const facilityValue = document.createElement("strong");
    facilityValue.textContent = order.delivery_facility || "Not assigned";
    facility.append(facilityLabel, facilityValue);
    delivery.append(estimate, facility);

    const details = document.createElement("div");
    details.className = "my-order-details";
    details.append(identifiers, items, delivery);
    const tracker = createDeliveryTracker(order.status, order.delivery_facility, order.live_location);
    tracker.dataset.correlationId = order.correlation_id;
    card.append(header, tracker, details);

    const actions = document.createElement("div");
    actions.className = "my-order-actions";
    const complaintButton = document.createElement("button");
    complaintButton.className = "button button-outline my-order-support";
    complaintButton.type = "button";
    complaintButton.textContent = "Report a problem";
    complaintButton.addEventListener("click", () => openComplaint(order));
    actions.append(complaintButton);

    if (order.status === "CANCELLED") {
      const cancelled = document.createElement("p");
      cancelled.className = "my-order-window";
      cancelled.textContent = "This order has been cancelled.";
      actions.append(cancelled);
    } else if (order.can_cancel) {
      const deadline = document.createElement("p");
      deadline.className = "my-order-window";
      deadline.textContent = `You can cancel before ${formatOrderDate(order.cancellation_deadline)}.`;
      const cancelButton = document.createElement("button");
      cancelButton.className = "button button-outline my-order-cancel";
      cancelButton.type = "button";
      cancelButton.textContent = "Cancel order";
      cancelButton.addEventListener("click", () => openCancelOrder(order));
      actions.append(deadline, cancelButton);
    } else if (order.status === "PENDING") {
      const closed = document.createElement("p");
      closed.className = "my-order-window";
      closed.textContent = "The 12-hour cancellation window has closed.";
      actions.append(closed);
    }

    card.append(actions);
    list.append(card);
  });
  list.hidden = false;
}

function createDeliveryTracker(status, facility, liveLocation) {
  const tracker = document.createElement("section");
  tracker.className = `delivery-tracker${status === "CANCELLED" ? " is-cancelled" : ""}`;
  tracker.setAttribute("aria-label", "Delivery progress");
  tracker.dataset.status = status;
  tracker.dataset.facility = facility || "";

  const heading = document.createElement("div");
  heading.className = "delivery-tracker-heading";
  const title = document.createElement("h4");
  title.textContent = status === "CANCELLED" ? "Delivery stopped" : "Delivery journey";
  const gps = document.createElement("span");
  gps.className = "delivery-gps-status";
  if (liveLocation?.status === "live" && status === "DISPATCHED") {
    gps.classList.add("is-live");
  }
  gps.textContent = status === "CANCELLED"
    ? "Cancelled"
    : status === "DELIVERED"
      ? "Delivered"
      : status !== "DISPATCHED"
        ? "GPS after dispatch"
        : liveLocation?.status === "live"
          ? "Live GPS"
          : liveLocation?.status === "stale"
            ? "GPS signal stale"
            : liveLocation?.status === "unavailable"
              ? "GPS refresh failed"
              : "Waiting for GPS";
  heading.append(title, gps);
  tracker.append(heading);

  if (status === "CANCELLED") {
    const message = document.createElement("p");
    message.className = "delivery-location-note";
    message.textContent = "This order was cancelled, so there is no active delivery location.";
    tracker.append(message);
    return tracker;
  }

  const stages = [
    { status: "PENDING", label: "Order received" },
    { status: "RECEIVED", label: "Preparing" },
    { status: "DISPATCHED", label: "Sent to facility" },
    { status: "DELIVERED", label: "Delivered" }
  ];
  const currentStage = Math.max(0, stages.findIndex((stage) => stage.status === status));
  const progress = document.createElement("ol");
  progress.className = "delivery-progress";
  progress.style.setProperty("--delivery-progress", `${(currentStage / (stages.length - 1)) * 100}%`);
  stages.forEach((stage, index) => {
    const step = document.createElement("li");
    if (index < currentStage) step.classList.add("is-complete");
    if (index === currentStage) {
      step.classList.add("is-current");
      step.setAttribute("aria-current", "step");
    }
    const marker = document.createElement("span");
    marker.className = "delivery-progress-marker";
    marker.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "delivery-progress-label";
    label.textContent = stage.label;
    step.append(marker, label);
    progress.append(step);
  });
  tracker.append(progress);

  const currentLocation = document.createElement("p");
  currentLocation.className = "delivery-location-note";
  if (status === "DELIVERED") {
    currentLocation.textContent = "Delivery completed at your address.";
  } else if (status === "DISPATCHED") {
    if (liveLocation?.status === "live") {
      currentLocation.textContent = `Live device position · updated ${formatOrderDate(liveLocation.updated_at)} · accuracy ±${Math.round(liveLocation.accuracy)} m.`;
      const livePosition = document.createElement("div");
      livePosition.className = "delivery-live-position";
      const coordinates = document.createElement("strong");
      coordinates.textContent = `${Number(liveLocation.latitude).toFixed(5)}, ${Number(liveLocation.longitude).toFixed(5)}`;
      const mapLink = document.createElement("a");
      mapLink.href = `https://www.openstreetmap.org/?mlat=${encodeURIComponent(liveLocation.latitude)}&mlon=${encodeURIComponent(liveLocation.longitude)}#map=16/${encodeURIComponent(liveLocation.latitude)}/${encodeURIComponent(liveLocation.longitude)}`;
      mapLink.target = "_blank";
      mapLink.rel = "noopener noreferrer";
      mapLink.textContent = "Open location in map";
      livePosition.append(coordinates, mapLink);
      tracker.append(livePosition);
    } else if (liveLocation?.status === "stale") {
      currentLocation.textContent = `GPS signal expired. Last update: ${formatOrderDate(liveLocation.updated_at)}. Old coordinates are hidden until sharing resumes.`;
    } else if (liveLocation?.status === "unavailable") {
      currentLocation.textContent = "Could not refresh GPS just now. The last location is not being presented as live; check your connection and refresh.";
    } else {
      currentLocation.textContent = facility
        ? `Delivery facility: ${facility}. Waiting for the courier to start GPS sharing from their device.`
        : "Sent to the delivery facility. Waiting for the courier to start GPS sharing from their device.";
    }
  } else if (status === "RECEIVED") {
    currentLocation.textContent = "Your order is being prepared. GPS sharing becomes available after dispatch.";
  } else {
    currentLocation.textContent = "Your order has been received. GPS sharing becomes available after dispatch.";
  }
  tracker.append(currentLocation);
  return tracker;
}

async function refreshTrackedOrderLocation() {
  if (!trackedOrderId || !document.querySelector("#trackDialog").open) return;
  try {
    const response = await fetch(`/orders/${encodeURIComponent(trackedOrderId)}`);
    const order = await response.json();
    if (!response.ok) throw new Error(order.detail || "Could not refresh delivery GPS.");
    const heading = document.querySelector("#trackResult h3");
    if (heading) heading.textContent = `Order status: ${statusLabel(order.status)}`;
    const tracker = document.querySelector("#trackResult .delivery-tracker");
    if (!tracker) return;
    tracker.replaceWith(createDeliveryTracker(order.status, order.delivery_facility, order.live_location));
  } catch (error) {
    console.error("Could not refresh tracked order GPS:", error);
    const tracker = document.querySelector("#trackResult .delivery-tracker");
    if (tracker) {
      tracker.replaceWith(createDeliveryTracker(
        tracker.dataset.status,
        tracker.dataset.facility,
        { status: "unavailable" }
      ));
    }
  }
}

async function refreshMyOrderLocations() {
  if (!document.querySelector("#myOrdersDialog").open || !authenticatedUser) return;
  try {
    const response = await fetch("/orders/my", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not refresh delivery GPS.");
    for (const order of result.orders) {
      const card = [...document.querySelectorAll(".my-order-card")]
        .find((item) => item.dataset.correlationId === order.correlation_id);
      const tracker = card?.querySelector(".delivery-tracker");
      if (tracker) {
        tracker.replaceWith(createDeliveryTracker(
          order.status,
          order.delivery_facility,
          order.live_location
        ));
      }
    }
  } catch (error) {
    console.error("Could not refresh My Orders GPS:", error);
    document.querySelectorAll(".my-order-card .delivery-tracker").forEach((tracker) => {
      tracker.replaceWith(createDeliveryTracker(
        tracker.dataset.status,
        tracker.dataset.facility,
        { status: "unavailable" }
      ));
    });
  }
}

function createMyOrderStat(label, value) {
  const stat = document.createElement("div");
  stat.className = "my-orders-stat";
  const count = document.createElement("strong");
  count.textContent = value;
  const caption = document.createElement("span");
  caption.textContent = label;
  stat.append(count, caption);
  return stat;
}

function createMyOrderReference(label, value) {
  const reference = document.createElement("div");
  reference.className = "my-order-reference";
  const caption = document.createElement("span");
  caption.textContent = label;
  const code = document.createElement("code");
  code.textContent = value;
  reference.append(caption, code);
  return reference;
}

function openComplaint(order) {
  if (!authenticatedUser) {
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
  if (!authenticatedUser) {
    openAccountDialog();
    return;
  }
  const dialog = document.querySelector("#myOrdersDialog");
  document.querySelector("#myOrdersError").hidden = true;
  document.querySelector("#myOrdersList").hidden = true;
  document.querySelector("#myOrdersSummary").hidden = true;
  if (!dialog.open) dialog.showModal();
  clearInterval(myOrdersLocationPollTimer);
  myOrdersLocationPollTimer = setInterval(refreshMyOrderLocations, 15000);
  loadMyOrders(authenticatedUser.email, "");
}

async function loadMyOrders(email, phone) {
  const errorBox = document.querySelector("#myOrdersError");
  const button = document.querySelector("#findMyOrders");
  errorBox.hidden = true;
  document.querySelector("#myOrdersList").hidden = true;
  document.querySelector("#myOrdersSummary").hidden = true;
  button.disabled = true;
  button.classList.add("is-busy");
  button.innerHTML = '<span aria-hidden="true">↻</span> Updating your orders…';
  activeMyOrdersCredentials = { email, phone };
  for (const [correlationId, watch] of deliveryLocationWatches) {
    navigator.geolocation.clearWatch(watch.watchId);
    try {
      await sendJson(locationShareUrl(correlationId), undefined, "DELETE");
    } catch (error) {
      console.error("Could not clear GPS sharing during logout:", error);
      showToast("This device stopped GPS, but the last location may remain visible for up to 2 minutes.");
    }
  }
  deliveryLocationWatches.clear();
  try {
    const response = await fetch("/orders/my", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
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
    button.innerHTML = '<span aria-hidden="true">↻</span> Refresh orders';
  }
}

function openCancelOrder(order) {
  pendingCancellation = order;
  document.querySelector("#cancelOrderError").hidden = true;
  const names = order.items.map((item) => {
    const product = productBySku.get(item.sku);
    return `${item.name || product?.name || item.sku} × ${item.quantity}`;
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
    await loadMyOrders(authenticatedUser.email, "");
  } catch (error) {
    errorBox.textContent = error.message || "We couldn’t reach the order service. Please try again.";
    errorBox.hidden = false;
    if (error.status === 409) {
      await loadMyOrders(authenticatedUser.email, "");
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
    if (line) {
      const product = productBySku.get(line.sku);
      const next = line.quantity + Number(quantityButton.dataset.quantity);
      if (next > 0 && next > Math.min(100, product?.stock ?? 0)) {
        showToast("There is not enough stock for that quantity.");
        return;
      }
      line.quantity = next;
    }
    cart = cart.filter((item) => item.quantity > 0);
  } else {
    return;
  }
  saveCart();
  renderCart();
});

document.querySelector("#startCheckout").addEventListener("click", () => {
  if (!cart.length) return;
  if (!authenticatedUser) {
    setDrawerOpen(false);
    openAccountDialog({ afterLogin: true });
    return;
  }
  document.querySelector("#customerEmail").value = authenticatedUser.email;
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
    loadStorefrontProducts().catch((error) => {
      console.error("Could not refresh inventory after checkout:", error);
      showToast("Order placed. Inventory refresh failed; reload the page to see current stock.");
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
document.querySelector("#trackDialog").addEventListener("close", () => {
  clearInterval(trackLocationPollTimer);
  trackLocationPollTimer = null;
  trackedOrderId = null;
});
document.querySelector("#myOrdersDialog").addEventListener("close", () => {
  clearInterval(myOrdersLocationPollTimer);
  myOrdersLocationPollTimer = null;
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
  if (authenticatedUser) loadMyOrders(authenticatedUser.email, "");
});
document.querySelector("#complaintForm").addEventListener("submit", submitComplaint);
document.querySelector("#productReviewForm").addEventListener("submit", submitProductReview);
document.querySelector("#reviewSignIn").addEventListener("click", () => {
  reviewAfterLoginSku = activeProductSku;
  document.querySelector("#productDialog").close();
  openAccountDialog();
});
document.querySelector("#complaintType").addEventListener("change", syncComplaintType);
document.querySelector("#accountButton").addEventListener("click", () => openAccountDialog());
document.querySelector("#openAccountFooter").addEventListener("click", () => openAccountDialog());
document.querySelector("#accountMode").addEventListener("change", syncAccountMode);
document.querySelectorAll(".password-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordTarget);
    setPasswordVisibility(button, input.type === "password");
  });
});
document.querySelector("#forgotPasswordLink").addEventListener("click", showForgotPassword);
document.querySelector("#backToLogin").addEventListener("click", () => {
  accountFlow = "account";
  syncAccountMode();
  document.querySelector("#accountEmail").focus();
});
document.querySelector("#accountForm").addEventListener("submit", submitAccount);
document.querySelector("#forgotPasswordForm").addEventListener("submit", submitPasswordResetRequest);
document.querySelector("#resetPasswordForm").addEventListener("submit", submitPasswordReset);
document.querySelector("#logoutButton").addEventListener("click", logout);
document.querySelector("#myOrdersButton").addEventListener("click", () => openMyOrders());
document.querySelector("#openMyOrdersFooter").addEventListener("click", () => openMyOrders());
document.querySelector("#openComplaints").addEventListener("click", () => openMyOrders());
document.querySelector("#managementButton").addEventListener("click", openManagement);
document.querySelector("#managementProductSelect").addEventListener("change", (event) => {
  populateManagedProduct(inventory.find((product) => product.sku === event.target.value));
});
document.querySelector("#productUpdateForm").addEventListener("submit", updateManagedProduct);
document.querySelector("#productCreateForm").addEventListener("submit", createManagedProduct);
document.querySelector("#managedUserForm").addEventListener("submit", createManagedUser);
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
syncAccountMode();
(async () => {
  try {
    const previousCart = cart;
    await loadAuthenticatedUser();
    await loadStorefrontProducts();
    if (authenticatedUser) switchCartToAuthenticatedUser(previousCart);
  } catch (error) {
    console.error("Could not initialize the storefront:", error);
    showToast(error.message || "Could not load the shop. Please reload.");
  }
})();
try {
  if (pendingResetToken) {
    accountFlow = "reset";
    syncAccountMode();
    document.querySelector("#accountDialog").showModal();
    document.querySelector("#newPassword").focus();
  } else if (localStorage.getItem("maltashop-welcome-dismissed") !== "true") {
    welcomeDialog.showModal();
  }
} catch (error) {
  console.error("Could not read the welcome preference:", error);
  welcomeDialog.showModal();
}

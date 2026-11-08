const additionalProductCatalog = {
  Home: [
    "Ceramic incense holder", "Linen table runner", "Woven storage basket", "Stoneware breakfast bowl",
    "Cotton cushion cover", "Oak picture frame", "Ribbed glass carafe", "Hand-thrown coffee mug",
    "Soft cotton throw", "Marble trinket tray", "Reed diffuser set", "Sculpted candle holder",
    "Striped tea towel set", "Jute plant basket", "Linen napkin set", "Speckled serving platter",
    "Timber bedside tray", "Textured door mat", "Ceramic soap dispenser", "Woven laundry hamper",
    "Amber glass candle", "Small wall mirror", "Cotton bath towel", "Fluted water glass set",
    "Decorative bookends", "Round placemat set", "Minimal wall clock", "Soft knit cushion",
    "Wooden salad servers", "Lidded pantry jar", "Handwoven table mat", "Ceramic bud vase",
    "Natural fiber rug", "Cotton duvet cover", "Scented wax melts", "Acacia chopping board",
    "Linen apron", "Glass bud vase set", "Woven bread basket", "Stoneware side plate",
    "Wooden jewelry stand", "Cotton cushion insert", "Decorative taper candles", "Small ceramic planter",
    "Brass photo frame", "Textured bath mat", "Reusable kitchen cloths", "Rattan wall shelf",
    "Porcelain tea cup", "Linen storage pouch", "Wooden serving bowl", "Soft eye pillow",
    "Ceramic oil bottle", "Woven coaster set", "Glass candle lantern", "Cotton tablecloth",
    "Sculptural bookend", "Bamboo cutlery tray", "Stoneware pasta bowl", "Cotton hand towels",
    "Decorative wall hook", "Hand-painted mug", "Small woven wall basket", "Wooden candle snuffer",
    "Linen bedside organizer", "Ceramic fruit bowl", "Foldable fabric storage box", "Wooden recipe stand"
  ],
  Tech: [
    "Wireless charging pad", "Compact Bluetooth speaker", "USB-C travel hub", "Noise-isolating earbuds",
    "Portable power bank", "Foldable phone stand", "Smart LED light strip", "Bluetooth keyboard",
    "Wireless computer mouse", "Fast-charge wall adapter", "Braided USB-C cable", "Laptop privacy screen",
    "Adjustable laptop stand", "Compact travel adapter", "Clip-on reading light", "Water-resistant speaker",
    "Over-ear studio headphones", "Magnetic phone mount", "Dual-port car charger", "Digital alarm clock",
    "Rechargeable desk lamp", "Webcam privacy cover", "Bluetooth tracker tag", "USB desk fan",
    "Wireless number pad", "Tablet protective sleeve", "Touchscreen stylus pen", "Multi-device charging dock",
    "Portable SSD case", "Foldable headphone stand", "Smart plug socket", "USB-C card reader",
    "Pocket-size tripod", "Camera cleaning kit", "LED selfie light", "Wireless presentation clicker",
    "Ergonomic mouse pad", "Cable organizer clips", "Laptop cooling stand", "Bluetooth shower speaker",
    "Rechargeable hand warmer", "Compact digital timer", "Screen-cleaning set", "USB microphone",
    "Portable photo printer", "Wireless charging stand", "Universal tablet holder", "Mini projector stand",
    "Smart motion sensor", "Noise-reducing earplugs", "Travel cable pouch", "USB-C ethernet adapter",
    "Rechargeable book light", "Bluetooth key finder", "Desk headphone hooks", "Portable battery lantern",
    "Digital kitchen scale", "Compact label maker", "Camera wrist strap", "USB-C to HDMI adapter",
    "Wireless doorbell chime", "Smart temperature sensor", "Travel power strip", "Mini Bluetooth receiver",
    "Wireless conference speakerphone", "Rechargeable camera flash", "Compact document scanner", "Bluetooth audio transmitter"
  ],
  Wear: [
    "Everyday leather cardholder", "Canvas weekend tote", "Classic cotton cap", "Lightweight linen scarf",
    "Stainless steel hoop earrings", "Braided leather bracelet", "Minimal pendant necklace", "Soft-knit beanie",
    "Everyday ankle socks", "Cotton bucket hat", "Slim leather belt", "Round-frame sunglasses",
    "Canvas crossbody bag", "Cotton crew-neck tee", "Lightweight overshirt", "Woven leather keyring",
    "Delicate chain bracelet", "Small travel jewelry case", "Ribbed cotton tank", "Relaxed linen shirt",
    "Everyday running cap", "Compact zip wallet", "Textured hoop earrings", "Cotton bandana",
    "Soft jersey lounge set", "Classic canvas belt", "Minimal signet ring", "Foldable shopping tote",
    "Striped cotton scarf", "Leather passport cover", "Everyday hair claw set", "Pearl drop earrings",
    "Lightweight gym towel", "Cotton baseball cap", "Woven beach bag", "Simple gold-tone studs",
    "Soft cotton sleep mask", "Unisex canvas pouch", "Layered pendant necklace", "Ribbed beanie hat",
    "Slim travel wallet", "Adjustable woven bracelet", "Everyday leather pouch", "Cotton band collar shirt",
    "Lightweight rain cap", "Classic aviator sunglasses", "Canvas laptop tote", "Textured silver ring",
    "Soft jersey shorts", "Linen blend scrunchie set", "Leather luggage tag", "Minimal cuff bracelet",
    "Relaxed cotton sweatshirt", "Small hoop earring set", "Cotton drawstring bag", "Everyday woven belt",
    "Compact makeup pouch", "Two-tone canvas tote", "Simple pendant earrings", "Lightweight neck wrap",
    "Classic cotton socks set", "Foldable travel hat", "Leather cord necklace", "Everyday zip card case",
    "Canvas market backpack", "Lightweight cotton cardigan", "Woven leather bracelet set", "Compact sunglasses case"
  ]
};

const productStyles = {
  Home: { hue: 24, basePrice: 14, priceStep: 17, priceRange: 112 },
  Tech: { hue: 190, basePrice: 16, priceStep: 23, priceRange: 132 },
  Wear: { hue: 315, basePrice: 12, priceStep: 19, priceRange: 126 }
};

const productTags = ["NEW ARRIVAL", "ISLAND FAVOURITE", "MADE TO KEEP", "GOOD ON THE GO"];
const additionalProducts = Object.entries(additionalProductCatalog).flatMap(([category, names]) => {
  const style = productStyles[category];
  return names.map((name, index) => ({
    sku: `${category.toUpperCase()}-${String(index + 1).padStart(3, "0")}`,
    name,
    category,
    price: style.basePrice + ((index * style.priceStep) % style.priceRange),
    tag: productTags[index % productTags.length],
    bg: `hsl(${(style.hue + index * 137.508) % 360} 35% 82%)`,
    image: additionalProductImages[`${category.toUpperCase()}-${String(index + 1).padStart(3, "0")}`],
    description: `${name} is a thoughtful ${category.toLocaleLowerCase()} find, selected for everyday use and easy island living.`
  }));
});

/* ===== MR Biker — Bolt-style Motorcycle Parcel Delivery (Harare) =====
   Dark UI with CartoDB dark tiles, Nominatim geocoding, OSRM routing */

/* ---------- DOM ---------- */
const mapStatus        = document.getElementById("mapStatus");
const pickupInput      = document.getElementById("pickupInput");
const dropoffInput     = document.getElementById("dropoffInput");
const pickupSuggestions  = document.getElementById("pickupSuggestions");
const dropoffSuggestions = document.getElementById("dropoffSuggestions");
const parcelDesc       = document.getElementById("parcelDesc");
const gpsBtn           = document.getElementById("gpsBtn");
const useMyLocBtn      = document.getElementById("useMyLocationBtn");
const fareMinus        = document.getElementById("fareMinus");
const farePlus         = document.getElementById("farePlus");
const fareValue        = document.getElementById("fareValue");
const fareOriginal     = document.getElementById("fareOriginal");
const fareRecommended  = document.getElementById("fareRecommended");
const sendBtn          = document.getElementById("sendParcelBtn");
const ctaText          = document.getElementById("ctaText");
const routeCard        = document.getElementById("routeCard");
const rcDist           = document.getElementById("rcDist");
const rcEta            = document.getElementById("rcEta");
const addrEta          = document.getElementById("addrEta");
const pickupError      = document.getElementById("pickupError");
const dropoffError     = document.getElementById("dropoffError");
const negotiationCard  = document.getElementById("negotiationCard");
const negotiationFare  = document.getElementById("negotiationFare");

/* ---------- State ---------- */
let map;
let pickupCoords       = null;
let dropoffCoords      = null;
let pickupMarker       = null;
let dropoffMarker      = null;
let routeLine          = null;
let lastRoute          = null;
let reverseLookupTimer = null;
let pickupTypingTimer  = null;
let dropoffTypingTimer = null;
let pickupSuggestionItems  = [];
let dropoffSuggestionItems = [];
let lastPickupAddress  = "";
let lastReverseCenter  = null;
let isEditingPickup    = false;
let currentFare        = 3.00;
let recommendedFare    = 3.00;
let searchingInProgress = false;
let searchStatusTimer = null;
let radarPulseTimer = null;
let foundRiderTimer = null;
let radarCircles = [];
let riderMarker = null;
const HARARE           = [-17.8252, 31.0335];
const BASE_RATE        = 0.80;
const MIN_FARE         = 1.00;
const FARE_STEP        = 0.50;
const AUTO_LOCATION_ZOOM = 17;

/* ---------- Init map ---------- */
function initMap() {
  map = L.map("rideMap", {
    zoomControl: false,
    attributionControl: true,
  }).setView(HARARE, 14);

  L.control.zoom({ position: "topright" }).addTo(map);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '\u00a9 <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  map.on("move", () => {
    clearTimeout(reverseLookupTimer);
  });

  map.on("moveend", () => {
    clearTimeout(reverseLookupTimer);
    reverseLookupTimer = setTimeout(() => {
      updatePickupFromCenter();
    }, 280);
  });

  attachEvents();
  tryGeolocate(true);
}

/* ---------- Reverse-geocode center -> pickup ---------- */
async function updatePickupFromCenter() {
  if (isEditingPickup) return;

  var center = map.getCenter();
  var nextCoords = [center.lat, center.lng];

  if (lastReverseCenter) {
    var movedLat = Math.abs(nextCoords[0] - lastReverseCenter[0]);
    var movedLng = Math.abs(nextCoords[1] - lastReverseCenter[1]);
    if (movedLat < 0.00008 && movedLng < 0.00008) return;
  }

  pickupCoords = nextCoords;
  lastReverseCenter = nextCoords;
  placePickupMarker();
  updateSendState();

  try {
    var address = await reverseGeocode(pickupCoords[0], pickupCoords[1]);
    if (address) {
      lastPickupAddress = address;
      pickupInput.value = shortAddr(address);
      mapStatus.textContent = "Pickup set";
      maybeRoute();
      return;
    }
    throw new Error("empty");
  } catch (e) {
    if (lastPickupAddress) {
      pickupInput.value = shortAddr(lastPickupAddress);
    }
  }
}

function shortAddr(full) {
  return full.split(",").slice(0, 2).join(",").trim();
}

function setInputError(type, message) {
  if (type === "pickup") {
    pickupError.textContent = message || "";
    pickupInput.classList.toggle("input-error", Boolean(message));
    return;
  }
  dropoffError.textContent = message || "";
  dropoffInput.classList.toggle("input-error", Boolean(message));
}

function clearInputErrors() {
  setInputError("pickup", "");
  setInputError("dropoff", "");
}

function setButtonIdle() {
  sendBtn.classList.remove("is-searching");
  sendBtn.disabled = !(pickupCoords && dropoffCoords);
  ctaText.textContent = "Find a Rider";
}

function cancelSearchFlow(reasonText) {
  if (!searchingInProgress) return;
  clearSearchVisuals();
  searchingInProgress = false;
  setButtonIdle();
  if (reasonText) {
    mapStatus.textContent = reasonText;
  }
}

function clearSearchVisuals() {
  if (searchStatusTimer) {
    clearInterval(searchStatusTimer);
    searchStatusTimer = null;
  }
  if (radarPulseTimer) {
    clearInterval(radarPulseTimer);
    radarPulseTimer = null;
  }
  if (foundRiderTimer) {
    clearTimeout(foundRiderTimer);
    foundRiderTimer = null;
  }
  radarCircles.forEach(function(circle) {
    if (map && map.hasLayer(circle)) {
      map.removeLayer(circle);
    }
  });
  radarCircles = [];
}

function startStatusEllipsis(baseText) {
  var dots = 0;
  mapStatus.textContent = baseText;
  searchStatusTimer = setInterval(function() {
    dots = (dots + 1) % 4;
    mapStatus.textContent = baseText + ".".repeat(dots);
  }, 420);
}

function spawnRadarCircle() {
  if (!pickupCoords) return;
  var circle = L.circle(pickupCoords, {
    radius: 35,
    color: "#5bbfff",
    weight: 2,
    fillColor: "#5bbfff",
    fillOpacity: 0.2,
    className: "radar-circle",
  }).addTo(map);

  radarCircles.push(circle);

  var started = Date.now();
  var lifeMs = 1800;
  var startRadius = 35;
  var endRadius = 220;

  var anim = setInterval(function() {
    var elapsed = Date.now() - started;
    var progress = Math.min(1, elapsed / lifeMs);
    var radius = startRadius + (endRadius - startRadius) * progress;
    circle.setRadius(radius);
    circle.setStyle({
      opacity: 0.7 * (1 - progress),
      fillOpacity: 0.22 * (1 - progress),
    });
    if (progress >= 1) {
      clearInterval(anim);
      if (map.hasLayer(circle)) {
        map.removeLayer(circle);
      }
      radarCircles = radarCircles.filter(function(item) { return item !== circle; });
    }
  }, 40);
}

function startRadarPulseLoop() {
  spawnRadarCircle();
  setTimeout(spawnRadarCircle, 400);
  setTimeout(spawnRadarCircle, 800);
  radarPulseTimer = setInterval(spawnRadarCircle, 1200);
}

function showRiderFound() {
  clearSearchVisuals();
  searchingInProgress = false;

  if (riderMarker && map.hasLayer(riderMarker)) {
    map.removeLayer(riderMarker);
  }

  var riderIcon = L.divIcon({
    className: "rider-drop-wrap",
    html: '<div class="rider-drop-icon" aria-hidden="true">R</div>',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });

  riderMarker = L.marker(pickupCoords, { icon: riderIcon, zIndexOffset: 900 }).addTo(map);

  negotiationFare.textContent = "$" + currentFare.toFixed(2);
  negotiationCard.classList.remove("hidden");
  mapStatus.textContent = "Rider found nearby. Open to negotiate.";
  ctaText.textContent = "Rider Found";
  sendBtn.classList.remove("is-searching");
  sendBtn.disabled = false;
}

function startRiderSearchFlow() {
  if (searchingInProgress || !pickupCoords || !dropoffCoords) return;

  searchingInProgress = true;
  negotiationCard.classList.add("hidden");
  sendBtn.classList.add("is-searching");
  sendBtn.disabled = true;
  ctaText.textContent = "Looking for riders nearby";

  map.flyTo(pickupCoords, 16, { duration: 0.8 });

  clearSearchVisuals();
  startStatusEllipsis("Looking for riders nearby");
  startRadarPulseLoop();

  foundRiderTimer = setTimeout(function() {
    showRiderFound();
  }, 4600);
}

/* ---------- UI Events ---------- */
function attachEvents() {
  pickupInput.addEventListener("focus", function() { isEditingPickup = true; });
  pickupInput.addEventListener("blur", function() {
    setTimeout(function() { isEditingPickup = false; }, 200);
    setTimeout(function() {
      var query = pickupInput.value.trim();
      if (query.length < 3) return;
      geocodeAddress(query, function(coords, resolved) {
        pickupCoords = coords;
        lastPickupAddress = resolved || query;
        pickupInput.value = shortAddr(lastPickupAddress);
        setInputError("pickup", "");
        placePickupMarker();
        fitMarkers();
        updateSendState();
        maybeRoute();
      }, "pickup");
    }, 210);
  });

  pickupInput.addEventListener("input", function() {
    cancelSearchFlow("Search canceled. Update locations and try again.");
    isEditingPickup = true;
    setInputError("pickup", "");
    clearTimeout(pickupTypingTimer);
    var query = pickupInput.value.trim();
    if (query.length < 3) {
      pickupSuggestionItems = [];
      hideSuggestions(pickupSuggestions);
      return;
    }
    pickupTypingTimer = setTimeout(function() {
      fetchPlaceSuggestions(query).then(function(items) {
        pickupSuggestionItems = items;
        renderSuggestions(pickupSuggestions, items, "pickup");
      });
    }, 450);
  });

  dropoffInput.addEventListener("input", function() {
    cancelSearchFlow("Search canceled. Update locations and try again.");
    setInputError("dropoff", "");
    clearTimeout(dropoffTypingTimer);
    var query = dropoffInput.value.trim();
    if (query.length < 3) {
      dropoffSuggestionItems = [];
      hideSuggestions(dropoffSuggestions);
      return;
    }
    dropoffTypingTimer = setTimeout(function() {
      fetchPlaceSuggestions(query).then(function(items) {
        dropoffSuggestionItems = items;
        renderSuggestions(dropoffSuggestions, items, "dropoff");
      });
    }, 450);
  });

  dropoffInput.addEventListener("blur", function() {
    setTimeout(function() {
      var query = dropoffInput.value.trim();
      if (query.length < 3) return;
      geocodeAddress(query, function(coords, resolved) {
        dropoffCoords = coords;
        dropoffInput.value = shortAddr(resolved || query);
        setInputError("dropoff", "");
        placeDropoffMarker();
        fitMarkers();
        updateSendState();
        maybeRoute();
      }, "dropoff");
    }, 120);
  });

  fareMinus.addEventListener("click", function() {
    cancelSearchFlow("Search canceled. Offer updated.");
    currentFare = Math.max(MIN_FARE, currentFare - FARE_STEP);
    updateFareDisplay();
  });

  farePlus.addEventListener("click", function() {
    cancelSearchFlow("Search canceled. Offer updated.");
    currentFare = Math.min(50, currentFare + FARE_STEP);
    updateFareDisplay();
  });

  useMyLocBtn.addEventListener("click", function() { tryGeolocate(true); });
  gpsBtn.addEventListener("click", function() { tryGeolocate(true); });

  pickupInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (pickupSuggestionItems.length > 0) {
        applySuggestion("pickup", pickupSuggestionItems[0]);
        return;
      }
      geocodeAddress(pickupInput.value.trim(), function(coords, resolved) {
        pickupCoords = coords;
        lastPickupAddress = resolved || pickupInput.value.trim();
        pickupInput.value = shortAddr(lastPickupAddress);
        setInputError("pickup", "");
        placePickupMarker();
        fitMarkers();
        updateSendState();
        maybeRoute();
      }, "pickup");
    }
  });

  dropoffInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (dropoffSuggestionItems.length > 0) {
        applySuggestion("dropoff", dropoffSuggestionItems[0]);
        return;
      }
      geocodeAddress(dropoffInput.value.trim(), function(coords, resolved) {
        dropoffCoords = coords;
        dropoffInput.value = shortAddr(resolved || dropoffInput.value.trim());
        setInputError("dropoff", "");
        placeDropoffMarker();
        fitMarkers();
        updateSendState();
        maybeRoute();
      }, "dropoff");
    }
  });

  sendBtn.addEventListener("click", function() {
    if (!pickupCoords || !dropoffCoords) return;
    startRiderSearchFlow();
  });

  document.addEventListener("click", function(event) {
    if (!pickupInput.contains(event.target) && !pickupSuggestions.contains(event.target)) {
      hideSuggestions(pickupSuggestions);
    }
    if (!dropoffInput.contains(event.target) && !dropoffSuggestions.contains(event.target)) {
      hideSuggestions(dropoffSuggestions);
    }
  });
}

/* ---------- Fare display ---------- */
function updateFareDisplay() {
  fareValue.textContent = "$" + currentFare.toFixed(2);
  if (currentFare !== recommendedFare) {
    fareOriginal.textContent = "$" + recommendedFare.toFixed(2);
    fareOriginal.classList.remove("hidden");
  } else {
    fareOriginal.classList.add("hidden");
  }
  fareRecommended.textContent = "Recommended fare: $" + recommendedFare.toFixed(2);
}

/* ---------- Suggestions ---------- */
function applySuggestion(type, item) {
  var coords = [Number(item.lat), Number(item.lon)];
  var label = item.display_name || "";

  if (type === "pickup") {
    pickupCoords = coords;
    lastPickupAddress = label;
    pickupInput.value = shortAddr(label);
    isEditingPickup = false;
    setInputError("pickup", "");
    placePickupMarker();
    hideSuggestions(pickupSuggestions);
  } else {
    dropoffCoords = coords;
    dropoffInput.value = shortAddr(label);
    setInputError("dropoff", "");
    placeDropoffMarker();
    hideSuggestions(dropoffSuggestions);
  }

  fitMarkers();
  updateSendState();
  maybeRoute();
}

function renderSuggestions(listEl, items, type) {
  if (!items || items.length === 0) {
    hideSuggestions(listEl);
    return;
  }

  listEl.innerHTML = items
    .map(function(item, index) {
      var text = item.display_name || "Unknown place";
      var first = text.split(",")[0];
      return (
        '<li><button type="button" class="suggestion-btn" data-type="' +
        type + '" data-index="' + index +
        '"><strong>' + escapeHtml(first) +
        '</strong><br>' + escapeHtml(text) +
        '</button></li>'
      );
    })
    .join("");

  listEl.classList.add("show");

  listEl.querySelectorAll(".suggestion-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var idx = Number(btn.dataset.index);
      var bucket = btn.dataset.type === "pickup" ? pickupSuggestionItems : dropoffSuggestionItems;
      if (bucket[idx]) {
        applySuggestion(btn.dataset.type, bucket[idx]);
      }
    });
  });
}

function hideSuggestions(listEl) {
  listEl.classList.remove("show");
  listEl.innerHTML = "";
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function fetchPlaceSuggestions(query) {
  var cleanQuery = query.trim();
  if (cleanQuery.length < 2) return [];

  var firstPass = await runSuggestionLookup(cleanQuery, true);
  if (firstPass.length > 0) return firstPass;

  // Fallback 1: retry without hard country lock but bias results toward Zimbabwe.
  var secondPass = await runSuggestionLookup(cleanQuery, false);
  if (secondPass.length > 0) return secondPass;

  // Fallback 2: strip trailing token to survive common last-word typos.
  var shortened = shortenQuery(cleanQuery);
  if (shortened && shortened !== cleanQuery) {
    var thirdPass = await runSuggestionLookup(shortened, true);
    if (thirdPass.length > 0) return thirdPass;
    return runSuggestionLookup(shortened, false);
  }

  return [];
}

function shortenQuery(query) {
  var parts = query.split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return "";
  parts.pop();
  return parts.join(" ").trim();
}

async function runSuggestionLookup(query, lockToZimbabwe) {
  var endpoint =
    "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6" +
    (lockToZimbabwe ? "&countrycodes=zw" : "&viewbox=25.2,-22.4,33.1,-15.4&bounded=0") +
    "&addressdetails=1&q=" + encodeURIComponent(query);

  try {
    var response = await fetch(endpoint, { headers: { Accept: "application/json" } });
    if (!response.ok) return [];
    var data = await response.json();
    return Array.isArray(data) ? data : [];
  } catch (e) {
    return [];
  }
}

/* ---------- Geolocation ---------- */
function tryGeolocate(userTriggered) {
  if (!navigator.geolocation) {
    if (userTriggered) mapStatus.textContent = "Geolocation not supported.";
    return;
  }

  mapStatus.textContent = "Getting your location...";

  navigator.geolocation.getCurrentPosition(
    function(pos) {
      setInputError("pickup", "");
      pickupCoords = [pos.coords.latitude, pos.coords.longitude];
      map.flyTo(pickupCoords, AUTO_LOCATION_ZOOM, { duration: 0.8 });
      placePickupMarker();

      reverseGeocode(pickupCoords[0], pickupCoords[1])
        .then(function(address) {
          if (address) {
            lastPickupAddress = address;
            pickupInput.value = shortAddr(address);
          } else if (lastPickupAddress) {
            pickupInput.value = shortAddr(lastPickupAddress);
          }
          mapStatus.textContent = "Pickup set to your location";
          updateSendState();
          maybeRoute();
        })
        .catch(function() {
          mapStatus.textContent = "Pickup set to your location";
          updateSendState();
          maybeRoute();
        });
    },
    function() {
      if (userTriggered) {
        mapStatus.textContent = "Location denied. Type an address.";
        setInputError("pickup", "Location access denied. Enter pickup manually.");
      }
    },
    { enableHighAccuracy: true, timeout: 8000 }
  );
}

/* ---------- Geocode helper ---------- */
async function geocodeAddress(query, callback, fieldType) {
  if (!query) return;
  mapStatus.textContent = "Looking up address...";
  try {
    var data = await fetchGeocodeCandidates(query);
    if (!Array.isArray(data) || data.length === 0) throw new Error("empty");
    var first = data[0];
    callback([Number(first.lat), Number(first.lon)], first.display_name || query);
  } catch (e) {
    mapStatus.textContent = "Could not find that address.";
    if (fieldType === "pickup") {
      setInputError("pickup", "Pickup address not found. Try a clearer place name.");
    } else {
      setInputError("dropoff", "Drop-off address not found. Try a clearer place name.");
    }
  }
}

async function fetchGeocodeCandidates(query) {
  var cleanQuery = query.trim();
  if (!cleanQuery) return [];

  var firstPass = await runGeocodeLookup(cleanQuery, true);
  if (firstPass.length > 0) return firstPass;

  var secondPass = await runGeocodeLookup(cleanQuery, false);
  if (secondPass.length > 0) return secondPass;

  var shortened = shortenQuery(cleanQuery);
  if (shortened && shortened !== cleanQuery) {
    var thirdPass = await runGeocodeLookup(shortened, true);
    if (thirdPass.length > 0) return thirdPass;
    return runGeocodeLookup(shortened, false);
  }

  return [];
}

async function runGeocodeLookup(query, lockToZimbabwe) {
  var endpoint =
    "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=3" +
    (lockToZimbabwe ? "&countrycodes=zw" : "&viewbox=25.2,-22.4,33.1,-15.4&bounded=0") +
    "&q=" + encodeURIComponent(query);

  try {
    var response = await fetch(endpoint, { headers: { Accept: "application/json" } });
    if (!response.ok) return [];
    var data = await response.json();
    return Array.isArray(data) ? data : [];
  } catch (e) {
    return [];
  }
}

async function reverseGeocode(lat, lon) {
  var endpoint = "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon);
  var response = await fetch(endpoint, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("fail");
  var data = await response.json();
  if (!data || !data.display_name) return "";
  return data.display_name;
}

/* ---------- Markers ---------- */
function placePickupMarker() {
  if (pickupMarker) map.removeLayer(pickupMarker);
  if (!pickupCoords) return;

  pickupMarker = L.circleMarker(pickupCoords, {
    radius: 8,
    color: "#fff",
    weight: 2,
    fillColor: "#7ed957",
    fillOpacity: 0.95,
  }).addTo(map);
}

function placeDropoffMarker() {
  if (dropoffMarker) map.removeLayer(dropoffMarker);
  if (!dropoffCoords) return;

  dropoffMarker = L.circleMarker(dropoffCoords, {
    radius: 8,
    color: "#fff",
    weight: 2,
    fillColor: "#ff4d6a",
    fillOpacity: 0.95,
  }).addTo(map);
}

function fitMarkers() {
  if (pickupCoords && dropoffCoords) {
    var bounds = L.latLngBounds([pickupCoords, dropoffCoords]);
    map.fitBounds(bounds, { padding: [80, 80] });
  } else if (pickupCoords) {
    map.panTo(pickupCoords);
  } else if (dropoffCoords) {
    map.panTo(dropoffCoords);
  }
}

/* ---------- Routing ---------- */
async function maybeRoute() {
  if (!pickupCoords || !dropoffCoords) return;

  mapStatus.textContent = "Calculating route...";

  try {
    var endpoint =
      "https://router.project-osrm.org/route/v1/driving/" +
      pickupCoords[1] + "," + pickupCoords[0] + ";" +
      dropoffCoords[1] + "," + dropoffCoords[0] +
      "?overview=full&geometries=geojson";

    var response = await fetch(endpoint);
    if (!response.ok) throw new Error("fail");
    var data = await response.json();
    if (!data.routes || data.routes.length === 0) throw new Error("none");
    showRoute(data.routes[0]);
  } catch (e) {
    mapStatus.textContent = "Route calculation failed.";
    hideRouteCard();
  }
}

function showRoute(route) {
  if (routeLine) map.removeLayer(routeLine);

  var coords = route.geometry.coordinates.map(function(c) { return [c[1], c[0]]; });
  routeLine = L.polyline(coords, {
    color: "#5bbfff",
    weight: 5,
    opacity: 0.85,
  }).addTo(map);

  map.fitBounds(routeLine.getBounds(), { padding: [80, 80] });

  var distKm = route.distance / 1000;
  var durMin = Math.ceil(route.duration / 60);
  lastRoute = { distanceKm: distKm, durationMin: durMin };

  recommendedFare = Math.max(MIN_FARE, parseFloat((distKm * BASE_RATE).toFixed(2)));

  if (currentFare === 3.00 || currentFare < recommendedFare) {
    currentFare = recommendedFare;
  }
  updateFareDisplay();

  rcDist.textContent = distKm.toFixed(1) + " km";
  rcEta.textContent = "~" + durMin + " min";
  addrEta.textContent = "~" + durMin + " min.";
  routeCard.classList.remove("hidden");

  mapStatus.textContent = distKm.toFixed(1) + " km \u00b7 " + durMin + " min";
}

function hideRouteCard() {
  if (routeLine) {
    map.removeLayer(routeLine);
    routeLine = null;
  }
  routeCard.classList.add("hidden");
  addrEta.textContent = "";
  lastRoute = null;
  negotiationCard.classList.add("hidden");
}

/* ---------- Send button state ---------- */
function updateSendState() {
  if (searchingInProgress) return;
  sendBtn.disabled = !(pickupCoords && dropoffCoords);
}

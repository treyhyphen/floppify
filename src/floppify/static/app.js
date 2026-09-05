const $ = (id) => document.getElementById(id);
const state = { playing: false, shuffle: false, selectedDevice: "", connected: false };

function formatMs(ms = 0) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function toast(message, error = false) {
  const box = $("toast");
  box.textContent = message;
  box.className = error ? "show error" : "show";
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { box.className = ""; }, 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); }
    catch (_) { payload = text; }
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    if (typeof payload === "string") message = payload;
    else if (payload?.detail) message = payload.detail;
    throw new Error(message);
  }
  return payload;
}

function deviceBody(extra = {}) {
  return JSON.stringify({ device_id: state.selectedDevice || null, ...extra });
}

async function command(path, extra = {}) {
  try {
    await api(path, { method: "POST", body: deviceBody(extra) });
    await refreshStatus();
  } catch (error) { toast(error.message, true); }
}

function renderStatus(data) {
  state.connected = data.provider.connected;
  if (!state.selectedDevice && data.selected_device_id) state.selectedDevice = data.selected_device_id;
  $("connect").classList.toggle("hidden", data.provider.configured && data.provider.connected);
  $("connect").textContent = data.provider.configured ? "Connect Spotify" : "Setup Spotify";

  const disk = data.disk;
  const diskState = $("disk-state");
  diskState.classList.toggle("active", disk.inserted && !disk.error);
  diskState.classList.toggle("error", Boolean(disk.error));
  diskState.querySelector("span").textContent = disk.error
    ? disk.error
    : disk.inserted
      ? (disk.config?.name || `${disk.config?.type || "music"} loaded`)
      : "Waiting for disk";

  if (data.error) toast(data.error, true);
  const player = data.player;
  if (!player) {
    state.playing = false;
    $("play").textContent = "▶";
    return;
  }
  state.playing = player.is_playing;
  state.shuffle = player.shuffle;
  $("play").textContent = player.is_playing ? "Ⅱ" : "▶";
  $("shuffle").classList.toggle("selected", player.shuffle);
  $("track").textContent = player.track || "Nothing playing";
  $("artist").textContent = player.artists || "Spotify";
  $("album").textContent = player.album || "";
  $("art").src = player.artwork || "/static/floppy.svg";
  $("elapsed").textContent = formatMs(player.progress_ms);
  $("duration").textContent = formatMs(player.duration_ms);
  const percent = player.duration_ms ? (player.progress_ms / player.duration_ms) * 100 : 0;
  $("progress-fill").style.width = `${Math.min(100, percent)}%`;
  if (player.device?.volume_percent != null && document.activeElement !== $("volume")) {
    $("volume").value = player.device.volume_percent;
  }
}

async function refreshStatus() {
  try { renderStatus(await api("/api/status")); }
  catch (error) { toast(error.message, true); }
}

async function refreshDevices(showHint = false) {
  if (!state.connected) return;
  try {
    const { devices } = await api("/api/devices");
    const select = $("devices");
    const previous = state.selectedDevice;
    select.innerHTML = "";
    if (!devices.length) select.add(new Option("Open Spotify on a device", ""));
    devices.forEach((device) => {
      const source = device.source === "sonos" ? " • Sonos" : "";
      const active = device.is_active ? " • active" : "";
      select.add(new Option(`${device.name}${source}${active}`, device.id));
    });
    const preferred = previous
      || devices.find((device) => device.selected)?.id
      || devices.find((device) => device.is_active)?.id
      || "";
    select.value = devices.some((device) => device.id === preferred) ? preferred : "";
    state.selectedDevice = select.value;
    if (showHint) toast("Device list refreshed, including locally discovered Sonos rooms.");
  } catch (error) { toast(error.message, true); }
}

$("connect").addEventListener("click", () => {
  if ($("connect").textContent.startsWith("Setup")) {
    toast("Add your Spotify client ID to /etc/floppify.env", true);
  } else window.location.href = "/auth/spotify/login";
});
$("play").addEventListener("click", () => command(state.playing ? "/api/pause" : "/api/play"));
$("previous").addEventListener("click", () => command("/api/previous"));
$("next").addEventListener("click", () => command("/api/next"));
$("shuffle").addEventListener("click", () => command("/api/shuffle", { enabled: !state.shuffle }));
$("refresh").addEventListener("click", () => refreshDevices(true));
$("devices").addEventListener("change", async (event) => {
  state.selectedDevice = event.target.value;
  if (state.selectedDevice) await command("/api/transfer");
});
let volumeTimer;
$("volume").addEventListener("input", (event) => {
  window.clearTimeout(volumeTimer);
  volumeTimer = window.setTimeout(() => command("/api/volume", { volume_percent: Number(event.target.value) }), 150);
});

refreshStatus().then(refreshDevices);
window.setInterval(refreshStatus, 3000);
window.setInterval(refreshDevices, 15000);

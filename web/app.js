const $ = (sel) => document.querySelector(sel);

function setStatus(message, { error = false } = {}) {
  const el = $("#status");
  el.textContent = message || "";
  el.classList.toggle("error", Boolean(error));
}

function extractVideoId(input) {
  const raw = (input || "").trim();
  if (!raw) return null;

  const direct = raw.match(/^[a-zA-Z0-9_-]{11}$/);
  if (direct) return direct[0];

  let url;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }

  const host = url.hostname.replace(/^www\./, "");
  if (host === "youtu.be") {
    const id = url.pathname.split("/").filter(Boolean)[0] || "";
    return id.match(/^[a-zA-Z0-9_-]{11}$/) ? id : null;
  }

  if (host.endsWith("youtube.com")) {
    const v = url.searchParams.get("v");
    if (v && v.match(/^[a-zA-Z0-9_-]{11}$/)) return v;

    const parts = url.pathname.split("/").filter(Boolean);
    const maybe = parts[1] || "";
    if (parts[0] === "shorts" || parts[0] === "embed") {
      return maybe.match(/^[a-zA-Z0-9_-]{11}$/) ? maybe : null;
    }
  }

  return null;
}

function extractChannelId(input) {
  const raw = (input || "").trim();
  if (!raw) return null;
  const match = raw.match(/UC[a-zA-Z0-9_-]{22}/);
  return match ? match[0] : null;
}

function extractPlaylistId(input) {
  const raw = (input || "").trim();
  if (!raw) return null;
  const match = raw.match(/PL[a-zA-Z0-9_-]+/);
  return match ? match[0] : null;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium" });
}

function setQuery(updates) {
  const url = new URL(window.location.href);
  Object.entries(updates).forEach(([k, v]) => {
    if (v === null || v === undefined || v === "") url.searchParams.delete(k);
    else url.searchParams.set(k, v);
  });
  history.replaceState(null, "", url);
}

async function fetchJson(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { error: text || `HTTP ${res.status}` };
  }
  if (!res.ok) {
    throw new Error(data?.error || `HTTP ${res.status}`);
  }
  return data;
}

function setPlayer(videoId) {
  const frame = $("#playerFrame");
  const placeholder = $("#playerPlaceholder");
  if (!videoId) {
    frame.src = "";
    placeholder.style.display = "grid";
    return;
  }
  placeholder.style.display = "none";
  const src = new URL(`https://www.youtube-nocookie.com/embed/${videoId}`);
  src.searchParams.set("autoplay", "1");
  src.searchParams.set("rel", "0");
  src.searchParams.set("modestbranding", "1");
  frame.src = src.toString();
}

function renderMeta({ videoId, title, author_name }) {
  $("#metaTitle").textContent = title || (videoId ? `Video: ${videoId}` : "");
  $("#metaByline").textContent = author_name ? `by ${author_name}` : "";

  const actions = $("#metaActions");
  actions.innerHTML = "";
  if (!videoId) return;

  const watch = document.createElement("a");
  watch.href = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
  watch.target = "_blank";
  watch.rel = "noreferrer noopener";
  watch.textContent = "Open on YouTube";

  const share = document.createElement("a");
  const link = new URL(window.location.href);
  link.searchParams.set("v", videoId);
  share.href = link.toString();
  share.textContent = "Permalink";

  actions.append(watch, share);
}

async function loadOEmbed(videoId) {
  try {
    const data = await fetchJson(`/api/oembed?v=${encodeURIComponent(videoId)}`);
    renderMeta({ videoId, ...data });
  } catch {
    renderMeta({ videoId });
  }
}

function renderFeed(feed) {
  $("#resultsTitle").textContent = feed?.title || "Feed";
  $("#resultsSub").textContent = feed?.feedUrl || "";

  const list = $("#resultsList");
  list.innerHTML = "";

  const items = Array.isArray(feed?.items) ? feed.items : [];
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "status";
    empty.textContent = "No items.";
    list.appendChild(empty);
    return;
  }

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "item";

    const thumb = document.createElement("div");
    thumb.className = "thumb";
    if (item.thumbnail) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.src = item.thumbnail;
      thumb.appendChild(img);
    }

    const body = document.createElement("div");

    const title = document.createElement("p");
    title.className = "itemTitle";
    title.textContent = item.title || item.videoId || "Untitled";

    const meta = document.createElement("div");
    meta.className = "itemMeta";
    const date = document.createElement("span");
    date.textContent = formatDate(item.published);
    meta.appendChild(date);

    const open = document.createElement("a");
    open.href = item.link || `https://www.youtube.com/watch?v=${item.videoId}`;
    open.target = "_blank";
    open.rel = "noreferrer noopener";
    open.textContent = "YouTube";
    meta.appendChild(open);

    const desc = document.createElement("div");
    desc.className = "itemDesc";
    desc.textContent = item.description || "";

    body.append(title, meta, desc);
    li.append(thumb, body);

    li.addEventListener("click", (e) => {
      const a = e.target?.closest?.("a");
      if (a) return;
      if (!item.videoId) return;
      playVideo(item.videoId, { pushQuery: true });
    });

    list.appendChild(li);
  }
}

async function loadFeed(params) {
  setStatus("Loading feed…");
  try {
    const url = new URL("/api/feed", window.location.origin);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const data = await fetchJson(url.toString());
    renderFeed(data);
    setStatus("");
  } catch (e) {
    setStatus(e?.message || "Failed to load feed", { error: true });
    renderFeed({ title: "Feed", items: [] });
  }
}

async function playVideo(videoId, { pushQuery = false } = {}) {
  if (!videoId) return;
  setPlayer(videoId);
  if (pushQuery) setQuery({ v: videoId });
  await loadOEmbed(videoId);
}

function bindUI() {
  $("#playBtn").addEventListener("click", async () => {
    const id = extractVideoId($("#videoInput").value);
    if (!id) return setStatus("Couldn’t find a video ID in that input.", { error: true });
    setStatus("");
    await playVideo(id, { pushQuery: true });
  });

  $("#channelBtn").addEventListener("click", async () => {
    const id = extractChannelId($("#channelInput").value);
    if (!id) return setStatus("Enter a channel ID like UC… (handles need a channel ID).", { error: true });
    setQuery({ channel: id, playlist: null });
    await loadFeed({ channel_id: id });
  });

  $("#playlistBtn").addEventListener("click", async () => {
    const id = extractPlaylistId($("#playlistInput").value);
    if (!id) return setStatus("Enter a playlist ID like PL…", { error: true });
    setQuery({ playlist: id, channel: null });
    await loadFeed({ playlist_id: id });
  });
}

async function initFromQuery() {
  const url = new URL(window.location.href);
  const v = url.searchParams.get("v");
  const channel = url.searchParams.get("channel");
  const playlist = url.searchParams.get("playlist");

  if (v) {
    $("#videoInput").value = v;
    const id = extractVideoId(v);
    if (id) await playVideo(id);
  }

  if (channel) {
    $("#channelInput").value = channel;
    const id = extractChannelId(channel);
    if (id) await loadFeed({ channel_id: id });
  } else if (playlist) {
    $("#playlistInput").value = playlist;
    const id = extractPlaylistId(playlist);
    if (id) await loadFeed({ playlist_id: id });
  }
}

bindUI();
initFromQuery();


// Presentation tier: a small single-page app using hash routing.
// It talks only to the API via the same-origin /api path (proxied by nginx).
// All API text is inserted with textContent / text nodes, never innerHTML,
// so post and comment content cannot inject markup.
"use strict";

const API = "/api";
const app = document.getElementById("app");
const nav = document.getElementById("nav");

/* ------------------------------------------------------------------ helpers */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value == null) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "value" || key === "checked" || key === "disabled") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const store = {
  get token() { try { return localStorage.getItem("token"); } catch { return null; } },
  set token(v) { try { v ? localStorage.setItem("token", v) : localStorage.removeItem("token"); } catch { /* ignore */ } },
  get user() { try { return JSON.parse(localStorage.getItem("user")); } catch { return null; } },
  set user(v) { try { v ? localStorage.setItem("user", JSON.stringify(v)) : localStorage.removeItem("user"); } catch { /* ignore */ } },
};

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (store.token) headers.Authorization = "Bearer " + store.token;
  const res = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && store.token) { store.token = null; store.user = null; renderNav(); }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const fmtDate = (iso) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "Not published";
const readTime = (words) => Math.max(1, Math.round((words || 0) / 200)) + " min read";

// Deterministic colourful cover per post, so no image files are needed.
function gradient(seed) {
  const hue = (seed * 47 + 12) % 360;
  return `linear-gradient(135deg, hsl(${hue} 62% 46%), hsl(${(hue + 48) % 360} 70% 38%))`;
}

const isAdmin = () => store.user && store.user.role === "admin";
const notice = (text, kind = "error") => h("div", { class: "notice " + kind, role: "alert" }, text);
const loading = () => h("div", { class: "skeleton" }, "Loading…");

function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(query) };
}

function mount(...nodes) {
  app.replaceChildren(...nodes.flat());
  window.scrollTo(0, 0);
}

function setTitle(text) { document.title = text ? `${text} · The Dev Journal` : "The Dev Journal"; }

/* Render the small post format: ## headings, - bullets, ``` code, paragraphs */
function renderBody(text) {
  const frag = document.createDocumentFragment();
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      frag.append(h("pre", {}, h("code", {}, code.join("\n"))));
    } else if (line.startsWith("## ")) {
      frag.append(h("h2", {}, line.slice(3)));
      i++;
    } else if (line.startsWith("- ")) {
      const ul = h("ul");
      while (i < lines.length && lines[i].startsWith("- ")) ul.append(h("li", {}, lines[i++].slice(2)));
      frag.append(ul);
    } else if (!line.trim()) {
      i++;
    } else {
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(## |- |```)/.test(lines[i])) para.push(lines[i++]);
      frag.append(h("p", {}, para.join(" ")));
    }
  }
  return frag;
}

/* --------------------------------------------------------------- navigation */
function renderNav() {
  const { parts } = parseHash();
  const section = parts[0] || "";
  nav.replaceChildren(
    ...[
      h("a", { href: "#/", class: section === "" || section === "post" ? "active" : "" }, "Home"),
      isAdmin()
        ? [
            h("a", { href: "#/admin", class: section === "admin" ? "active" : "" }, "Dashboard"),
            h("button", { onclick: logout }, "Log out"),
          ]
        : h("a", { href: "#/login", class: section === "login" ? "active" : "" }, "Admin login"),
    ].flat()
  );
}

function logout() {
  store.token = null;
  store.user = null;
  renderNav();
  location.hash = "#/";
}

/* --------------------------------------------------------------- home page */
function postCard(post) {
  const firstTag = post.tags[0] || "Article";
  return h("article", { class: "card" },
    h("div", { class: "cover", style: `background:${gradient(post.id)}` }, firstTag),
    h("div", { class: "card-body" },
      h("h2", {}, h("a", { href: "#/post/" + post.slug }, post.title)),
      h("p", {}, post.excerpt),
      h("div", { class: "meta" },
        h("span", {}, post.author),
        h("span", {}, fmtDate(post.published_at)),
        h("span", {}, readTime(post.word_count)),
        h("span", {}, `${post.comment_count} comment${post.comment_count == 1 ? "" : "s"}`)
      )
    )
  );
}

function homeUrl(params) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v && !(k === "page" && v == 1)) qs.set(k, v);
  const s = qs.toString();
  return "#/" + (s ? "?" + s : "");
}

async function renderHome(params) {
  const page = parseInt(params.get("page") || "1", 10) || 1;
  const tag = params.get("tag") || "";
  const q = params.get("q") || "";
  const filtered = Boolean(tag || q);
  setTitle("");
  mount(loading());

  try {
    const query = new URLSearchParams({ page, per_page: 6 });
    if (tag) query.set("tag", tag);
    if (q) query.set("q", q);
    const [result, tags] = await Promise.all([api("/posts?" + query), api("/tags")]);

    const searchInput = h("input", { type: "search", placeholder: "Search posts…", value: q, "aria-label": "Search posts" });
    const searchForm = h("form", {
      class: "search",
      onsubmit: (e) => { e.preventDefault(); location.hash = homeUrl({ tag, q: searchInput.value.trim() }); },
    }, searchInput, h("button", { class: "btn", type: "submit" }, "Search"));

    const chips = h("div", { class: "chips" },
      h("a", { class: "chip" + (!tag ? " active" : ""), href: homeUrl({ q }) }, "All"),
      tags.map((t) => h("a", { class: "chip" + (tag === t.slug ? " active" : ""), href: homeUrl({ tag: t.slug, q }) },
        t.name, h("small", {}, t.count)))
    );

    const pager = result.pages > 1
      ? h("div", { class: "pager" },
          page > 1 ? h("a", { class: "btn secondary small", href: homeUrl({ tag, q, page: page - 1 }) }, "← Newer") : h("span"),
          h("span", {}, `Page ${result.page} of ${result.pages}`),
          page < result.pages ? h("a", { class: "btn secondary small", href: homeUrl({ tag, q, page: page + 1 }) }, "Older →") : h("span"))
      : null;

    mount(
      filtered ? null : h("section", { class: "hero" },
        h("h1", {}, "Notes on building software, one post at a time."),
        h("p", {}, "Practical articles on Python, databases, APIs and deployment, from people who build things for a living.")),
      h("div", { class: "toolbar" }, searchForm,
        filtered ? h("a", { class: "btn secondary small", href: "#/" }, "Clear filters") : null),
      chips,
      result.items.length
        ? h("div", { class: "grid" }, result.items.map(postCard))
        : h("div", { class: "empty" }, "No posts match your search."),
      pager
    );
  } catch (err) {
    mount(notice(err.message));
  }
}

/* ---------------------------------------------------------------- post page */
async function renderPost(slug) {
  mount(loading());
  try {
    const post = await api("/posts/" + encodeURIComponent(slug));
    setTitle(post.title);

    const list = h("div");
    const drawComments = () => {
      list.replaceChildren(...(post.comments.length
        ? post.comments.map((c) => h("div", { class: "comment" },
            h("div", { class: "comment-head" },
              h("span", {}, h("strong", {}, c.author_name), " · ", fmtDate(c.created_at)),
              isAdmin() ? h("button", {
                class: "btn danger small",
                onclick: async () => {
                  if (!confirm("Delete this comment?")) return;
                  try {
                    await api("/admin/comments/" + c.id, { method: "DELETE" });
                    post.comments = post.comments.filter((x) => x.id !== c.id);
                    drawComments();
                  } catch (err) { alert(err.message); }
                },
              }, "Delete") : null),
            h("p", {}, c.body)))
        : [h("p", { class: "hint" }, "No comments yet. Be the first to share your thoughts.")]));
      heading.textContent = `Comments (${post.comments.length})`;
    };
    const heading = h("h3");

    const nameInput = h("input", { type: "text", maxlength: "80", required: true, placeholder: "Your name" });
    const bodyInput = h("textarea", { rows: "3", maxlength: "2000", required: true, placeholder: "Write a comment…" });
    const msg = h("div");
    const form = h("form", {
      onsubmit: async (e) => {
        e.preventDefault();
        msg.replaceChildren();
        try {
          const c = await api(`/posts/${encodeURIComponent(post.slug)}/comments`, {
            method: "POST", body: { author: nameInput.value, body: bodyInput.value },
          });
          post.comments.push(c);
          bodyInput.value = "";
          drawComments();
          msg.replaceChildren(notice("Thanks for your comment!", "ok"));
        } catch (err) { msg.replaceChildren(notice(err.message)); }
      },
    },
      h("label", {}, "Leave a comment"), nameInput,
      h("div", { style: "height:10px" }), bodyInput,
      msg, h("button", { class: "btn", type: "submit" }, "Post comment"));

    mount(
      h("article", { class: "article" },
        h("a", { class: "back", href: "#/" }, "← All posts"),
        h("div", { class: "article-cover", style: `background:${gradient(post.id)}` }),
        h("div", { class: "chips" }, post.tags.map((t) => h("a", { class: "chip", href: homeUrl({ tag: t.toLowerCase().replace(/[^a-z0-9]+/g, "-") }) }, t))),
        h("h1", {}, post.title),
        h("div", { class: "meta" },
          h("span", {}, "By " + post.author),
          h("span", {}, fmtDate(post.published_at)),
          h("span", {}, readTime(post.word_count)),
          h("span", {}, `${post.views} views`),
          post.published ? null : h("span", { class: "badge-draft" }, "Draft"),
          isAdmin() ? h("a", { href: "#/admin/edit/" + post.id }, "Edit post") : null),
        h("div", { class: "prose" }, renderBody(post.body))
      ),
      h("section", { class: "comments" }, heading, list, h("div", { style: "height:14px" }), form)
    );
    drawComments();
  } catch (err) {
    mount(h("a", { class: "back", href: "#/" }, "← All posts"), notice(err.message));
  }
}

/* --------------------------------------------------------------- login page */
function renderLogin() {
  setTitle("Admin login");
  if (isAdmin()) { location.hash = "#/admin"; return; }
  const user = h("input", { type: "text", autocomplete: "username", required: true, value: "" });
  const pass = h("input", { type: "password", autocomplete: "current-password", required: true });
  const msg = h("div");
  mount(h("div", { class: "login-box" },
    h("h1", {}, "Admin login"),
    h("form", {
      class: "form-card",
      onsubmit: async (e) => {
        e.preventDefault();
        msg.replaceChildren();
        try {
          const data = await api("/auth/login", { method: "POST", body: { username: user.value, password: pass.value } });
          store.token = data.token;
          store.user = data.user;
          renderNav();
          location.hash = "#/admin";
        } catch (err) { msg.replaceChildren(notice(err.message)); }
      },
    }, h("label", {}, "Username"), user, h("label", {}, "Password"), pass, msg,
       h("div", { style: "height:16px" }), h("button", { class: "btn", type: "submit" }, "Log in"))
  ));
  user.focus();
}

/* ---------------------------------------------------------------- dashboard */
async function renderAdmin() {
  setTitle("Dashboard");
  if (!isAdmin()) { location.hash = "#/login"; return; }
  mount(loading());
  try {
    const [stats, posts] = await Promise.all([api("/admin/stats"), api("/admin/posts")]);

    const statBox = (n, label) => h("div", { class: "stat" }, h("b", {}, n), h("span", {}, label));

    const rows = posts.map((p) => h("tr", {},
      h("td", {}, h("a", { href: "#/post/" + p.slug }, p.title)),
      h("td", {}, p.published ? h("span", { class: "badge-live" }, "Published") : h("span", { class: "badge-draft" }, "Draft")),
      h("td", {}, p.tags.join(", ") || "-"),
      h("td", {}, p.views),
      h("td", {}, p.comment_count),
      h("td", {}, fmtDate(p.updated_at)),
      h("td", {}, h("div", { class: "actions" },
        h("a", { class: "btn secondary small", href: "#/admin/edit/" + p.id }, "Edit"),
        h("button", {
          class: "btn secondary small",
          onclick: async () => {
            try { await api("/admin/posts/" + p.id, { method: "PUT", body: { published: !p.published } }); renderAdmin(); }
            catch (err) { alert(err.message); }
          },
        }, p.published ? "Unpublish" : "Publish"),
        h("button", {
          class: "btn danger small",
          onclick: async () => {
            if (!confirm(`Delete "${p.title}"? This also deletes its comments.`)) return;
            try { await api("/admin/posts/" + p.id, { method: "DELETE" }); renderAdmin(); }
            catch (err) { alert(err.message); }
          },
        }, "Delete")))));

    mount(h("section", { class: "dash" },
      h("div", { class: "dash-head" },
        h("h1", {}, "Dashboard"),
        h("a", { class: "btn", href: "#/admin/new" }, "+ New post")),
      h("div", { class: "stats" },
        statBox(stats.posts, "Total posts"), statBox(stats.published, "Published"),
        statBox(stats.drafts, "Drafts"), statBox(stats.views, "Total views"), statBox(stats.comments, "Comments")),
      h("div", { class: "table-wrap" },
        h("table", {},
          h("thead", {}, h("tr", {}, ["Title", "Status", "Tags", "Views", "Comments", "Updated", ""].map((t) => h("th", {}, t)))),
          h("tbody", {}, rows)))));
  } catch (err) {
    mount(notice(err.message));
  }
}

/* ------------------------------------------------------------------- editor */
async function renderEditor(id) {
  if (!isAdmin()) { location.hash = "#/login"; return; }
  setTitle(id ? "Edit post" : "New post");
  mount(loading());
  let post = { title: "", body: "", excerpt: "", tags: [], published: false };
  try { if (id) post = await api("/admin/posts/" + id); }
  catch (err) { mount(notice(err.message)); return; }

  const title = h("input", { type: "text", maxlength: "200", required: true, value: post.title });
  const tags = h("input", { type: "text", placeholder: "python, api, tutorial", value: post.tags.join(", ") });
  const excerpt = h("textarea", { rows: "2", maxlength: "400", placeholder: "Leave empty to generate from the first paragraph" });
  excerpt.value = post.excerpt;
  const body = h("textarea", { rows: "16", required: true });
  body.value = post.body;
  const published = h("input", { type: "checkbox", checked: post.published });
  const msg = h("div");

  mount(h("section", { class: "editor" },
    h("a", { class: "back", href: "#/admin" }, "← Dashboard"),
    h("h1", {}, id ? "Edit post" : "New post"),
    h("form", {
      class: "form-card",
      onsubmit: async (e) => {
        e.preventDefault();
        msg.replaceChildren();
        const payload = { title: title.value, body: body.value, excerpt: excerpt.value, tags: tags.value, published: published.checked };
        try {
          const saved = id
            ? await api("/admin/posts/" + id, { method: "PUT", body: payload })
            : await api("/admin/posts", { method: "POST", body: payload });
          location.hash = "#/post/" + saved.slug;
        } catch (err) { msg.replaceChildren(notice(err.message)); }
      },
    },
      h("label", {}, "Title"), title,
      h("label", {}, "Tags ", h("small", {}, "(comma separated, max 8)")), tags,
      h("label", {}, "Excerpt ", h("small", {}, "(optional)")), excerpt,
      h("label", {}, "Body"), body,
      h("p", { class: "hint" }, "Formatting: ## Heading, - bullet point, and ``` fenced code blocks. Blank lines separate paragraphs."),
      h("label", { class: "check" }, published, "Published (visible to everyone)"),
      msg,
      h("div", { class: "row", style: "margin-top:18px" },
        h("button", { class: "btn", type: "submit" }, id ? "Save changes" : "Create post"),
        h("a", { class: "btn secondary", href: "#/admin" }, "Cancel")))));
  title.focus();
}

/* ------------------------------------------------------------------- router */
function route() {
  renderNav();
  const { parts, params } = parseHash();
  const [section, a, b] = parts;
  if (!section) return renderHome(params);
  if (section === "post" && a) return renderPost(a);
  if (section === "login") return renderLogin();
  if (section === "admin" && !a) return renderAdmin();
  if (section === "admin" && a === "new") return renderEditor(null);
  if (section === "admin" && a === "edit" && b) return renderEditor(parseInt(b, 10));
  setTitle("Not found");
  mount(h("div", { class: "empty" }, h("h1", {}, "Page not found"), h("a", { class: "btn", href: "#/" }, "Back to home")));
}

async function checkHealth() {
  const el = document.getElementById("health");
  try {
    await api("/health");
    el.textContent = "API & database online";
    el.className = "health ok";
  } catch {
    el.textContent = "API unreachable";
    el.className = "health down";
  }
}

window.addEventListener("hashchange", route);
route();
checkHealth();
setInterval(checkHealth, 30000);

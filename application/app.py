"""Application tier: Flask REST API for the blog / CMS.

This is the only component that talks to PostgreSQL. The presentation tier
(nginx + static files) calls it over HTTP. Public endpoints serve published
content; /api/admin/* endpoints require a JWT issued by /api/auth/login.
"""
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import wraps

import jwt
import psycopg2
from flask import Flask, g, jsonify, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
JWT_HOURS = int(os.getenv("JWT_HOURS", "12"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
PER_PAGE_MAX = 24


class JSONProvider(DefaultJSONProvider):
    """Serialise dates as ISO-8601 strings."""

    @staticmethod
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def connect_with_retry(retries: int = 20, delay: float = 2.0):
    """The DB container may still be starting; retry before giving up."""
    dsn = dict(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "blogdb"),
        user=os.getenv("DB_USER", "bloguser"),
        password=os.getenv("DB_PASSWORD", "blogpass"),
    )
    last = None
    for attempt in range(1, retries + 1):
        try:
            return pool.ThreadedConnectionPool(1, 10, **dsn)
        except psycopg2.OperationalError as exc:
            last = exc
            print(f"[db] attempt {attempt}/{retries} failed, retrying...", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to database: {last}")


db_pool = connect_with_retry()


@contextmanager
def db():
    """Yield a cursor inside a transaction; commit on success, roll back on error."""
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db_pool.putconn(conn)


def ensure_admin():
    """Create or update the admin login from ADMIN_USERNAME / ADMIN_PASSWORD."""
    with db() as cur:
        cur.execute(
            """INSERT INTO users (username, display_name, password_hash, role)
               VALUES (%s, 'Admin', %s, 'admin')
               ON CONFLICT (username)
               DO UPDATE SET password_hash = EXCLUDED.password_hash, role = 'admin'""",
            (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)),
        )


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def unique_slug(cur, base: str, exclude_id=None) -> str:
    base = base or "post"
    slug, n = base, 2
    while True:
        cur.execute(
            "SELECT 1 FROM posts WHERE slug = %s AND id <> COALESCE(%s, -1)",
            (slug, exclude_id),
        )
        if not cur.fetchone():
            return slug
        slug = f"{base}-{n}"
        n += 1


def make_excerpt(body: str, limit: int = 180) -> str:
    for block in re.split(r"\n\s*\n", body.strip()):
        text = block.strip()
        if text and not text.startswith(("##", "```", "- ")):
            text = " ".join(text.split())
            return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
    return ""


def like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def parse_tags(raw):
    """Accept a list or comma-separated string; return [(name, slug)] (max 8)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        raise ValueError("tags must be a list or comma-separated string")
    seen, result = set(), []
    for item in raw:
        name = " ".join(str(item).split())
        if not name:
            continue
        if len(name) > 30:
            raise ValueError("each tag must be 30 characters or fewer")
        slug = slugify(name)
        if slug and slug not in seen:
            seen.add(slug)
            result.append((name, slug))
    if len(result) > 8:
        raise ValueError("a post can have at most 8 tags")
    return result


def set_tags(cur, post_id: int, tags):
    cur.execute("DELETE FROM post_tags WHERE post_id = %s", (post_id,))
    for name, slug in tags:
        cur.execute(
            """INSERT INTO tags (name, slug) VALUES (%s, %s)
               ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug
               RETURNING id""",
            (name, slug),
        )
        cur.execute(
            "INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s)",
            (post_id, cur.fetchone()["id"]),
        )
    cur.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM post_tags)")


POST_LIST_SQL = """
SELECT p.id, p.title, p.slug, p.excerpt, p.published, p.published_at,
       p.created_at, p.updated_at, p.views,
       u.display_name AS author,
       COALESCE(array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL), '{}') AS tags,
       (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comment_count,
       array_length(regexp_split_to_array(btrim(p.body), '\\s+'), 1) AS word_count
FROM posts p
JOIN users u ON u.id = p.author_id
LEFT JOIN post_tags pt ON pt.post_id = p.id
LEFT JOIN tags t ON t.id = pt.tag_id
"""


def validate_post(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("Body must be a JSON object")
    data = {}
    if "title" in payload or not partial:
        title = " ".join(str(payload.get("title", "")).split())
        if not title:
            raise ValueError("title is required")
        if len(title) > 200:
            raise ValueError("title must be 200 characters or fewer")
        data["title"] = title
    if "body" in payload or not partial:
        body = str(payload.get("body", "")).strip()
        if not body:
            raise ValueError("body is required")
        if len(body) > 50000:
            raise ValueError("body is too long (max 50,000 characters)")
        data["body"] = body
    if "excerpt" in payload:
        excerpt = str(payload["excerpt"]).strip()
        if len(excerpt) > 400:
            raise ValueError("excerpt must be 400 characters or fewer")
        data["excerpt"] = excerpt
    if "published" in payload:
        data["published"] = bool(payload["published"])
    if "tags" in payload:
        data["tags"] = parse_tags(payload["tags"])
    return data


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def make_token(user) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "iat": now,
            "exp": now + timedelta(hours=JWT_HOURS),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def current_user():
    """Return the JWT claims if a valid token was sent, else None."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        return jwt.decode(header[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify(error="authentication required"), 401
        if user.get("role") != "admin":
            return jsonify(error="admin access required"), 403
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# App + routes
# ---------------------------------------------------------------------------
def create_app() -> Flask:
    app = Flask(__name__)
    app.json = JSONProvider(app)
    CORS(app, origins=os.getenv("CORS_ORIGINS", "*").split(","))

    if JWT_SECRET == "dev-only-secret-change-me":
        print("[warn] JWT_SECRET is the default value; set a strong one!", flush=True)

    ensure_admin()

    # ---- health ----------------------------------------------------------
    @app.get("/api/health")
    def health():
        try:
            with db() as cur:
                cur.execute("SELECT 1")
            return jsonify(status="ok", database="up")
        except Exception:
            return jsonify(status="degraded", database="down"), 503

    # ---- auth ------------------------------------------------------------
    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        with db() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify(error="invalid username or password"), 401
        return jsonify(
            token=make_token(user),
            user={"id": user["id"], "username": user["username"],
                  "display_name": user["display_name"], "role": user["role"]},
        )

    @app.get("/api/auth/me")
    def me():
        user = current_user()
        if not user:
            return jsonify(error="authentication required"), 401
        return jsonify(user={"id": int(user["sub"]), "username": user["username"],
                             "role": user["role"]})

    # ---- public: posts ---------------------------------------------------
    @app.get("/api/posts")
    def list_posts():
        try:
            page = max(1, int(request.args.get("page", 1)))
            per_page = min(PER_PAGE_MAX, max(1, int(request.args.get("per_page", 6))))
        except ValueError:
            return jsonify(error="page and per_page must be integers"), 400

        where, params = ["p.published = TRUE"], []
        tag = request.args.get("tag", "").strip()
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM post_tags x JOIN tags xt ON xt.id = x.tag_id "
                "WHERE x.post_id = p.id AND xt.slug = %s)"
            )
            params.append(tag)
        q = request.args.get("q", "").strip()
        if q:
            where.append("(p.title ILIKE %s OR p.body ILIKE %s OR p.excerpt ILIKE %s)")
            params += [like_pattern(q)] * 3
        clause = " WHERE " + " AND ".join(where)

        with db() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM posts p{clause}", params)
            total = cur.fetchone()["n"]
            cur.execute(
                POST_LIST_SQL + clause +
                " GROUP BY p.id, u.display_name"
                " ORDER BY p.published_at DESC, p.id DESC LIMIT %s OFFSET %s",
                params + [per_page, (page - 1) * per_page],
            )
            items = cur.fetchall()
        return jsonify(items=items, page=page, per_page=per_page, total=total,
                       pages=max(1, -(-total // per_page)))

    @app.get("/api/posts/<slug>")
    def get_post(slug):
        is_admin = (current_user() or {}).get("role") == "admin"
        with db() as cur:
            cur.execute(
                POST_LIST_SQL + " WHERE p.slug = %s GROUP BY p.id, u.display_name", (slug,)
            )
            post = cur.fetchone()
            if not post or (not post["published"] and not is_admin):
                return jsonify(error="post not found"), 404
            cur.execute("SELECT body FROM posts WHERE id = %s", (post["id"],))
            post["body"] = cur.fetchone()["body"]
            if post["published"]:
                cur.execute("UPDATE posts SET views = views + 1 WHERE id = %s RETURNING views",
                            (post["id"],))
                post["views"] = cur.fetchone()["views"]
            cur.execute(
                "SELECT id, author_name, body, created_at FROM comments "
                "WHERE post_id = %s ORDER BY created_at", (post["id"],)
            )
            post["comments"] = cur.fetchall()
        return jsonify(post)

    @app.post("/api/posts/<slug>/comments")
    def add_comment(slug):
        payload = request.get_json(silent=True) or {}
        author = " ".join(str(payload.get("author", "")).split())
        body = str(payload.get("body", "")).strip()
        if not author or len(author) > 80:
            return jsonify(error="name is required (max 80 characters)"), 400
        if not body or len(body) > 2000:
            return jsonify(error="comment is required (max 2000 characters)"), 400
        with db() as cur:
            cur.execute("SELECT id FROM posts WHERE slug = %s AND published = TRUE", (slug,))
            post = cur.fetchone()
            if not post:
                return jsonify(error="post not found"), 404
            cur.execute(
                "INSERT INTO comments (post_id, author_name, body) VALUES (%s, %s, %s) "
                "RETURNING id, author_name, body, created_at",
                (post["id"], author, body),
            )
            comment = cur.fetchone()
        return jsonify(comment), 201

    # ---- public: tags ----------------------------------------------------
    @app.get("/api/tags")
    def list_tags():
        with db() as cur:
            cur.execute(
                """SELECT t.name, t.slug, COUNT(p.id) AS count
                   FROM tags t
                   JOIN post_tags pt ON pt.tag_id = t.id
                   JOIN posts p ON p.id = pt.post_id AND p.published = TRUE
                   GROUP BY t.id ORDER BY count DESC, t.name"""
            )
            return jsonify(cur.fetchall())

    # ---- admin -----------------------------------------------------------
    @app.get("/api/admin/stats")
    @admin_required
    def stats():
        with db() as cur:
            cur.execute(
                """SELECT COUNT(*) AS posts,
                          COUNT(*) FILTER (WHERE published) AS published,
                          COUNT(*) FILTER (WHERE NOT published) AS drafts,
                          COALESCE(SUM(views), 0) AS views,
                          (SELECT COUNT(*) FROM comments) AS comments
                   FROM posts"""
            )
            return jsonify(cur.fetchone())

    @app.get("/api/admin/posts")
    @admin_required
    def admin_list_posts():
        with db() as cur:
            cur.execute(POST_LIST_SQL + " GROUP BY p.id, u.display_name ORDER BY p.created_at DESC, p.id DESC")
            return jsonify(cur.fetchall())

    @app.get("/api/admin/posts/<int:post_id>")
    @admin_required
    def admin_get_post(post_id):
        with db() as cur:
            cur.execute(
                POST_LIST_SQL + " WHERE p.id = %s GROUP BY p.id, u.display_name", (post_id,)
            )
            post = cur.fetchone()
            if not post:
                return jsonify(error="post not found"), 404
            cur.execute("SELECT body FROM posts WHERE id = %s", (post_id,))
            post["body"] = cur.fetchone()["body"]
        return jsonify(post)

    @app.post("/api/admin/posts")
    @admin_required
    def create_post():
        try:
            data = validate_post(request.get_json(silent=True))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        published = data.get("published", False)
        with db() as cur:
            slug = unique_slug(cur, slugify(data["title"]))
            cur.execute(
                """INSERT INTO posts (title, slug, excerpt, body, author_id, published, published_at)
                   VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END)
                   RETURNING id, slug""",
                (data["title"], slug,
                 data.get("excerpt") or make_excerpt(data["body"]),
                 data["body"], int(g.user["sub"]), published, published),
            )
            row = cur.fetchone()
            set_tags(cur, row["id"], data.get("tags", []))
        return jsonify(row), 201

    @app.put("/api/admin/posts/<int:post_id>")
    @admin_required
    def update_post(post_id):
        try:
            data = validate_post(request.get_json(silent=True), partial=True)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if not data:
            return jsonify(error="nothing to update"), 400
        with db() as cur:
            cur.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
            current = cur.fetchone()
            if not current:
                return jsonify(error="post not found"), 404

            title = data.get("title", current["title"])
            body = data.get("body", current["body"])
            excerpt = data["excerpt"] if "excerpt" in data else current["excerpt"]
            if not excerpt:
                excerpt = make_excerpt(body)
            published = data.get("published", current["published"])
            slug = unique_slug(cur, slugify(title), exclude_id=post_id) \
                if title != current["title"] else current["slug"]

            cur.execute(
                """UPDATE posts SET title = %s, slug = %s, excerpt = %s, body = %s,
                       published = %s,
                       published_at = CASE WHEN %s AND published_at IS NULL
                                           THEN NOW() ELSE published_at END,
                       updated_at = NOW()
                   WHERE id = %s RETURNING id, slug""",
                (title, slug, excerpt, body, published, published, post_id),
            )
            row = cur.fetchone()
            if "tags" in data:
                set_tags(cur, post_id, data["tags"])
        return jsonify(row)

    @app.delete("/api/admin/posts/<int:post_id>")
    @admin_required
    def delete_post(post_id):
        with db() as cur:
            cur.execute("DELETE FROM posts WHERE id = %s RETURNING id", (post_id,))
            if not cur.fetchone():
                return jsonify(error="post not found"), 404
            cur.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM post_tags)")
        return "", 204

    @app.delete("/api/admin/comments/<int:comment_id>")
    @admin_required
    def delete_comment(comment_id):
        with db() as cur:
            cur.execute("DELETE FROM comments WHERE id = %s RETURNING id", (comment_id,))
            if not cur.fetchone():
                return jsonify(error="comment not found"), 404
        return "", 204

    # ---- errors ----------------------------------------------------------
    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(_):
        return jsonify(error="method not allowed"), 405

    @app.errorhandler(500)
    def server_error(_):
        return jsonify(error="internal server error"), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")

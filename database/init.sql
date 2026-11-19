-- ===========================================================================
-- Data tier: PostgreSQL schema + demo content.
-- The app runs this file automatically the first time it connects to an
-- empty database, so the site has posts to show right away. (You can also run
-- it by hand:  psql -U bloguser -d blogdb -f database/init.sql)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    display_name  VARCHAR(100) NOT NULL,
    bio           TEXT         NOT NULL DEFAULT '',
    password_hash TEXT         NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'author'
                  CHECK (role IN ('admin', 'author')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS posts (
    id           SERIAL PRIMARY KEY,
    title        VARCHAR(200) NOT NULL,
    slug         VARCHAR(220) NOT NULL UNIQUE,
    excerpt      TEXT         NOT NULL DEFAULT '',
    body         TEXT         NOT NULL,
    author_id    INTEGER      NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    published    BOOLEAN      NOT NULL DEFAULT FALSE,
    published_at TIMESTAMPTZ,
    views        INTEGER      NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts (published, published_at DESC);

CREATE TABLE IF NOT EXISTS tags (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(40) NOT NULL,
    slug VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS post_tags (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER      NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_name VARCHAR(80)  NOT NULL,
    body        TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments (post_id, created_at);

-- ---------------------------------------------------------------------------
-- Demo data
-- ---------------------------------------------------------------------------

-- The password hash '!' can never match, so these accounts cannot log in.
-- The API sets the real admin password from ADMIN_PASSWORD at startup.
INSERT INTO users (id, username, display_name, bio, password_hash, role) VALUES
 (1, 'admin', 'Admin', 'Editor of The Dev Journal.', '!', 'admin'),
 (2, 'priya', 'Priya Sharma', 'Backend engineer who loves databases and clean APIs.', '!', 'author'),
 (3, 'arjun', 'Arjun Mehta', 'Full-stack developer and part-time automation enthusiast.', '!', 'author');

INSERT INTO tags (id, name, slug) VALUES
 (1, 'Announcements', 'announcements'),
 (2, 'Architecture',  'architecture'),
 (3, 'Backend',       'backend'),
 (4, 'Python',        'python'),
 (5, 'Database',      'database'),
 (6, 'PostgreSQL',    'postgresql'),
 (7, 'Testing',       'testing'),
 (8, 'DevOps',        'devops'),
 (9, 'API',           'api'),
 (10,'JavaScript',    'javascript'),
 (11,'Frontend',      'frontend'),
 (12,'Security',      'security');

INSERT INTO posts (id, title, slug, excerpt, body, author_id, published, published_at, views) VALUES

(1, 'Welcome to The Dev Journal', 'welcome-to-the-dev-journal',
 'A quick tour of this blog, how it is built, and how to start writing your own posts.',
$body$Welcome! The Dev Journal is a small blog about building software, written to show how a real three-tier web application fits together.

## What you are looking at

Everything you see here comes from a PostgreSQL database. A Python API reads the posts, tags and comments, and a lightweight frontend turns them into the pages you are browsing right now.

## Try it out

- Browse posts on the home page, or filter them by tag
- Use the search box to find a topic
- Leave a comment at the bottom of any post
- Log in as the admin to write, edit, publish and delete posts

## Writing your own posts

Posts support a tiny bit of formatting: lines starting with two hashes become headings, lines starting with a dash become bullet points, and blocks fenced with three backticks become code. That is all you need for most articles.

Happy reading, and happy writing.$body$,
 1, TRUE, NOW() - INTERVAL '1 day', 214),

(2, 'Understanding Three-Tier Architecture', 'understanding-three-tier-architecture',
 'Presentation, application and data: why splitting a web app into three layers makes it easier to build, scale and secure.',
$body$Most web applications, from tiny hobby projects to large commercial platforms, can be understood as three layers that each do one job well.

## The three tiers

- Presentation: what the user sees and clicks, usually HTML, CSS and JavaScript
- Application: the business logic, validation and rules, exposed as an API
- Data: the database that stores everything permanently

## Why separate them?

Each tier can change without breaking the others. You can redesign the website without touching the database, swap the database engine behind the API, or run several copies of the API to handle more traffic.

It is also safer. Only the application tier talks to the database, so the outside world never reaches your data directly. A request has to pass through the API, where it is checked and logged.

## A tiny example

When you open a post on this blog, the browser asks the API for it. The API runs one query against PostgreSQL and returns JSON. The browser turns that JSON into the page you read.

```
Browser -> Flask API -> PostgreSQL
```

Keep this picture in mind and most backend design questions become easier to answer.$body$,
 2, TRUE, NOW() - INTERVAL '3 days', 389),

(3, 'Seven Python Habits That Make Code Easier to Maintain', 'seven-python-habits-for-maintainable-code',
 'Small, practical habits that keep Python projects readable months after you wrote them.',
$body$Good Python is not about clever tricks. It is about code your future self can read quickly. These habits have saved me the most time.

## The habits

- Name things for what they mean, not how they work
- Keep functions short and focused on one job
- Add type hints to public functions
- Prefer pathlib over string manipulation for file paths
- Use f-strings for readable formatting
- Handle specific exceptions, never a bare except
- Write a test for every bug you fix

## Type hints in practice

Type hints cost a few seconds to write and pay back every time you read the function again.

```
def total_price(items: list[float], tax_rate: float = 0.18) -> float:
    return round(sum(items) * (1 + tax_rate), 2)
```

## Start small

You do not need to adopt all seven at once. Pick one, apply it to your next pull request, and add another next week. Consistency beats intensity.$body$,
 3, TRUE, NOW() - INTERVAL '6 days', 301),

(4, 'Why PostgreSQL Is a Great Default Database', 'why-postgresql-is-a-great-default-database',
 'Reliable, standards-compliant and surprisingly capable: the case for choosing PostgreSQL first.',
$body$If you are starting a new project and are not sure which database to pick, PostgreSQL is a safe and powerful default.

## Reasons to choose it

- It is open source and has been developed for decades
- It follows SQL standards closely, so your skills transfer
- It supports transactions, constraints and foreign keys that protect your data
- It handles JSON, full-text search and arrays when you need them
- Every major cloud offers a managed version

## Let the database enforce the rules

A good habit is to put rules in the database as well as in application code. This blog, for example, uses a unique constraint on post slugs, so two posts can never share a URL, even if a bug slips through the API.

```
ALTER TABLE posts ADD CONSTRAINT posts_slug_unique UNIQUE (slug);
```

## When to look elsewhere

For huge write-heavy event streams or very specialised workloads, other systems may fit better. For most web applications, PostgreSQL will carry you very far.$body$,
 2, TRUE, NOW() - INTERVAL '9 days', 267),

(5, 'Testing Your API with curl', 'testing-your-api-with-curl',
 'Check every endpoint from the command line before you ever write a line of frontend code.',
$body$Before building a user interface, it pays to check that the API behaves. The curl command is installed almost everywhere and is perfect for the job.

## What to test

- The happy path: does each endpoint return what you expect?
- Bad input: do you get a clear 400 error instead of a crash?
- Missing login: do protected routes return 401?
- Unknown things: do missing records return 404?

## A first request

```
curl http://localhost:8000/api/posts
```

## Make it a habit

Every time you fix a bug, add the request that exposed it to a small script. After a few weeks you will have a safety net that catches mistakes before your users do.$body$,
 3, TRUE, NOW() - INTERVAL '12 days', 178),

(6, 'Designing a Friendly REST API', 'designing-a-friendly-rest-api',
 'Clear URLs, honest status codes and helpful errors: the small details that make an API pleasant to use.',
$body$An API is a user interface for other programmers. A few simple conventions make yours much easier to work with.

## Use nouns and standard methods

- GET /posts lists posts
- GET /posts/some-slug fetches one
- POST /posts creates one
- PUT /posts/12 updates it
- DELETE /posts/12 removes it

## Return honest status codes

Use 201 when something is created, 204 when there is nothing to return, 400 for bad input, 401 when login is needed, 404 when something does not exist. Clients can then react correctly without parsing your messages.

## Make errors helpful

An error should say what went wrong in plain words, in a predictable shape.

```
{"error": "title is required"}
```

## Always validate input

Never trust data from the client. Check lengths, types and allowed values on the server, and use parameterised queries so user input can never be run as SQL.$body$,
 2, TRUE, NOW() - INTERVAL '15 days', 245),

(7, 'Building a Frontend Without a Framework', 'building-a-frontend-without-a-framework',
 'Modern browsers can do a lot on their own. Here is how far plain JavaScript can take you.',
$body$Frameworks are wonderful, but they are not always necessary. For small and medium sites, plain JavaScript is fast, tiny and easy to understand.

## What the browser already gives you

- fetch for talking to your API
- Hash-based routing for simple page navigation
- Template-free rendering with document.createElement
- CSS grid and custom properties for layout and theming

## Keep it safe

When you insert text from an API into a page, set textContent instead of innerHTML. That single habit prevents most cross-site scripting bugs, because the browser treats the text as text, never as markup.

## When to reach for a framework

If your interface grows many interactive components that share state, a framework starts to pay for itself. Until then, a few hundred lines of plain JavaScript are easier to debug and load instantly.$body$,
 3, TRUE, NOW() - INTERVAL '19 days', 156),

(8, 'A Practical Checklist for Deploying to Production', 'practical-checklist-for-deploying-to-production',
 'Before you put your app on the internet, run through this short list of security and reliability basics.',
$body$Getting an app running on a server is the easy part. Keeping it safe and reliable takes a little more care. Use this checklist before you go live.

## Security

- Change every default password and secret
- Serve the site over HTTPS only
- Keep database ports closed to the internet
- Store secrets in environment variables, never in git
- Validate input and use parameterised queries

## Reliability

- Add health checks and restart policies
- Back up the database on a schedule, and test restoring it
- Send logs somewhere you can read them
- Know how to roll back a bad release

## Keep improving

No checklist is ever finished. Review it after every incident, and add the lesson you just learned.$body$,
 1, TRUE, NOW() - INTERVAL '24 days', 198),

(9, 'Coming Soon: A Beginner Guide to Caching', 'coming-soon-beginner-guide-to-caching',
 'A draft post that only the admin can see.',
$body$This is an unpublished draft. Visitors cannot see it, but you can find it in the admin dashboard, finish writing it and publish it with one click.$body$,
 1, FALSE, NULL, 0);

INSERT INTO post_tags (post_id, tag_id) VALUES
 (1, 1),
 (2, 2), (2, 3),
 (3, 4),
 (4, 5), (4, 6),
 (5, 7), (5, 9),
 (6, 9), (6, 3), (6, 4),
 (7, 10), (7, 11),
 (8, 8), (8, 12),
 (9, 3);

INSERT INTO comments (post_id, author_name, body, created_at) VALUES
 (1, 'Rahul',  'Nice clean design. Looking forward to more posts!', NOW() - INTERVAL '20 hours'),
 (1, 'Sneha',  'Love that the demo already has content in it.',      NOW() - INTERVAL '10 hours'),
 (2, 'Karthik','The diagram at the end made it click for me. Thanks!', NOW() - INTERVAL '2 days'),
 (2, 'Meera',  'Could you write one about scaling the API tier next?', NOW() - INTERVAL '1 day'),
 (4, 'Vikram', 'Switched my side project to PostgreSQL after reading this.', NOW() - INTERVAL '5 days'),
 (6, 'Anita',  'The status code section is a handy reference.',       NOW() - INTERVAL '10 days');

-- Keep the SERIAL counters ahead of the ids inserted above.
SELECT setval(pg_get_serial_sequence('users',    'id'), (SELECT MAX(id) FROM users));
SELECT setval(pg_get_serial_sequence('posts',    'id'), (SELECT MAX(id) FROM posts));
SELECT setval(pg_get_serial_sequence('tags',     'id'), (SELECT MAX(id) FROM tags));
SELECT setval(pg_get_serial_sequence('comments', 'id'), (SELECT MAX(id) FROM comments));

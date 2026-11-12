-- Deterministic synthetic data generator (no external files needed).
-- ~27k orders / ~51k order items for 2025-01-01 .. 2026-10-31.
-- Planted business signals for the demo:
--   * Q2 2026 demand drop: "Аудио" (-48.6%), "Игры и консоли" (-31.5%), "Смартфоны" (-27.5%)
--   * Q2 2026 laptop boom: "Ноутбуки" grows vs Q1
--   * Seasonality: November / December peaks, steady growth trend
--   * NULLs in customers.city (~3%) and orders.channel (~3%)

SELECT setseed(0.42);

INSERT INTO categories (name) VALUES
    ('Ноутбуки'), ('Смартфоны'), ('Аудио'), ('Бытовая техника'),
    ('Аксессуары'), ('Серверное оборудование'), ('Игры и консоли'), ('Книги');

-- 15 products per category -------------------------------------------------
WITH cfg (cat, prefix, min_price, max_price, brands) AS (
    VALUES
        ('Ноутбуки',               'Ноутбук',     55000, 160000, ARRAY['Lenovo', 'ASUS', 'Huawei', 'HP', 'Acer']),
        ('Смартфоны',              'Смартфон',    15000,  95000, ARRAY['Samsung', 'Xiaomi', 'realme', 'HONOR', 'Tecno']),
        ('Аудио',                  'Наушники',     2500,  35000, ARRAY['Sony', 'JBL', 'Marshall', 'Sennheiser', 'Edifier']),
        ('Бытовая техника',        'Техника',      6000,  70000, ARRAY['Bosch', 'Philips', 'Redmond', 'Polaris', 'Tefal']),
        ('Аксессуары',             'Аксессуар',     400,   6000, ARRAY['Baseus', 'Ugreen', 'Anker', 'Hoco', 'Deppa']),
        ('Серверное оборудование', 'Сервер',     150000, 450000, ARRAY['Dell', 'Supermicro', 'Lenovo', 'HPE', 'Huawei']),
        ('Игры и консоли',         'Игровой',      2500,  65000, ARRAY['Sony', 'Microsoft', 'Nintendo', 'Valve', 'Logitech']),
        ('Книги',                  'Книга',         350,   2500, ARRAY['МИФ', 'Питер', 'АСТ', 'Эксмо', 'Альпина'])
)
INSERT INTO products (name, category_id, price, cost, is_active)
SELECT
    format('%s %s %s-%s', cfg.prefix, cfg.brands[1 + (n % 5)], upper(substr(md5(cfg.cat || n), 1, 2)), 100 + n * 7),
    c.id,
    p.price,
    round(p.price * (0.55 + p.r_cost * 0.25)::numeric, 2),
    p.r_active > 0.05
FROM cfg
JOIN categories c ON c.name = cfg.cat
CROSS JOIN generate_series(1, 15) AS n
CROSS JOIN LATERAL (
    SELECT
        round((cfg.min_price + random() * (cfg.max_price - cfg.min_price))::numeric, -1) AS price,
        random() AS r_cost,
        random() AS r_active,
        n AS _n
) AS p
ORDER BY c.id, n;

-- 2000 customers ------------------------------------------------------------
INSERT INTO customers (full_name, email, city, segment, registered_at)
SELECT
    CASE WHEN r.r_gender < 0.5
        THEN (ARRAY['Иванов', 'Смирнов', 'Кузнецов', 'Попов', 'Васильев', 'Петров', 'Соколов', 'Михайлов', 'Новиков', 'Фёдоров', 'Морозов', 'Волков'])[1 + floor(r.r_last * 12)::int]
             || ' ' ||
             (ARRAY['Александр', 'Дмитрий', 'Максим', 'Сергей', 'Андрей', 'Алексей', 'Артём', 'Илья', 'Кирилл', 'Михаил'])[1 + floor(r.r_first * 10)::int]
        ELSE (ARRAY['Иванова', 'Смирнова', 'Кузнецова', 'Попова', 'Васильева', 'Петрова', 'Соколова', 'Михайлова', 'Новикова', 'Фёдорова', 'Морозова', 'Волкова'])[1 + floor(r.r_last * 12)::int]
             || ' ' ||
             (ARRAY['Анна', 'Мария', 'Елена', 'Ольга', 'Наталья', 'Екатерина', 'Татьяна', 'Ирина', 'Дарья', 'Полина'])[1 + floor(r.r_first * 10)::int]
    END,
    format('customer%s@example.com', g),
    CASE
        WHEN r.r_city < 0.03 THEN NULL
        WHEN r.r_city < 0.33 THEN 'Москва'
        WHEN r.r_city < 0.51 THEN 'Санкт-Петербург'
        WHEN r.r_city < 0.59 THEN 'Новосибирск'
        WHEN r.r_city < 0.67 THEN 'Екатеринбург'
        WHEN r.r_city < 0.75 THEN 'Казань'
        WHEN r.r_city < 0.81 THEN 'Нижний Новгород'
        WHEN r.r_city < 0.88 THEN 'Краснодар'
        WHEN r.r_city < 0.93 THEN 'Самара'
        WHEN r.r_city < 0.97 THEN 'Ростов-на-Дону'
        ELSE 'Воронеж'
    END,
    CASE WHEN r.r_segment < 0.80 THEN 'b2c' WHEN r.r_segment < 0.95 THEN 'b2b' ELSE 'vip' END,
    TIMESTAMPTZ '2023-06-01 00:00:00+00' + make_interval(days => floor(r.r_reg * 580)::int)
FROM generate_series(1, 2000) AS g
CROSS JOIN LATERAL (
    SELECT random() AS r_gender, random() AS r_last, random() AS r_first,
           random() AS r_city, random() AS r_segment, random() AS r_reg, g AS _g
) AS r;

-- Orders: daily volume = base * seasonality * trend * noise -----------------
INSERT INTO orders (customer_id, status, channel, created_at)
SELECT
    1 + floor(r.r_customer * 2000)::int,
    CASE WHEN r.r_status < 0.88 THEN 'completed'
         WHEN r.r_status < 0.94 THEN 'cancelled'
         WHEN r.r_status < 0.98 THEN 'returned'
         ELSE 'pending' END,
    CASE WHEN r.r_channel < 0.45 THEN 'web'
         WHEN r.r_channel < 0.75 THEN 'mobile'
         WHEN r.r_channel < 0.90 THEN 'marketplace'
         WHEN r.r_channel < 0.97 THEN 'offline'
         ELSE NULL END,
    (d.day + make_interval(secs => floor(r.r_time * 86400)::int)) AT TIME ZONE 'UTC'
FROM generate_series(TIMESTAMP '2025-01-01', TIMESTAMP '2026-10-31', INTERVAL '1 day') AS d (day)
CROSS JOIN LATERAL generate_series(
    1,
    greatest(5, round(
        38
        * (ARRAY[0.90, 0.85, 0.95, 1.00, 0.95, 0.95, 0.90, 0.95, 1.00, 1.05, 1.35, 1.50])[extract(month FROM d.day)::int]
        * (1 + 0.25 * extract(epoch FROM d.day - TIMESTAMP '2025-01-01') / (86400 * 668))
        * (0.8 + 0.4 * random())
    )::int)
) AS n
CROSS JOIN LATERAL (
    SELECT random() AS r_customer, random() AS r_status, random() AS r_channel, random() AS r_time, n AS _n
) AS r;

-- Order items: 1..3 positions per order ---------------------------------------
INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount)
SELECT
    o.id,
    pr.id,
    1 + floor(power(r.r_qty, 3) * 4)::int,
    round(pr.price * (0.92 + r.r_price * 0.12)::numeric, 2),
    CASE WHEN r.r_disc < 0.70 THEN 0 WHEN r.r_disc < 0.85 THEN 5 WHEN r.r_disc < 0.95 THEN 10 ELSE 15 END
FROM orders o
CROSS JOIN LATERAL generate_series(1, 1 + floor(random() * 3 + o.id * 0)::int) AS k
CROSS JOIN LATERAL (
    SELECT random() AS r_product, random() AS r_qty, random() AS r_price, random() AS r_disc, k AS _k
) AS r
JOIN products pr ON pr.id = 1 + floor(r.r_product * 120)::int;

-- Server equipment is a rare, expensive purchase: keep ~25% of its positions.
DELETE FROM order_items oi
USING products p, categories c
WHERE oi.product_id = p.id
  AND p.category_id = c.id
  AND c.name = 'Серверное оборудование'
  AND random() + oi.id * 0 < 0.75;

-- Planted anomaly: Q2 2026 demand drop.
DELETE FROM order_items oi
USING orders o, products p, categories c
WHERE oi.order_id = o.id
  AND oi.product_id = p.id
  AND p.category_id = c.id
  AND o.created_at >= '2026-04-01' AND o.created_at < '2026-07-01'
  -- `oi.id * 0` ties random() to the item row: otherwise the planner pushes the filter
  -- down to the categories scan and draws one random number per category.
  AND random() + oi.id * 0 < CASE c.name
                     WHEN 'Аудио' THEN 0.55
                     WHEN 'Игры и консоли' THEN 0.40
                     WHEN 'Смартфоны' THEN 0.30
                     ELSE 0
                 END;

-- Planted anomaly: Q2 2026 laptop boom (extra laptop positions).
INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount)
SELECT o.id, pr.id, 1, round(pr.price * 0.97, 2), 0
FROM orders o
CROSS JOIN LATERAL (SELECT random() AS r_pick, random() AS r_take, o.id AS _id) AS r
JOIN products pr ON pr.id = 1 + floor(r.r_pick * 15)::int
WHERE o.created_at >= '2026-04-01' AND o.created_at < '2026-07-01'
  AND r.r_take < 0.12;

-- Orders that lost all positions are removed.
DELETE FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.id);

ANALYZE;

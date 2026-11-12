-- Synthetic e-commerce schema for agentic-sql-analyst.
-- Executed automatically by the postgres image on first start (docker-entrypoint-initdb.d).

CREATE TABLE categories (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
COMMENT ON TABLE categories IS 'Категории товаров';
COMMENT ON COLUMN categories.name IS 'Название категории (например, Ноутбуки)';

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        TEXT          NOT NULL,
    category_id INTEGER       NOT NULL REFERENCES categories (id),
    price       NUMERIC(12, 2) NOT NULL CHECK (price > 0),
    cost        NUMERIC(12, 2) NOT NULL CHECK (cost > 0),
    is_active   BOOLEAN       NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE products IS 'Каталог товаров';
COMMENT ON COLUMN products.price IS 'Текущая розничная цена, руб.';
COMMENT ON COLUMN products.cost IS 'Себестоимость единицы товара, руб.';

CREATE TABLE customers (
    id            SERIAL PRIMARY KEY,
    full_name     TEXT        NOT NULL,
    email         TEXT        NOT NULL UNIQUE,
    city          TEXT,
    segment       TEXT        NOT NULL CHECK (segment IN ('b2c', 'b2b', 'vip')),
    registered_at TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE customers IS 'Клиенты магазина';
COMMENT ON COLUMN customers.city IS 'Город клиента, может быть NULL (не указан)';
COMMENT ON COLUMN customers.segment IS 'Сегмент клиента: b2c, b2b, vip';

CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER     NOT NULL REFERENCES customers (id),
    status      TEXT        NOT NULL CHECK (status IN ('completed', 'cancelled', 'returned', 'pending')),
    channel     TEXT CHECK (channel IN ('web', 'mobile', 'marketplace', 'offline')),
    created_at  TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE orders IS 'Заказы. Выручку считают только по status = completed';
COMMENT ON COLUMN orders.channel IS 'Канал продаж, может быть NULL (неизвестен)';
COMMENT ON COLUMN orders.created_at IS 'Дата и время оформления заказа';

CREATE TABLE order_items (
    id         SERIAL PRIMARY KEY,
    order_id   INTEGER       NOT NULL REFERENCES orders (id),
    product_id INTEGER       NOT NULL REFERENCES products (id),
    quantity   INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price > 0),
    discount   NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount < 100)
);
COMMENT ON TABLE order_items IS 'Позиции заказа. Выручка позиции = quantity * unit_price * (1 - discount / 100)';
COMMENT ON COLUMN order_items.unit_price IS 'Цена за единицу на момент покупки, руб.';
COMMENT ON COLUMN order_items.discount IS 'Скидка в процентах (0-99)';

CREATE INDEX idx_orders_created_at ON orders (created_at);
CREATE INDEX idx_orders_customer_id ON orders (customer_id);
CREATE INDEX idx_order_items_order_id ON order_items (order_id);
CREATE INDEX idx_order_items_product_id ON order_items (product_id);
CREATE INDEX idx_products_category_id ON products (category_id);

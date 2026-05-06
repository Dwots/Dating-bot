-- Practice database for SQL isolation anomalies.
-- The script is compatible with MySQL and MariaDB.

-- Recreate the database so the practice starts from the same state.
DROP DATABASE IF EXISTS isolation_practice;
CREATE DATABASE isolation_practice;
USE isolation_practice;

-- Accounts table: useful for balance-related examples.
-- It will be used for non-repeatable read and lost update.
CREATE TABLE accounts (
    id INT PRIMARY KEY,
    owner_name VARCHAR(50) NOT NULL,
    balance INT NOT NULL
) ENGINE=InnoDB;

-- Products table: useful for reading uncommitted price changes.
-- It will be used for dirty read.
CREATE TABLE products (
    id INT PRIMARY KEY,
    product_name VARCHAR(50) NOT NULL,
    price INT NOT NULL
) ENGINE=InnoDB;

-- Orders table: useful for queries that return a set of rows.
-- It will be used for phantom read.
CREATE TABLE orders (
    id INT PRIMARY KEY,
    customer_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    amount INT NOT NULL
) ENGINE=InnoDB;

-- Test data for accounts.
INSERT INTO accounts (id, owner_name, balance) VALUES
    (1, 'Alice', 1000),
    (2, 'Bob', 500);

-- Test data for products.
INSERT INTO products (id, product_name, price) VALUES
    (1, 'Phone', 1000),
    (2, 'Laptop', 2000);

-- Test data for orders.
INSERT INTO orders (id, customer_name, status, amount) VALUES
    (1, 'Alice', 'new', 100),
    (2, 'Bob', 'paid', 200),
    (3, 'Carol', 'new', 300);

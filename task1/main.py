import psycopg2

try:
    conn = psycopg2.connect(
        dbname='sm_task1', 
        user='postgres',
        password='secret',
        host='postgres'
    )
except Exception as e:
    print(f'Can`t establish connection: {e}')


def create_tables():
    try:
        with conn.cursor() as curs:
            curs.execute('''
            CREATE TABLE IF NOT EXISTS Customers (
                id SERIAL PRIMARY KEY,
                FirstName TEXT NOT NULL,
                LastName TEXT NOT NULL,
                Email TEXT UNIQUE
                )
            ''')

            curs.execute('''
            CREATE TABLE IF NOT EXISTS Products (
                id SERIAL PRIMARY KEY,
                ProductName TEXT NOT NULL,
                Price DECIMAL(10,2) NOT NULL   
                )
            ''')

            curs.execute('''
            CREATE TABLE IF NOT EXISTS Orders (
                id SERIAL PRIMARY KEY,
                CustomerID INT REFERENCES Customers(id),
                OrderDate DATE NOT NULL,
                TotalAmount DECIMAL(10,2) NOT NULL
                )
            ''')

            curs.execute('''
            CREATE TABLE IF NOT EXISTS OrderItems (
                id SERIAL PRIMARY KEY,
                OrderID INT REFERENCES Orders(id),
                ProductID INT REFERENCES Products(id),
                Quantity INT NOT NULL,
                Subtotal DECIMAL(10,2) NOT NULL
                )
            ''')

            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'Error creating tables: {e}')

def insert_sample_data():
    try:
        with conn.cursor() as curs:
            curs.execute("INSERT INTO Customers (FirstName, LastName, Email) VALUES ('Test1', 'Test1', 'test1@gmail.com') RETURNING id")
            customer_id1 = curs.fetchone()[0]

            curs.execute("INSERT INTO Customers (FirstName, LastName, Email) VALUES ('Test2', 'Test2', 'test2@gmail.com') RETURNING id")
            customer_id2 = curs.fetchone()[0]

            curs.execute("INSERT INTO Products (ProductName, Price) VALUES ('Monitor', 15000) RETURNING id")
            monitor_id = curs.fetchone()[0]

            curs.execute("INSERT INTO Products (ProductName, Price) VALUES ('PC', 95000) RETURNING id")
            pc_id = curs.fetchone()[0]

            curs.execute("INSERT INTO Products (ProductName, Price) VALUES ('Laptop', 50000) RETURNING id")
            laptop_id = curs.fetchone()[0]

            curs.execute("INSERT INTO Orders (CustomerID, OrderDate, TotalAmount) VALUES (%s, '2026-01-01', 0) RETURNING id",
                        (customer_id1,))
            order_id1 = curs.fetchone()[0]

            curs.execute("INSERT INTO Orders (CustomerID, OrderDate, TotalAmount) VALUES (%s, '2026-01-02', 0) RETURNING id",
                        (customer_id2,))
            order_id2 = curs.fetchone()[0]

            curs.execute("INSERT INTO OrderItems (OrderID, ProductID, Quantity, Subtotal) VALUES (%s, %s, 1, 15000)",
                        (order_id1, monitor_id))

            curs.execute("INSERT INTO OrderItems (OrderID, ProductID, Quantity, Subtotal) VALUES (%s, %s, 1, 50000)",
                        (order_id2, laptop_id))
            
            curs.execute("UPDATE Orders SET TotalAmount = (SELECT SUM(Subtotal) FROM OrderItems WHERE OrderID = Orders.id)")
            conn.commit()

    except Exception as e:
        conn.rollback()
        print(f'Error inserting sample data: {e}')

def update_email(old_email, new_email):
    try:
        with conn.cursor() as curs:
            curs.execute("SELECT id FROM Customers WHERE Email = %s", (old_email,))
            customer_id1 = curs.fetchone()[0]
            curs.execute("UPDATE Customers SET Email = %s WHERE id = %s", (new_email, customer_id1))
            conn.commit()
    
    except Exception as e:
        conn.rollback()
        print(f'Error updating email: {e}')


def add_new_product(ProductName, Price):
    try:
        with conn.cursor() as curs:
            curs.execute("INSERT INTO Products (ProductName, Price) VALUES (%s, %s)", (ProductName, Price))
            conn.commit()

    except Exception as e:
        conn.rollback()
        print(f'Error adding new product: {e}')



if __name__ == "__main__":
    create_tables()
    insert_sample_data()
    update_email('test1@gmail.com', 'newtest1@gmail.com')
    add_new_product('Keyboard', 5000)
    conn.close()
import psycopg2

DB_CONFIG = {
    "dbname": "quotation_maker",
    "user": "rudhrasindhava",
    "password": "",
    "host": "127.0.0.1",
    "port": "5432"
}

def restore_services():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print("Resetting services table...")
    cursor.execute('TRUNCATE TABLE services RESTART IDENTITY CASCADE;')
    
    services = [
        ('Fine Grading', 3.50, 'per sqft'),
        ('Garden Development (small plants)', 30.00, 'per plant'),
        ('Garden Development (big plants)', 100.00, 'per plant'),
        ('After Maintenance', 150000.00, 'per month'),
        ('Extra Charge', 20.00, 'per plant'),
        ('Lawn Cutting', 15000.00, 'per month'),
        ('Pesticides and Fertilizers', 15000.00, 'per month'),
        ('Transportation Charges', 3000.00, 'per tonne')
    ]
    
    cursor.executemany('''
        INSERT INTO services (description, price, unit_type) 
        VALUES (%s, %s, %s)
    ''', services)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Success! Restored 8 detailed services to the database.")

if __name__ == '__main__':
    restore_services()
from src.db_model import engine, Base, Order, Product, Warranty, AsyncSessionLocal
import asyncio
import sqlalchemy

async def create_tables():
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def seed_database():
    """Seed the database with initial data (idempotent)."""
    async with AsyncSessionLocal() as session:
        res = await session.execute(sqlalchemy.select(Order).limit(1))
        if res.scalars().first():
            print("Database already seeded.")
            return

        print("Seeding database...")

        warranty1 = Warranty(
            duration_months=24, 
            terms="Hanya mencakup cacat produksi."
        )
        warranty2 = Warranty(
            duration_months=12, 
            terms="Termasuk perlindungan kerusakan tidak disengaja."
        )
        session.add_all([warranty1, warranty2])
        await session.flush()

        products = [
            Product(
                id="P123",
                name="Headphone Wireless",
                description="Headphone wireless berkualitas tinggi dengan noise cancellation.",
                pros="Kualitas suara yang bagus; Nyaman dipakai; Baterai tahan lama",
                cons="Harga mahal; Case yang besar",
                warranty_id=warranty1.id,
            ),
            Product(
                id="P234",
                name="Smartphone X",
                description="Smartphone generasi terbaru dengan layar OLED dan sistem triple camera.",
                pros="Kamera sangat bagus; Performa cepat; Desain premium",
                cons="Harga tinggi; Tidak ada jack headphone",
                warranty_id=warranty2.id,
            ),
            Product(
                id="P345",
                name="Gaming Laptop Pro",
                description="Laptop gaming yang powerful dengan grafis RTX dan layar high refresh.",
                pros="GPU tingkat atas; SSD cepat; Sistem pendingin yang baik",
                cons="Berat; Baterai cepat habis",
                warranty_id=warranty1.id,
            ),
        ]
        session.add_all(products)
        await session.flush()

        orders = [
            Order(
                order_id="ORD12345", 
                user_id="user1", 
                status="Shipped", 
                tracking="TRACK123", 
                product_id="P123"
            ),
            Order(
                order_id="ORD23456", 
                user_id="user2", 
                status="Processing", 
                tracking=None, 
                product_id="P234"
            ),
            Order(
                order_id="ORD34567", 
                user_id="user1", 
                status="Delivered", 
                tracking="TRACK789", 
                product_id="P345"
            ),
        ]
        session.add_all(orders)

        await session.commit()
        print("Database seeded successfully with orders, warranties, and products.")

async def init_database():
    """Initialize database: create tables and seed data."""
    await create_tables()
    await seed_database()

if __name__ == "__main__":
    asyncio.run(init_database())
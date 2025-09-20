from sqlalchemy.orm import selectinload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db_model import AsyncSessionLocal, Message, Order, Product, Warranty
import sqlalchemy
import json

async def persist_message(user_id: str, role: str, content: str):
    """Store a message in the database."""
    async with AsyncSessionLocal() as session:
        msg = Message(user_id=user_id, role=role, content=content)
        session.add(msg)
        await session.commit()

async def get_last_n_messages(user_id: str, n: int = 3):
    """Retrieve the last n messages for a user."""
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            sqlalchemy.select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(n)
        )
        results = q.scalars().all()
        return [{"role": r.role, "content": r.content} for r in results]

async def get_all_messages_for_user(user_id: str):
    """Get all messages for a user ordered by creation time."""
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            sqlalchemy.select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.created_at)
        )
        items = q.scalars().all()
        return [
            {
                "role": item.role, 
                "content": item.content, 
                "created_at": item.created_at.isoformat()
            }
            for item in items
        ]

async def get_order_status(order_id: str):
    """Get order status by order ID (any user)."""
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.order_id == order_id)
        )
        order = q.scalars().first()
        if not order:
            return {"found": False, "order_id": order_id}
        return {
            "found": True,
            "order_id": order.order_id,
            "status": order.status,
            "tracking": order.tracking,
            "user_id": order.user_id,
            "product_id": order.product.id if order.product else None,
            "product_name": order.product.name if order.product else None,
        }

async def get_user_order_status(session: AsyncSession, user_id: str, order_id: str):
    """Get order status for a specific user's order."""
    q = await session.execute(
        select(Order)
        .options(selectinload(Order.product))
        .where(Order.order_id == order_id, Order.user_id == user_id)
    )
    order = q.scalars().first()
    if not order:
        return {"found": False, "order_id": order_id}
    return {
        "found": True,
        "order_id": order.order_id,
        "status": order.status,
        "tracking": order.tracking,
        "user_id": order.user_id,
        "product_id": order.product.id if order.product else None,
        "product_name": order.product.name if order.product else None,
    }

async def get_latest_order_for_user(session: AsyncSession, user_id: str):
    """Get the most recent order for a user."""
    q = await session.execute(
        select(Order)
        .options(selectinload(Order.product))
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    return q.scalars().first()

async def get_all_orders_for_user(user_id: str):
    """Get all orders for a specific user."""
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
        )
        orders = q.scalars().all()
        return [
            {
                "order_id": order.order_id,
                "status": order.status,
                "tracking": order.tracking,
                "created_at": order.created_at.isoformat(),
                "product_id": order.product.id if order.product else None,
                "product_name": order.product.name if order.product else None,
            }
            for order in orders
        ]

async def get_product_info(session: AsyncSession, product_identifier: str):
    """Get product information by product ID or name."""
    # First try to find by exact product ID
    result = await session.execute(
        select(Product).where(Product.id == product_identifier)
    )
    product = result.scalar_one_or_none()
    
    # If not found and identifier doesn't look like a product ID, try name search
    if not product and not product_identifier.startswith('P'):
        result = await session.execute(
            select(Product)
            .where(Product.name.ilike(f"%{product_identifier}%"))
        )
        product = result.scalars().first()
    
    if product:
        return {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "pros": product.pros,
            "cons": product.cons,
        }
    return None

async def search_product_by_name(session: AsyncSession, product_name: str):
    """Search for product by name (case-insensitive partial match)."""
    result = await session.execute(
        select(Product)
        .where(Product.name.ilike(f"%{product_name}%"))
    )
    products = result.scalars().all()
    return [
        {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "pros": product.pros,
            "cons": product.cons,
        }
        for product in products
    ]

async def get_all_products():
    """Get all products."""
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Product))
        products = q.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "pros": p.pros,
                "cons": p.cons,
                "warranty_id": p.warranty_id,
            }
            for p in products
        ]

async def get_warranty_info(session: AsyncSession, product_identifier: str):
    """Get warranty information for a product by ID or name."""
    # First try to find by exact product ID
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.warranty))
        .where(Product.id == product_identifier)
    )
    product = result.scalar_one_or_none()
    
    # If not found and identifier doesn't look like a product ID, try name search
    if not product and not product_identifier.startswith('P'):
        result = await session.execute(
            select(Product)
            .options(selectinload(Product.warranty))
            .where(Product.name.ilike(f"%{product_identifier}%"))
        )
        product = result.scalars().first()
    
    if product and product.warranty:
        return {
            "product": product.name,
            "product_id": product.id,
            "duration_months": product.warranty.duration_months,
            "terms": product.warranty.terms,
        }
    return None

async def get_all_warranties():
    """Get all warranty policies."""
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Warranty))
        warranties = q.scalars().all()
        return [
            {
                "id": w.id,
                "duration_months": w.duration_months,
                "terms": w.terms,
            }
            for w in warranties
        ]